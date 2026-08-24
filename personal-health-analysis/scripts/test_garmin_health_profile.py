import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
