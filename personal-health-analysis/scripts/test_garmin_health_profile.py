import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import garmin_health_profile as profile


class GarminHealthProfileTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("GARMIN_TEST_TEMP_DIR")
        if parent:
            self.root = Path(parent)
            self.database = self.root / f"garmin-profile-{uuid.uuid4().hex}.db"
        else:
            self.root = Path(tempfile.mkdtemp(prefix="garmin-profile-"))
            self.database = self.root / "garmin.db"
        self.root.mkdir(parents=True, exist_ok=True)
        self.activity_database = self.root / f"garmin-activities-{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE attributes (timestamp TEXT, key TEXT, value TEXT);
            CREATE TABLE weight (day TEXT PRIMARY KEY, weight REAL NOT NULL);
            CREATE TABLE daily_summary (
                day TEXT, rhr REAL, stress_avg REAL, steps REAL,
                moderate_activity_time TEXT, vigorous_activity_time TEXT,
                intensity_time_goal TEXT, calories_active REAL, distance REAL,
                floors_up REAL, bb_charged REAL, bb_max REAL, bb_min REAL,
                spo2_avg REAL, spo2_min REAL, rr_waking_avg REAL
            );
            CREATE TABLE sleep (
                day TEXT, start TEXT, end TEXT, total_sleep TEXT, awake TEXT,
                deep_sleep TEXT, light_sleep TEXT, rem_sleep TEXT, score REAL,
                avg_spo2 REAL, avg_rr REAL, avg_stress REAL
            );
            CREATE TABLE hrv (
                day TEXT, weekly_avg REAL, last_night_avg REAL,
                last_night_5min_high REAL, baseline_low REAL,
                baseline_upper REAL, status TEXT
            );
            """
        )
        today = date.today()
        for offset in range(7, -1, -1):
            day = today - timedelta(days=offset)
            day_text = day.isoformat()
            rhr = 10 if offset == 7 else 60 + offset
            connection.execute(
                "INSERT INTO daily_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    day_text, rhr, 30, 8000, "00:20:00", "00:10:00",
                    "02:30:00", 400, 6000, 5, 55, 80, 20, 96, 93, 14,
                ),
            )
            start = datetime.combine(day, datetime.min.time()).replace(hour=23)
            end = start + timedelta(hours=8)
            connection.execute(
                "INSERT INTO sleep VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    day_text, start.isoformat(sep=" "), end.isoformat(sep=" "),
                    "07:30:00", "00:30:00", "01:20:00", "04:40:00",
                    "01:30:00", 80, 96, 14, 20,
                ),
            )
            connection.execute(
                "INSERT INTO hrv VALUES (?, ?, ?, ?, ?, ?, ?)",
                (day_text, 42, 43, 70, 35, 50, "BALANCED"),
            )
            connection.execute("INSERT INTO weight VALUES (?, ?)", (day_text, 78 + offset / 10))
        connection.execute(
            "INSERT INTO weight VALUES (?, ?)",
            ((today - timedelta(days=20)).isoformat(), 80.0),
        )
        connection.execute(
            "INSERT INTO attributes VALUES (?, ?, ?)",
            (datetime.now().isoformat(sep=" "), "vo2max_running", "45.5"),
        )
        connection.commit()
        connection.close()
        activity_connection = sqlite3.connect(self.activity_database)
        activity_connection.execute(
            """
            CREATE TABLE activities (
                type TEXT, start_time TEXT, elapsed_time TEXT, moving_time TEXT,
                distance REAL, avg_hr REAL, max_hr REAL, calories REAL,
                training_load REAL, training_effect REAL,
                anaerobic_training_effect REAL,
                name TEXT, description TEXT, activity_id TEXT,
                start_lat REAL, start_long REAL
            )
            """
        )
        for offset in (0, 3, 20):
            started = datetime.combine(today - timedelta(days=offset), datetime.min.time()).replace(hour=7)
            activity_connection.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "running", started.isoformat(sep=" "), "00:30:00", "00:25:00",
                    5000, 130, 160, 300, 50, 2.5, 0.4,
                    "private name", "private description", f"id-{offset}", 1.0, 2.0,
                ),
            )
        activity_connection.commit()
        activity_connection.close()

    def tearDown(self):
        if os.environ.get("GARMIN_TEST_TEMP_DIR"):
            for database in (self.database, self.activity_database):
                for suffix in ("", "-wal", "-shm"):
                    Path(f"{database}{suffix}").unlink(missing_ok=True)
        else:
            shutil.rmtree(self.root, ignore_errors=True)

    def test_exact_window_and_multidimensional_modules(self):
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            result = profile.build_profile(7, "Asia/Shanghai", False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["requested_window"]["days"], 7)
        self.assertEqual(
            result["modules"]["autonomic_recovery"]["resting_heart_rate"]["minimum"],
            60,
        )
        self.assertEqual(
            result["modules"]["sleep_health"]["timing_regularity"]["status"],
            "eligible",
        )
        self.assertEqual(
            result["modules"]["autonomic_recovery"]["hrv"]["latest_vendor_context"]["derived_alignment"],
            "within_vendor_baseline",
        )
        self.assertEqual(
            result["modules"]["movement"]["who_guideline_comparison"]["status"],
            "not_evaluated_population_not_confirmed",
        )
        self.assertEqual(result["schema"], "garmin-health-profile.v2")
        self.assertEqual(result["modules"]["body_weight"]["status"], "available")
        self.assertEqual(result["modules"]["body_weight"]["window_measurement_count"], 7)
        self.assertEqual(result["modules"]["recorded_activities"]["window_summary"]["record_count"], 2)
        self.assertEqual(result["modules"]["recorded_activities"]["window_summary"]["total_distance_km"], 10.0)
        self.assertFalse(result["modules"]["recorded_activities"]["privacy"]["location_fields_read"])
        self.assertEqual(result["guidance_contract"]["composite_health_score"], "not_scored")
        self.assertEqual(
            result["provenance"]["database_integrity"]["status"],
            "verified_unchanged",
        )
        self.assertEqual(len(result["provenance"]["database_integrity"]["databases"]), 2)

    def test_timezone_is_required_for_naive_sleep_timing(self):
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            result = profile.build_profile(7, None, False)
        timing = result["modules"]["sleep_health"]["timing_regularity"]
        self.assertEqual(timing["status"], "timezone_required")

    def test_adult_guideline_is_opt_in_and_not_training_clearance(self):
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            result = profile.build_profile(7, "Asia/Shanghai", True)
        guideline = result["modules"]["movement"]["who_guideline_comparison"]
        self.assertEqual(guideline["status"], "observed_at_or_above_minimum_equivalent")
        self.assertEqual(guideline["classification_scope"], "public_health_reference_not_training_clearance")
        self.assertEqual(result["guidance_contract"]["training_clearance"], "not_provided")

    def test_sparse_weight_and_activity_report_prior_freshness_without_expanding_window(self):
        start = (date.today() - timedelta(days=6)).isoformat()
        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM weight WHERE date(day) >= ?", (start,))
        connection.commit()
        connection.close()
        activity_connection = sqlite3.connect(self.activity_database)
        activity_connection.execute("DELETE FROM activities WHERE date(start_time) >= ?", (start,))
        activity_connection.commit()
        activity_connection.close()

        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            result = profile.build_profile(7, "Asia/Shanghai", False)

        weight = result["modules"]["body_weight"]
        activities = result["modules"]["recorded_activities"]
        self.assertEqual(weight["status"], "no_window_observations_prior_available")
        self.assertEqual(weight["window_measurement_count"], 0)
        self.assertTrue(weight["latest_as_of_window_end"]["outside_requested_window"])
        self.assertEqual(activities["status"], "no_window_records_prior_available")
        self.assertEqual(activities["window_summary"]["record_count"], 0)
        self.assertTrue(activities["latest_as_of_window_end"]["outside_requested_window"])

    def test_weight_trend_requires_three_observations_and_fourteen_day_span(self):
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            short = profile.build_profile(7, "Asia/Shanghai", False)
            long = profile.build_profile(21, "Asia/Shanghai", False)

        self.assertEqual(
            short["modules"]["body_weight"]["window_trend"]["status"],
            "insufficient_observations_or_span",
        )
        self.assertEqual(
            long["modules"]["body_weight"]["window_trend"]["status"],
            "eligible_descriptive_only",
        )

    def test_missing_activity_database_does_not_hide_other_health_modules(self):
        missing = self.root / "missing-activities.db"
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", missing),
        ):
            result = profile.build_profile(7, "Asia/Shanghai", False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["modules"]["recorded_activities"]["status"], "source_unavailable")
        self.assertEqual(result["provenance"]["database_integrity"]["databases"], [self.database.name])
        insights = result["problem_insights"]
        activity = insights["items"][2]
        self.assertEqual(activity["qualification"]["status"], "descriptive_available")
        self.assertIsNone(activity["observations"][-1]["value"])
        self.assertEqual(insights["optional_actions"][0]["id"], "verify_observation_coverage")
        self.assertEqual(insights["optional_actions"][0]["applies_to"], [activity["id"]])
        self.assertLessEqual(len(insights["optional_actions"]), 2)

    def test_timestamp_only_sleep_keeps_three_day_timing_observations(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE sleep SET total_sleep = NULL, awake = NULL")
            connection.commit()
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
        ):
            result = profile.build_profile(3, "Asia/Shanghai", False)
        insights = result["problem_insights"]
        sleep = insights["items"][0]
        observations = {obs["metric"]: obs for obs in sleep["observations"]}
        self.assertIsNone(observations["sleep_duration"]["value"])
        self.assertEqual(observations["sleep_onset_dispersion"]["value"], 0)
        self.assertEqual(observations["sleep_onset_dispersion"]["sample_count"], 3)
        self.assertEqual(sleep["qualification"]["status"], "partial_observation")
        self.assertEqual(sleep["qualification"]["formal_regularity_status"], "insufficient_window")
        self.assertIn(sleep["id"], insights["optional_actions"][0]["applies_to"])
        self.assertEqual(result["requested_window"]["days"], 3)

    def test_one_day_cli_preserves_minimal_window_and_field_semantics(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE daily_summary SET moderate_activity_time = '00:00:00', vigorous_activity_time = NULL WHERE day = ?", (date.today().isoformat(),))
            connection.commit()
        output = io.StringIO()
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
            contextlib.redirect_stdout(output),
        ):
            code = profile.main(["--source", "local", "--days", "1", "--timezone", "Asia/Shanghai", "--allow-health-data"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        today = date.today().isoformat()
        self.assertEqual(result["requested_window"], {"start": today, "end": today, "days": 1})
        sleep, _, activity = result["problem_insights"]["items"]
        self.assertEqual(sleep["qualification"]["formal_regularity_status"], "insufficient_window")
        self.assertEqual(sleep["observations"][0]["observed_date"], today)
        self.assertEqual(activity["qualification"]["goal_comparison_status"], "insufficient_week_coverage")
        self.assertEqual(activity["observations"][0]["value"], 0)
        self.assertIsNone(activity["observations"][1]["value"])
        self.assertIsNone(activity["observations"][3]["value"])
        self.assertEqual(activity["observations"][0]["coverage"]["requested_days"], 1)
        self.assertEqual(activity["observations"][0]["window"], {"start": today, "end": today})
        self.assertLessEqual(len(result["problem_insights"]["optional_actions"]), 2)
        self.assertEqual(result["provenance"]["database_integrity"]["status"], "verified_unchanged")

    def test_cli_emits_problem_insights_from_same_synthetic_database_read_set(self):
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
            mock.patch.object(profile, "_read_supported_rows", wraps=profile._read_supported_rows) as read_rows,
        ):
            with mock.patch.object(profile, "_problem_insights", return_value={}):
                profile.build_profile(7, "Asia/Shanghai", False)
            prior_queries = [call.args[1:] for call in read_rows.call_args_list]
            read_rows.reset_mock()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = profile.main(["--source", "local", "--days", "7", "--timezone", "Asia/Shanghai", "--allow-health-data"])
            self.assertEqual([call.args[1:] for call in read_rows.call_args_list], prior_queries)
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["schema"], "garmin-health-profile.v2")
        self.assertEqual(result["problem_insights"]["schema"], "problem-insights.v1")
        self.assertEqual(len(result["problem_insights"]["items"]), 3)
        self.assertEqual(result["requested_window"]["days"], 7)
        self.assertFalse(result["problem_insights"]["privacy"]["additional_data_reads"])

    def test_empty_synthetic_profile_cli_keeps_no_data_and_bounded_insights(self):
        connection = sqlite3.connect(self.database)
        for table in ("daily_summary", "sleep", "hrv", "weight", "attributes"):
            connection.execute(f'DELETE FROM "{table}"')
        connection.commit()
        connection.close()
        connection = sqlite3.connect(self.activity_database)
        connection.execute("DELETE FROM activities")
        connection.commit()
        connection.close()
        output = io.StringIO()
        with (
            mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
            mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
            contextlib.redirect_stdout(output),
        ):
            code = profile.main(["--source", "local", "--days", "7", "--allow-health-data"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["problem_insights"]["data_status"], "no_data")
        self.assertEqual([action["id"] for action in result["problem_insights"]["optional_actions"]], ["verify_observation_coverage"])

    def test_optional_context_cli_preserves_p1_and_database_read_set_without_writes(self):
        context_path = self.root / "SYNTHETIC-CONTEXT-NOT-OUTPUT.json"
        context_path.write_text(json.dumps({"schema_version": 1, "records": [{"date": date.today().isoformat(), "sleep_opportunity_minutes": 480, "subjective_daytime_sleepiness": "low", "caffeine_last_time": "13:47", "user_selected_action": profile.CONTEXT_ACTION, "performed": False}]}), encoding="utf-8")
        before = {path: path.read_bytes() for path in (context_path, self.database, self.activity_database)}
        names_before = set(self.root.iterdir())
        try:
            with (
                mock.patch.object(profile.adapter, "GARMIN_DB", self.database),
                mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database),
                mock.patch.object(profile, "_read_supported_rows", wraps=profile._read_supported_rows) as reads,
                mock.patch("socket.socket", side_effect=AssertionError("no network")),
            ):
                with mock.patch.object(profile, "_load_context", side_effect=AssertionError("omitted context must not read")):
                    omitted = profile.build_profile(14, "Asia/Shanghai", False)
                    self.assertEqual(omitted, profile.build_profile(14, "Asia/Shanghai", False, None))
                prior_queries = [call.args[1:] for call in reads.call_args_list][:5]
                reads.reset_mock()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = profile.main(["--source", "local", "--days", "14", "--timezone", "Asia/Shanghai", "--allow-health-data", "--context-file", str(context_path)])
                self.assertEqual([call.args[1:] for call in reads.call_args_list], prior_queries)
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["modules"], omitted["modules"])
            self.assertEqual(result["problem_insights"]["items"][0]["qualification"], omitted["problem_insights"]["items"][0]["qualification"])
            self.assertEqual(result["problem_insights"]["items"][0]["qualification"]["formal_regularity_status"], "epoch_unknown")
            self.assertIsNone(result["modules"]["sleep_health"]["qualified_regularity"]["baseline_comparable"])
            self.assertEqual(result["problem_insights"]["optional_actions"], omitted["problem_insights"]["optional_actions"])
            self.assertLessEqual(len(result["problem_insights"]["optional_actions"]), 2)
            self.assertEqual(result["user_context_review"]["source"], "USER-REPORTED")
            self.assertTrue(result["problem_insights"]["privacy"]["explicit_user_context_read"])
            self.assertFalse(result["problem_insights"]["privacy"]["additional_database_reads"])
            self.assertIn("complete_user_reported_sleep_opportunity", result["problem_insights"]["items"][0]["missing_evidence"])
            for marker in (str(context_path), context_path.name, "13:47", "caffeine_last_time", '"performed"'):
                self.assertNotIn(marker, output.getvalue())
            self.assertEqual(set(self.root.iterdir()), names_before)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
        finally:
            context_path.unlink()

    def test_context_permission_and_invalid_input_fail_before_any_database_access(self):
        path = self.root / "SYNTHETIC-PRIVATE-CONTEXT.json"
        args = ["--source", "local", "--days", "1", "--context-file", str(path)]
        with mock.patch.object(profile, "_load_context", side_effect=AssertionError("no context read without permission")), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(profile.main(args), 2)
            self.assertIn("HEALTH_DATA_AUTH_REQUIRED", stderr.getvalue())
        try:
            with mock.patch.object(profile.adapter, "resolve_database_path", side_effect=AssertionError("no DB resolution")), mock.patch.object(profile.adapter, "get_connection", side_effect=AssertionError("no DB read")):
                for rows in ([{"date": (date.today() + timedelta(days=1)).isoformat()}], [{"date": (date.today() - timedelta(days=1)).isoformat()}], [{"date": date.today().isoformat(), "symptoms": "SYNTHETIC-PROSE"}]):
                    path.write_text(json.dumps({"schema_version": 1, "records": rows}), encoding="utf-8")
                    with contextlib.redirect_stderr(io.StringIO()) as stderr:
                        self.assertEqual(profile.main(args + ["--allow-health-data"]), 2)
                        self.assertEqual(json.loads(stderr.getvalue()), {"status": "invalid_context", "error_code": "CONTEXT_INVALID"})
                path.unlink()
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(profile.main(args + ["--allow-health-data"]), 4)
                    error = json.loads(stderr.getvalue())
                    self.assertEqual(error["error_code"], "CONTEXT_READ_ERROR")
                    self.assertEqual(error["error_type"], "FileNotFoundError")
                    self.assertNotIn(str(path), stderr.getvalue())
        finally:
            path.unlink(missing_ok=True)

    def test_one_day_context_without_device_data_does_not_create_trend_or_objective_data(self):
        path = self.root / "synthetic-context.json"
        path.write_text(json.dumps({"schema_version": 1, "records": [{"date": date.today().isoformat(), "sleep_opportunity_minutes": 0, "user_selected_action": profile.CONTEXT_ACTION, "performed": False}]}), encoding="utf-8")
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.executescript("DELETE FROM daily_summary; DELETE FROM sleep; DELETE FROM hrv; DELETE FROM weight; DELETE FROM attributes;")
            connection.commit()
        with contextlib.closing(sqlite3.connect(self.activity_database)) as connection:
            connection.execute("DELETE FROM activities")
            connection.commit()
        try:
            with mock.patch.object(profile.adapter, "GARMIN_DB", self.database), mock.patch.object(profile.adapter, "ACTIVITIES_DB", self.activity_database), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(profile.main(["--source", "local", "--days", "1", "--allow-health-data", "--context-file", str(path)]), 3)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "no_data")
            self.assertEqual(result["requested_window"]["days"], 1)
            self.assertEqual(result["problem_insights"]["items"][0]["qualification"]["formal_regularity_status"], "insufficient_window")
            summary = result["user_context_review"]["summary"]
            self.assertEqual(summary["sleep_opportunity_median_minutes"], 0)
            self.assertEqual(summary["action_not_completed_days"], 1)
            self.assertEqual(summary["action_missing_days"], 0)
            self.assertEqual(summary["paired_sleep_duration_days"], 0)
            self.assertEqual(result["user_context_review"]["effectiveness"], "not_evaluated")
        finally:
            path.unlink()

    def test_cli_keeps_health_and_network_gates(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = profile.main(["--source", "local", "--days", "7"])
        self.assertEqual(code, 2)
        self.assertIn("HEALTH_DATA_AUTH_REQUIRED", stderr.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = profile.main(
                [
                    "--source", "local", "--days", "7",
                    "--allow-health-data", "--allow-network",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("NETWORK_NOT_ALLOWED_FOR_LOCAL_SOURCE", stderr.getvalue())


class UserContextValidationTests(unittest.TestCase):
    def setUp(self):
        self.dates = ["2026-07-01", "2026-07-02", "2026-07-03"]

    def validate(self, rows):
        return profile._validate_context({"schema_version": 1, "records": rows}, self.dates)

    def test_strict_schema_rejects_unknown_fields_types_ranges_and_dates(self):
        invalid = [
            {"date": "2026-07-04"}, {"date": "2026-06-30"}, {"date": "2026-7-1"},
            {"date": "2026-02-30"}, {"date": True}, {"date": []},
            {"date": self.dates[0], "prompt": "SYNTHETIC-DO-NOT-ECHO"},
        ]
        for field, values in {
            "sleep_opportunity_minutes": [True, False, None, "480", 480.0, -1, 1441, float("nan"), float("inf")],
            "subjective_daytime_sleepiness": [True, None, [], {}, "severe", "SYNTHETIC-PROSE"],
            "caffeine_last_time": [None, True, 1200, "24:00", "7:00", "12:60", "１２:００", "12:00Z", "https://invalid"],
            "user_selected_action": [None, False, {}, "change_medication", "review_device_goal_context"],
            "performed": [True, False, None, 0, 1, "false"],  # No action selected.
            "phase": ["baseline", "observation", "treatment", [], None],
        }.items():
            invalid.extend({"date": self.dates[0], field: value} for value in values)
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(profile.ContextValidationError):
                self.validate([row])
        for payload in (None, [], {}, {"schema_version": True, "records": []}, {"schema_version": 1.0, "records": []}, {"schema_version": 1, "records": [], "path": "private"}, {"schema_version": 1, "records": {}}, {"schema_version": 1, "records": [None]}):
            with self.subTest(payload=payload), self.assertRaises(profile.ContextValidationError):
                profile._validate_context(payload, self.dates)
        with self.assertRaises(profile.ContextValidationError):
            self.validate([{"date": self.dates[0]}] * 2)
        with self.assertRaises(profile.ContextValidationError):
            self.validate([{"date": self.dates[0]}] * 367)

    def test_single_action_phase_validation_and_boolean_pitfalls(self):
        rows = [{"date": day, "user_selected_action": profile.CONTEXT_ACTION, "phase": phase} for day, phase in zip(self.dates, ("baseline", "observation", "observation"), strict=True)]
        self.assertEqual(self.validate(rows[::-1]), rows)
        for value in (0, 1, None, "false", []):
            with self.subTest(value=value), self.assertRaises(profile.ContextValidationError):
                self.validate([{**rows[0], "performed": value}])
        for phases in (("observation", "baseline", "observation"), ("baseline", None, "observation")):
            bad = [{**row, "phase": phase} for row, phase in zip(rows, phases, strict=True)]
            with self.assertRaises(profile.ContextValidationError):
                self.validate(bad)
        mixed = [rows[0], {"date": self.dates[1], "user_selected_action": profile.CONTEXT_ACTION}]
        with self.assertRaises(profile.ContextValidationError):
            self.validate(mixed)

    def test_counts_missing_false_zero_phase_coverage_and_no_effectiveness(self):
        rows = self.validate([
            {"date": self.dates[0], "sleep_opportunity_minutes": 0, "subjective_daytime_sleepiness": "low", "caffeine_last_time": "00:00", "user_selected_action": profile.CONTEXT_ACTION, "performed": False, "phase": "baseline"},
            {"date": self.dates[1], "user_selected_action": profile.CONTEXT_ACTION, "phase": "observation"},
            {"date": self.dates[2], "sleep_opportunity_minutes": 480, "user_selected_action": profile.CONTEXT_ACTION, "performed": True, "phase": "observation"},
        ])
        result = profile._context_review(rows, self.dates, [{"date": self.dates[0], "total_sleep": 3600}, {"date": self.dates[2], "total_sleep": 25200}])
        summary = result["summary"]
        self.assertEqual([summary[key] for key in ("action_recorded_days", "action_completed_days", "action_not_completed_days", "action_missing_days")], [2, 1, 1, 1])
        self.assertEqual(summary["sleep_opportunity_median_minutes"], 240)
        self.assertEqual(summary["sleepiness_category_counts"], {"low": 1, "moderate": 0, "high": 0})
        self.assertEqual(summary["paired_sleep_duration_days"], 2)
        self.assertEqual(result["phases"]["baseline"]["sleep_opportunity_median_minutes"], 0)
        self.assertEqual(result["phases"]["observation"]["start"], self.dates[1])
        self.assertEqual(result["phases"]["observation"]["action_missing_days"], 1)
        self.assertEqual(result["phase_comparison"], {"sleep_opportunity": "descriptive_side_by_side_only", "sleepiness": "insufficient_evidence"})
        self.assertEqual(result["effectiveness"], "not_evaluated")
        self.assertEqual(result["objective_outcome_comparison"], "not_evaluated")
        serialized = json.dumps(result)
        for raw in ("caffeine_last_time", "00:00", '"records"', '"performed"', '"date"'):
            self.assertNotIn(raw, serialized)

    def test_empty_short_and_conflicted_device_fields_never_create_evidence(self):
        empty = profile._context_review([], self.dates[:1], [])
        self.assertEqual(empty["summary"]["action_missing_days"], 1)
        self.assertIsNone(empty["selected_action_id"])
        self.assertEqual(empty["action_review_status"], "not_evaluated")
        self.assertIsNone(empty["summary"]["sleep_opportunity_median_minutes"])
        self.assertEqual(empty["phase_comparison"]["sleepiness"], "insufficient_evidence")
        rows = self.validate([{"date": self.dates[0], "sleep_opportunity_minutes": 1440}])
        sleep = [{"date": self.dates[0], "total_sleep": value} for value in (3600, 7200)]
        result = profile._context_review(rows, self.dates, sleep)
        self.assertEqual(result["summary"]["paired_sleep_duration_days"], 0)
        self.assertIsNone(result["summary"]["paired_device_sleep_duration_median_minutes"])
        self.assertEqual(result["summary"]["pairing_status"], "insufficient_evidence")
        self.assertEqual(result["phases"], {})

    def test_reparse_symlink_and_mapped_network_paths_fail_before_open(self):
        with mock.patch.object(Path, "lstat", return_value=mock.Mock(st_mode=profile.stat.S_IFLNK, st_file_attributes=0)), mock.patch.object(Path, "open", side_effect=AssertionError("must not open")), self.assertRaises(profile.ContextValidationError):
            profile._load_context(str(Path(__file__).absolute()), self.dates)
        if os.name == "nt":
            import ctypes
            with mock.patch.object(ctypes.windll.kernel32, "GetDriveTypeW", return_value=4), mock.patch.object(Path, "lstat", side_effect=AssertionError("no network metadata read")), self.assertRaises(profile.ContextValidationError):
                profile._load_context("Z:/synthetic-context.json", self.dates)
            with mock.patch.object(Path, "lstat", return_value=mock.Mock(st_mode=profile.stat.S_IFREG, st_file_attributes=profile.stat.FILE_ATTRIBUTE_REPARSE_POINT)), mock.patch.object(Path, "open", side_effect=AssertionError("must not open")), self.assertRaises(profile.ContextValidationError):
                profile._load_context(str(Path(__file__).absolute()), self.dates)

    def test_bounded_parser_and_local_path_guards_before_open(self):
        for path in ("https://invalid/private.json", "//server/private.json", "\\\\server\\private.json", "C:/private.json:stream", "\\\\?\\C:\\private.json"):
            with self.subTest(path=path), mock.patch.object(Path, "open", side_effect=AssertionError("must not open")), self.assertRaises(profile.ContextValidationError):
                profile._load_context(path, self.dates)
        with tempfile.TemporaryDirectory(prefix="synthetic-context-") as directory:
            path = Path(directory) / "SYNTHETIC-PRIVATE.json"
            invalid_bytes = [
                b'{"schema_version":1,"schema_version":1,"records":[]}',
                b'{"schema_version":1,"records":[{"date":"2026-07-01","date":"2026-07-01"}]}',
                b'{"schema_version":1,"records":[{"date":"2026-07-01","sleep_opportunity_minutes":NaN}]}',
                b'[' * 2000, b'\xff', b'{}' + b' ' * profile.MAX_CONTEXT_BYTES,
            ]
            for raw in invalid_bytes:
                path.write_bytes(raw)
                with self.subTest(size=len(raw)), self.assertRaises(profile.ContextValidationError):
                    profile._load_context(str(path), self.dates)
            with self.assertRaises(profile.ContextValidationError):
                profile._load_context(directory, self.dates)
            valid = b'{"schema_version":1,"records":[]}'
            path.write_bytes(valid + b' ' * (profile.MAX_CONTEXT_BYTES - len(valid)))
            before = path.read_bytes()
            self.assertEqual(profile._load_context(str(path), self.dates), [])
            self.assertEqual(path.read_bytes(), before)


class SleepQualificationTests(unittest.TestCase):
    def sleep_fixture(self, window_days, observed_nights, *, aware=False):
        first = date(2026, 7, 1)
        dates = [(first + timedelta(days=index)).isoformat() for index in range(window_days)]
        rows = []
        for index, day in enumerate(dates[:observed_nights]):
            offset = "+08:00" if aware else ""
            rows.append({
                "date": day,
                "total_sleep": 25200 + index * 60,
                "awake": 1800,
                "sleep_start": f"{day}T00:00:00{offset}",
                "sleep_end": f"{day}T08:00:00{offset}",
            })
        return rows, dates

    def test_three_six_and_seven_nights_are_descriptions_not_qualified_regularity(self):
        for count in (3, 6, 7):
            with self.subTest(count=count):
                rows, dates = self.sleep_fixture(7, count)
                result = profile._sleep_module(rows, dates, "Asia/Shanghai")
                duration = result["duration_regularity"]
                self.assertEqual(duration["status"], "eligible")
                self.assertEqual(duration["status_scope"], "descriptive_availability_only")
                self.assertEqual(duration["observed_nights"], count)
                self.assertIsNotNone(duration["duration_sd_hours"])
                self.assertEqual(result["timing_regularity"]["status_scope"], "descriptive_availability_only")
                formal = result["qualified_regularity"]
                self.assertFalse(formal["qualified"])
                self.assertEqual(formal["status"], "insufficient_window")
                self.assertEqual(formal["duration_observed_nights"], count)
                self.assertEqual(formal["timing_observed_nights"], 0)
                self.assertIsNone(formal["duration_sd_hours"])
                self.assertIsNone(formal["baseline_comparable"])

    def test_fourteen_day_sample_gate_does_not_override_unknown_comparability(self):
        for count in (6, 7, 14):
            with self.subTest(count=count):
                rows, dates = self.sleep_fixture(14, count, aware=True)
                formal = profile._sleep_module(rows, dates, "Asia/Shanghai")["qualified_regularity"]
                self.assertEqual(formal["status"], "epoch_unknown")
                self.assertEqual(formal["duration_observed_nights"], count)
                self.assertEqual(formal["timing_observed_nights"], count)
                self.assertEqual(formal["sample_status"]["duration"], "sufficient_observed_nights" if count >= 7 else "insufficient_valid_nights")
                self.assertEqual(formal["min_valid_nights"], 7)
                self.assertEqual(formal["window_days"], 14)
                self.assertFalse(formal["qualified"])
                self.assertIsNone(formal["duration_sd_hours"])

    def test_formal_samples_use_terminal_fourteen_days_not_entire_request(self):
        rows, dates = self.sleep_fixture(21, 21, aware=True)
        result = profile._sleep_module(rows, dates, "Asia/Shanghai")
        self.assertEqual(result["duration_regularity"]["observed_nights"], 21)
        self.assertEqual(result["qualified_regularity"]["duration_observed_nights"], 14)
        self.assertEqual(result["qualified_regularity"]["timing_observed_nights"], 14)

    def test_duplicate_nights_do_not_inflate_descriptive_or_formal_counts(self):
        rows, dates = self.sleep_fixture(14, 3, aware=True)
        result = profile._sleep_module(rows + rows, dates, "Asia/Shanghai")
        self.assertEqual(result["duration_regularity"]["observed_nights"], 3)
        self.assertEqual(result["timing_regularity"]["sleep_onset"]["observed_nights"], 3)
        self.assertEqual(result["qualified_regularity"]["duration_observed_nights"], 3)
        conflict = {**rows[0], "total_sleep": 9999, "sleep_start": f"{dates[0]}T01:00:00+08:00"}
        result = profile._sleep_module(rows + [conflict], dates, "Asia/Shanghai")
        self.assertEqual(result["duration_regularity"]["status"], "duplicate_conflict")
        self.assertEqual(result["timing_regularity"]["status"], "duplicate_conflict")
        self.assertIsNone(result["duration_regularity"]["duration_sd_hours"])
        self.assertEqual(result["qualified_regularity"]["duration_observed_nights"], 2)

    def test_six_of_seven_days_remains_partial_not_sync_failure_and_null_stays_null(self):
        rows, dates = self.sleep_fixture(7, 6)
        result = profile._sleep_module(rows, dates, None)
        self.assertEqual(result["duration"]["coverage"]["status"], "partial")
        self.assertEqual(result["duration"]["coverage"]["observed_days"], 6)
        self.assertEqual(result["duration"]["coverage"]["trailing_missing_days"], 1)
        self.assertEqual(result["timing_regularity"]["status"], "timezone_required")
        empty = profile._sleep_module([], dates, None)
        self.assertEqual(empty["duration"]["coverage"]["status"], "no_observations")
        self.assertIsNone(empty["duration"]["latest"])
        self.assertIsNone(empty["duration_regularity"]["duration_sd_hours"])


class ProblemInsightTests(unittest.TestCase):
    def fixture(self, days=7, observed=None, goal: int | None = 150, minutes=20):
        count = days if observed is None else observed
        dates = [(date(2026, 7, 1) + timedelta(days=index)).isoformat() for index in range(days)]
        daily = [{"date": day, "resting_heart_rate": 55, "moderate_activity_time": minutes * 60, "vigorous_activity_time": 0, "intensity_time_goal": goal * 60 if goal is not None else None} for day in dates[:count]]
        sleep = [{"date": day, "total_sleep": 27000, "awake": 1800, "sleep_start": f"{day}T00:00:00+08:00", "sleep_end": f"{day}T08:00:00+08:00"} for day in dates[:count]]
        hrv = [{"date": day, "last_night_average": 43, "weekly_average": 42, "baseline_low": 35, "baseline_upper": 50, "status": "BALANCED"} for day in dates[:count]]
        modules = {
            "sleep_health": profile._sleep_module(sleep, dates, "Asia/Shanghai"),
            "autonomic_recovery": {"resting_heart_rate": profile._series_summary(daily, "resting_heart_rate", dates, "bpm"), "hrv": profile._hrv_module(hrv, dates)},
            "movement": profile._movement_module(daily, dates, False),
            "recorded_activities": profile._recorded_activity_module([], dates, None, "available"),
        }
        return modules, {"start": dates[0], "end": dates[-1], "days": days}

    def build(self, modules, window, status="complete"):
        with mock.patch.object(profile.adapter, "get_connection", side_effect=AssertionError("insights must not read databases")):
            return profile._problem_insights(modules, window, status)

    def observed(self, item, metric):
        return next(obs for obs in item["observations"] if obs["metric"] == metric)

    def test_complete_sources_keep_recovery_unknown_but_show_dated_vendor_facts(self):
        modules, window = self.fixture()
        result = self.build(modules, window)
        sleep, recovery, activity = result["items"]
        self.assertEqual(recovery["qualification"]["comparison_status"], "epoch_unknown")
        self.assertIsNone(recovery["qualification"]["baseline_comparable"])
        vendor = self.observed(recovery, "vendor_weekly_hrv")
        self.assertEqual(vendor["value"], 42)
        self.assertEqual(vendor["observed_date"], "2026-07-07")
        self.assertEqual(self.observed(sleep, "sleep_duration")["coverage"]["observed_days"], 7)
        self.assertEqual(activity["qualification"]["goal_comparison_status"], "eligible_device_goal_observation")
        self.assertEqual([action["id"] for action in result["optional_actions"]], ["observe_sleep_opportunity", "review_device_goal_context"])
        self.assertIn("hrv_rhr_observation_attribution", recovery["missing_evidence"])

    def test_timing_descriptions_keep_counts_basis_and_formal_gate_separate(self):
        modules, window = self.fixture()
        sleep = self.build(modules, window)["items"][0]
        onset = self.observed(sleep, "sleep_onset_dispersion")
        self.assertEqual(onset["sample_count"], 7)
        self.assertEqual(onset["value"], 0)
        self.assertEqual(sleep["qualification"]["timing_basis"], "source_offsets_converted")
        self.assertEqual(sleep["qualification"]["formal_regularity_status"], "insufficient_window")
        modules["sleep_health"]["timing_regularity"]["status"] = "timezone_required"
        sleep = self.build(modules, window)["items"][0]
        self.assertIsNone(self.observed(sleep, "sleep_onset_dispersion")["value"])
        self.assertEqual(sleep["qualification"]["timing_description_status"], "timezone_required")

    def test_evidence_pointers_resolve_for_complete_and_empty_sources(self):
        for observed in (7, 0):
            modules, window = self.fixture(observed=observed)
            result = self.build(modules, window)
            for item in result["items"]:
                for obs in item["observations"]:
                    target = {"modules": modules}
                    for key in obs["evidence_pointer"].lstrip("/").split("/"):
                        target = target[key]

    def test_partial_sources_prioritize_coverage_and_keep_short_descriptions(self):
        modules, window = self.fixture(observed=6)
        result = self.build(modules, window, "partial")
        duration = self.observed(result["items"][0], "sleep_duration")
        self.assertEqual(duration["value"], 7.5)
        self.assertEqual(duration["observed_date"], "2026-07-06")
        self.assertEqual(duration["coverage"]["observed_days"], 6)
        self.assertEqual(result["optional_actions"][0]["id"], "verify_observation_coverage")
        self.assertEqual(result["items"][2]["qualification"]["goal_comparison_status"], "insufficient_week_coverage")
        self.assertIsNone(self.observed(result["items"][2], "device_goal_progress")["value"])

    def test_no_data_does_not_turn_legacy_zero_sums_into_observations(self):
        modules, window = self.fixture(observed=0)
        self.assertEqual(modules["movement"]["latest_7_days"]["moderate_minutes"], 0)
        result = self.build(modules, window, "no_data")
        self.assertEqual(result["data_status"], "no_data")
        self.assertTrue(all(item["qualification"]["status"] == "no_observations" for item in result["items"]))
        self.assertIsNone(self.observed(result["items"][2], "moderate_activity")["value"])
        self.assertIsNone(self.observed(result["items"][2], "vigorous_activity")["value"])
        self.assertEqual([item["id"] for item in result["optional_actions"]], ["verify_observation_coverage"])
        self.assertFalse(result["items"][0]["possible_explanations"])

    def test_recorded_zero_is_not_missing_and_goal_does_not_imply_coverage(self):
        modules, window = self.fixture(minutes=0)
        result = self.build(modules, window)
        activity = result["items"][2]
        self.assertEqual(self.observed(activity, "moderate_activity")["value"], 0)
        self.assertEqual(self.observed(activity, "device_goal_progress")["value"], 0)
        modules["movement"]["latest_7_days"]["vigorous_coverage"].update(status="no_observations", observed_days=0)
        activity = self.build(modules, window)["items"][2]
        self.assertIsNone(self.observed(activity, "vigorous_activity")["value"])
        self.assertIsNone(self.observed(activity, "device_goal_progress")["value"])
        self.assertEqual(activity["qualification"]["goal_comparison_status"], "insufficient_week_coverage")

    def test_absent_goal_does_not_invent_one_or_advise_goal_targeting(self):
        modules, window = self.fixture(goal=None)
        result = self.build(modules, window)
        activity = result["items"][2]
        self.assertIsNone(self.observed(activity, "device_goal")["value"])
        self.assertEqual(activity["qualification"]["goal_comparison_status"], "goal_unavailable")
        self.assertEqual(activity["qualification"]["status"], "descriptive_available")
        self.assertNotIn("review_device_goal_context", [action["id"] for action in result["optional_actions"]])
        self.assertNotIn("verify_observation_coverage", [action["id"] for action in result["optional_actions"]])

    def test_event_stream_blank_days_do_not_require_coverage_verification(self):
        for status, count in (("no_records", 0), ("no_window_records_prior_available", 0), ("available", 1)):
            with self.subTest(status=status):
                modules, window = self.fixture()
                modules["recorded_activities"]["status"] = status
                modules["recorded_activities"]["window_summary"]["active_days_with_records"] = count
                result = self.build(modules, window)
                activity = result["items"][2]
                self.assertEqual(self.observed(activity, "days_with_recorded_activities")["value"], count)
                self.assertEqual(activity["qualification"]["status"], "descriptive_available")
                self.assertNotIn("verify_observation_coverage", [action["id"] for action in result["optional_actions"]])

    def test_recorded_activity_evidence_survives_missing_minutes_and_goal(self):
        modules, window = self.fixture(observed=0, goal=None)
        modules["recorded_activities"]["status"] = "available"
        modules["recorded_activities"]["window_summary"]["active_days_with_records"] = 1
        activity = self.build(modules, window)["items"][2]
        self.assertEqual(activity["qualification"]["status"], "partial_observation")
        self.assertEqual(self.observed(activity, "days_with_recorded_activities")["value"], 1)
        self.assertIsNone(self.observed(activity, "moderate_activity")["value"])
        self.assertIsNone(self.observed(activity, "device_goal")["value"])

    def test_week_coverage_and_goal_date_use_actual_fields_without_expansion(self):
        dates = [(date(2026, 7, 1) + timedelta(days=i)).isoformat() for i in range(14)]
        rows = [{"date": day, "moderate_activity_time": 600, "vigorous_activity_time": None, "intensity_time_goal": 9000 if day == "2026-07-12" else None} for day in dates[-7:]]
        movement = profile._movement_module(rows, dates, False)
        week = movement["latest_7_days"]
        self.assertEqual(week["moderate_coverage"]["observed_days"], 7)
        self.assertEqual(week["vigorous_coverage"]["observed_days"], 0)
        self.assertEqual(week["vendor_goal_date"], "2026-07-12")
        modules, window = self.fixture(days=3)
        result = self.build(modules, window)
        self.assertEqual(modules["movement"]["latest_7_days"]["moderate_coverage"]["requested_days"], 3)
        self.assertEqual(result["items"][2]["qualification"]["goal_comparison_status"], "insufficient_week_coverage")
        self.assertEqual(result["items"][2]["observations"][0]["window"], {"start": "2026-07-01", "end": "2026-07-03"})

    def test_unknown_and_cross_epoch_remain_explicit_without_suppressing_descriptions(self):
        for status, comparable in (("epoch_unknown", None), ("cross_epoch", False)):
            modules, window = self.fixture(days=14)
            modules["sleep_health"]["qualified_regularity"].update(status=status, epoch_comparable=comparable)
            result = self.build(modules, window)
            sleep = result["items"][0]
            self.assertEqual(sleep["qualification"]["formal_regularity_status"], status)
            self.assertEqual(sleep["qualification"]["baseline_comparable"], comparable)
            self.assertEqual(self.observed(sleep, "sleep_duration")["value"], 7.5)
            self.assertIn("observe_sleep_opportunity", [action["id"] for action in result["optional_actions"]])

    def test_actions_are_bounded_unique_and_change_with_available_evidence(self):
        for days, observed, goal in ((7, 7, 150), (7, 6, 150), (7, 0, None), (3, 3, None)):
            modules, window = self.fixture(days=days, observed=observed, goal=goal)
            result = self.build(modules, window)
            ids = [action["id"] for action in result["optional_actions"]]
            self.assertLessEqual(len(ids), 2)
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(action["optional"] is True for action in result["optional_actions"]))
            self.assertTrue(all(set(item["optional_action_ids"]) <= set(ids) for item in result["items"]))
            for item in result["items"]:
                self.assertTrue(item["question"] and item["interpretation"] and item["next_observation_criteria"])
                self.assertTrue(all(explanation["status"] == "unverified_possibility" for explanation in item["possible_explanations"]))

    def test_conflicted_sleep_prioritizes_verification_and_inconsistent_eligible_never_unlocks(self):
        modules, window = self.fixture()
        modules["sleep_health"]["duration_regularity"]["status"] = "duplicate_conflict"
        result = self.build(modules, window)
        self.assertEqual(result["optional_actions"][0]["id"], "verify_observation_coverage")
        self.assertNotIn("observe_sleep_opportunity", [action["id"] for action in result["optional_actions"]])
        modules["sleep_health"]["qualified_regularity"].update(status="eligible", epoch_comparable=None)
        result = self.build(modules, window)
        self.assertEqual(result["items"][0]["qualification"]["formal_regularity_status"], "epoch_unknown")

    def test_private_arbitrary_source_strings_are_not_projected_into_insights(self):
        modules, window = self.fixture()
        secret = "C:/private/SYNTHETIC-RAW-SERIAL-DO-NOT-COPY"
        modules["serial_number"] = secret
        modules["autonomic_recovery"]["hrv"]["latest_vendor_context"]["vendor_status"] = secret
        modules["sleep_health"]["qualified_regularity"]["limitations"] = [secret]
        modules["recorded_activities"]["window_summary"]["activity_type_counts"] = {secret: 1}
        serialized = json.dumps(self.build(modules, window), ensure_ascii=False, allow_nan=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("serial_number", serialized)
        self.assertNotIn("activity_type_counts", serialized)
        for forbidden in ("health_score", "readiness_score", "risk_color", "training_clearance"):
            self.assertNotIn(forbidden, serialized)

    def test_invalid_vendor_interval_and_different_dates_are_not_merged(self):
        modules, window = self.fixture()
        modules["autonomic_recovery"]["hrv"]["last_night"]["latest_date"] = "2026-07-06"
        modules["autonomic_recovery"]["hrv"]["latest_vendor_context"]["baseline_low_ms"] = 100
        recovery = self.build(modules, window)["items"][1]
        self.assertEqual(self.observed(recovery, "last_night_hrv")["observed_date"], "2026-07-06")
        self.assertEqual(self.observed(recovery, "resting_heart_rate")["observed_date"], "2026-07-07")
        self.assertIsNone(self.observed(recovery, "vendor_weekly_hrv")["value"])
        self.assertIn("same_date_vendor_interval", recovery["missing_evidence"])
        self.assertIsNone(recovery["qualification"]["baseline_comparable"])


if __name__ == "__main__":
    unittest.main()
