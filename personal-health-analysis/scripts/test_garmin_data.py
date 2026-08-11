import importlib.util
import io
import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from garmin_capabilities import require_capability


SCRIPT_PATH = Path(__file__).with_name("garmin_data.py")
SPEC = importlib.util.spec_from_file_location("garmin_data", SCRIPT_PATH)
garmin_auth_stub = types.SimpleNamespace(get_client=lambda: None)
garminconnect_stub = types.SimpleNamespace(Garmin=object)
_STUBS = {"garmin_auth": garmin_auth_stub, "garminconnect": garminconnect_stub}
_PREVIOUS_MODULES = {name: sys.modules.get(name) for name in _STUBS}
sys.modules.update(_STUBS)
try:
    garmin_data = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(garmin_data)
finally:
    for name, previous in _PREVIOUS_MODULES.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def _component_mocks():
    return {
        "fetch_sleep": Mock(return_value={"sleep": [{"sleep_time_seconds": 28800, "sleep_score": 80}]}),
        "fetch_hrv": Mock(return_value={"hrv": [{"last_night_avg": 40}]}),
        "fetch_body_battery": Mock(return_value={"body_battery": [{"charged": 50}]}),
        "fetch_heart_rate": Mock(return_value={"heart_rate": [{"resting_hr": 55}]}),
        "fetch_activities": Mock(return_value={"activities": [{"calories": 100}]}),
        "fetch_stress": Mock(return_value={"stress": []}),
        "fetch_training_load_series": Mock(return_value={"training_load": []}),
        "fetch_training_status": Mock(return_value={"status": "ok"}),
        "fetch_max_metrics": Mock(return_value={"fitness_age": 40}),
        "fetch_hydration": Mock(return_value={"valueInML": 1000}),
        "fetch_body_composition": Mock(return_value={"weight": 70}),
        "fetch_alarms": Mock(return_value=[]),
    }


class GarminSummaryTests(unittest.TestCase):
    def test_local_summary_uses_one_verified_window_and_ignores_null_only_rows(self):
        today = datetime.now().strftime("%Y-%m-%d")
        summary_frame = pd.DataFrame(
            [
                {
                    "date": today,
                    "resting_heart_rate": None,
                    "stress_avg": None,
                    "body_battery_highest": None,
                    "body_battery_lowest": None,
                    "body_battery_charged": None,
                }
            ]
        )
        sleep_frame = pd.DataFrame(
            [{"date": today, "sleep_time_seconds": None, "sleep_score": None}]
        )
        hrv_frame = pd.DataFrame(
            [{"date": today, "hrv_avg": None, "status": None}]
        )
        activities_frame = pd.DataFrame(columns=["date", "activity_id"])
        state = {"entered": 0, "exited": 0, "paths": None}

        class VerifiedWindow:
            def __enter__(self):
                state["entered"] += 1
                return self

            def __exit__(self, exc_type, exc, traceback):
                state["exited"] += 1
                return False

            def public_summary(self):
                self_outer.assertEqual(state["exited"], 1)
                return {"status": "verified_unchanged", "databases": []}

        self_outer = self

        def make_window(paths):
            state["paths"] = list(paths)
            return VerifiedWindow()

        adapter_stub = types.SimpleNamespace(
            GARMIN_DB=Path("garmin.db"),
            ACTIVITIES_DB=Path("garmin_activities.db"),
            get_summary=Mock(return_value=summary_frame),
            get_sleep_data=Mock(return_value=sleep_frame),
            get_hrv_data=Mock(return_value=hrv_frame),
            get_activities_data=Mock(return_value=activities_frame),
            verified_database_read_window=make_window,
        )
        with patch.dict(sys.modules, {"garmin_sqlite_adapter": adapter_stub}):
            result = garmin_data._fetch_local_metric("summary", days=1)

        self.assertEqual(state["entered"], 1)
        self.assertEqual(state["exited"], 1)
        self.assertEqual(
            {Path(path).name for path in state["paths"]},
            {"garmin.db", "garmin_activities.db"},
        )
        self.assertEqual(result["data_integrity"]["status"], "verified_unchanged")
        self.assertEqual(result["status"], "no_data")
        for component in (
            "sleep",
            "hrv",
            "heart_rate",
            "body_battery",
            "stress",
            "activities",
        ):
            self.assertEqual(result["component_status"][component]["status"], "no_data")
            self.assertEqual(result["component_status"][component]["observed_days"], 0)

    def test_single_local_metric_reports_null_only_rows_as_no_data(self):
        today = datetime.now().strftime("%Y-%m-%d")
        result = garmin_data._local_metric_result(
            "sleep",
            [{"date": today, "sleep_time_seconds": None, "sleep_score": None}],
            1,
        )

        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["coverage"]["observed_days"], 0)

    def test_local_cli_fails_closed_when_database_changes_during_read(self):
        class LocalDatabaseChangedError(RuntimeError):
            pass

        class ChangedWindow:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                raise LocalDatabaseChangedError("sensitive_database_path")

            def public_summary(self):
                raise AssertionError("an unverified window must not be summarized")

        adapter_stub = types.SimpleNamespace(
            GARMIN_DB=Path("garmin.db"),
            ACTIVITIES_DB=Path("garmin_activities.db"),
            get_summary=Mock(return_value=pd.DataFrame()),
            get_sleep_data=Mock(return_value=pd.DataFrame()),
            get_hrv_data=Mock(return_value=pd.DataFrame()),
            get_activities_data=Mock(return_value=pd.DataFrame()),
            verified_database_read_window=lambda _paths: ChangedWindow(),
        )
        output = io.StringIO()
        with (
            patch.dict(sys.modules, {"garmin_sqlite_adapter": adapter_stub}),
            patch.object(
                sys,
                "argv",
                ["garmin_data.py", "summary", "--days", "1", "--allow-health-data"],
            ),
            patch("sys.stdout", output),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload,
            {
                "status": "read_error",
                "error_code": "database_changed_during_read",
            },
        )
        self.assertNotIn("sensitive_database_path", output.getvalue())

    def test_local_cli_preserves_safe_schema_failure_code(self):
        class LocalDatabaseReadError(RuntimeError):
            pass

        output = io.StringIO()
        with (
            patch.object(
                garmin_data,
                "_fetch_local_metric",
                side_effect=LocalDatabaseReadError("sleep_query_failed"),
            ),
            patch.object(
                sys,
                "argv",
                ["garmin_data.py", "sleep", "--days", "1", "--allow-health-data"],
            ),
            patch("sys.stdout", output),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 1)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "read_error", "error_code": "sleep_query_failed"},
        )

    def test_local_module_has_no_eager_garminconnect_dependency(self):
        import ast

        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        eager_live_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "garminconnect"
        ]
        self.assertEqual(eager_live_imports, [])

    def test_days_window_is_exact_and_explicit_range_is_validated(self):
        start, end = garmin_data.get_date_range(days=7)
        observed_days = (
            datetime.strptime(end, "%Y-%m-%d")
            - datetime.strptime(start, "%Y-%m-%d")
        ).days + 1
        self.assertEqual(observed_days, 7)
        self.assertEqual(
            garmin_data.get_date_range(start="2026-07-01", end="2026-07-07"),
            ("2026-07-01", "2026-07-07"),
        )
        for kwargs in (
            {"days": 0},
            {"start": "2026-07-01"},
            {"end": "2026-07-07"},
            {"start": "2026-07-08", "end": "2026-07-07"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                garmin_data.get_date_range(**kwargs)

    def test_summary_serializes_components_and_daily_requests(self):
        mocks = _component_mocks()
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=7)

        self.assertNotIn("error", result)
        self.assertEqual(result["summary"]["total_activities"], 1)
        self.assertEqual(result["summary"]["total_calories"], 100)
        for name in (
            "fetch_sleep",
            "fetch_hrv",
            "fetch_body_battery",
            "fetch_heart_rate",
            "fetch_stress",
            "fetch_training_load_series",
        ):
            self.assertEqual(mocks[name].call_args.kwargs["max_workers"], 1)
        for name in (
            "fetch_training_status",
            "fetch_max_metrics",
            "fetch_hydration",
            "fetch_body_composition",
            "fetch_alarms",
        ):
            mocks[name].assert_not_called()
        self.assertEqual(
            result["authorized_scope"]["components"],
            list(garmin_data.LIVE_SUMMARY_COMPONENTS),
        )
        self.assertEqual(
            result["authorized_scope"]["omitted_components"],
            list(garmin_data.LIVE_SUMMARY_OMITTED_COMPONENTS),
        )
        self.assertEqual(garmin_data.SUMMARY_MAX_WORKERS, 1)

    def test_summary_component_subset_does_not_call_unrequested_endpoints(self):
        mocks = _component_mocks()
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(
                object(),
                start="2026-08-08",
                end="2026-08-08",
                components=("activities",),
            )

        mocks["fetch_activities"].assert_called_once()
        for name, mock in mocks.items():
            if name != "fetch_activities":
                mock.assert_not_called()
        self.assertEqual(result["authorized_scope"]["components"], ["activities"])
        self.assertEqual(result["component_status"]["sleep"]["status"], "not_requested")

    def test_summary_rate_limit_stops_before_later_components(self):
        mocks = _component_mocks()
        mocks["fetch_sleep"].return_value = {
            "error": "rate_limited",
            "error_type": "LiveRequestError",
        }
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=1)

        self.assertEqual(result["error"], "rate_limited")
        mocks["fetch_sleep"].assert_called_once()
        for name, mock in mocks.items():
            if name != "fetch_sleep":
                mock.assert_not_called()

    def test_summary_spy_client_observes_only_declared_methods_and_dates(self):
        calls = []

        class ScopeBoundClient:
            def _daily(self, method, day):
                calls.append((method, day))
                return {}

            def get_sleep_data(self, day):
                return self._daily("get_sleep_data", day)

            def get_hrv_data(self, day):
                return self._daily("get_hrv_data", day)

            def get_body_battery(self, day):
                return self._daily("get_body_battery", day)

            def get_heart_rates(self, day):
                return self._daily("get_heart_rates", day)

            def get_stress_data(self, day):
                return self._daily("get_stress_data", day)

            def get_training_status(self, day):
                return self._daily("get_training_status", day)

            def get_activities_by_date(self, start, end, activity_type):
                calls.append(("get_activities_by_date", start, end, activity_type))
                return []

        result = garmin_data.fetch_summary(
            ScopeBoundClient(),
            start="2026-08-08",
            end="2026-08-09",
            components=garmin_data.LIVE_SUMMARY_COMPONENTS,
        )

        self.assertNotIn("error", result)
        for component in garmin_data.LIVE_SUMMARY_COMPONENTS:
            self.assertNotEqual(result["component_status"][component]["status"], "error")
        daily_methods = {
            "get_sleep_data",
            "get_hrv_data",
            "get_body_battery",
            "get_heart_rates",
            "get_stress_data",
            "get_training_status",
        }
        for method in daily_methods:
            self.assertEqual(
                [call[1] for call in calls if call[0] == method],
                ["2026-08-08", "2026-08-09"],
            )
        self.assertIn(
            ("get_activities_by_date", "2026-08-08", "2026-08-09", ""),
            calls,
        )

    def test_stress_uses_narrow_endpoint_and_does_not_emit_steps(self):
        client = Mock()
        client.get_stress_data.return_value = {
            "averageStressLevel": 25,
            "maxStressLevel": 60,
            "restStressDuration": 100,
            "lowStressDuration": 200,
            "mediumStressDuration": 300,
            "highStressDuration": 400,
            "totalSteps": 9999,
        }

        result = garmin_data.fetch_stress(
            client, start="2026-08-08", end="2026-08-08", max_workers=1
        )

        client.get_stress_data.assert_called_once_with("2026-08-08")
        self.assertNotIn("steps", result["stress"][0])

    def test_component_failure_keeps_partial_summary(self):
        mocks = _component_mocks()
        mocks["fetch_hrv"].side_effect = RuntimeError("private upstream detail")
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=7)

        self.assertNotIn("error", result)
        self.assertEqual(result["hrv"], [])
        self.assertEqual(result["sleep"][0]["sleep_score"], 80)
        self.assertEqual(result["component_status"]["hrv"]["status"], "error")

    def test_activity_component_failure_is_not_reported_as_zero(self):
        mocks = _component_mocks()
        mocks["fetch_activities"].side_effect = RuntimeError("synthetic failure")
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=1)

        self.assertIsNone(result["summary"]["total_activities"])
        self.assertIsNone(result["summary"]["total_calories"])
        self.assertEqual(result["component_status"]["activities"]["status"], "error")

    def test_missing_aggregates_are_null_and_coverage_is_explicit(self):
        mocks = _component_mocks()
        for name, result_key in (
            ("fetch_sleep", "sleep"),
            ("fetch_hrv", "hrv"),
            ("fetch_body_battery", "body_battery"),
            ("fetch_heart_rate", "heart_rate"),
            ("fetch_activities", "activities"),
            ("fetch_stress", "stress"),
            ("fetch_training_load_series", "training_load"),
        ):
            mocks[name].return_value = {result_key: []}
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(object(), days=7)

        for field in (
            "avg_sleep_hours",
            "avg_sleep_score",
            "avg_hrv_ms",
            "avg_resting_hr",
            "avg_body_battery_charged",
        ):
            self.assertIsNone(result["summary"][field], field)
        self.assertEqual(result["coverage"]["requested_days"], 7)
        self.assertEqual(result["component_status"]["sleep"]["observed_days"], 0)
        self.assertEqual(result["component_status"]["sleep"]["status"], "no_data")
        self.assertIsNone(result["summary"]["total_activities"])
        self.assertIsNone(result["summary"]["total_calories"])
        self.assertEqual(result["component_status"]["activities"]["status"], "no_data")

    def test_observed_zero_activity_calories_remain_zero(self):
        mocks = _component_mocks()
        mocks["fetch_activities"].return_value = {
            "activities": [{"date": "2026-07-27", "calories": 0}]
        }
        with patch.multiple(garmin_data, **mocks):
            result = garmin_data.fetch_summary(
                object(), start="2026-07-27", end="2026-07-27"
            )

        self.assertEqual(result["summary"]["total_activities"], 1)
        self.assertEqual(result["summary"]["total_calories"], 0)
        self.assertEqual(result["component_status"]["activities"]["status"], "complete")

    def test_cli_defaults_to_local_without_initializing_live_client(self):
        local_result = {"sleep": [], "source": "local"}
        with (
            patch.object(garmin_data, "_fetch_local_metric", return_value=local_result),
            patch.object(
                garmin_data,
                "get_client",
                side_effect=AssertionError("live client must not be initialized"),
            ) as get_client,
            patch.object(
                sys,
                "argv",
                ["garmin_data.py", "sleep", "--days", "1", "--allow-health-data"],
            ),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 0)
        get_client.assert_not_called()

    def test_local_source_requires_explicit_health_data_permission(self):
        output = io.StringIO()
        with (
            patch.object(
                garmin_data,
                "_fetch_local_metric",
                side_effect=AssertionError("permission gate must run before local read"),
            ) as fetch_local,
            patch.object(sys, "argv", ["garmin_data.py", "sleep", "--days", "1"]),
            patch("sys.stdout", output),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "health_data_authorization_required"},
        )
        fetch_local.assert_not_called()

    def test_live_source_requires_explicit_network_permission(self):
        with (
            patch.object(
                garmin_data,
                "get_client",
                side_effect=AssertionError("permission gate must run first"),
            ) as get_client,
            patch.object(
                sys,
                "argv",
                ["garmin_data.py", "sleep", "--source", "live"],
            ),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 2)
        get_client.assert_not_called()

    def test_authorized_live_source_uses_scoped_capability(self):
        client = object()
        with (
            patch.object(garmin_data, "get_client", return_value=client) as get_client,
            patch.object(garmin_data, "fetch_sleep", return_value={"sleep": []}),
            patch.object(
                sys,
                "argv",
                [
                    "garmin_data.py",
                    "sleep",
                    "--source",
                    "live",
                    "--allow-network",
                    "--allow-health-data",
                    "--days",
                    "1",
                ],
            ),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 0)
        get_client.assert_called_once()
        self.assertEqual(
            get_client.call_args.kwargs["operation"], "health_data_live"
        )
        require_capability(
            get_client.call_args.kwargs["network_capability"],
            scope="network",
            operation="health_data_live",
            request=get_client.call_args.kwargs["request"],
        )
        self.assertEqual(get_client.call_args.kwargs["request"]["metric"], "sleep")

    def test_live_summary_capability_binds_fixed_components_and_exact_dates(self):
        client = object()
        with (
            patch.object(garmin_data, "get_client", return_value=client) as get_client,
            patch.object(garmin_data, "fetch_summary", return_value={"summary": {}}) as fetch,
            patch.object(
                sys,
                "argv",
                [
                    "garmin_data.py",
                    "summary",
                    "--source",
                    "live",
                    "--allow-network",
                    "--allow-health-data",
                    "--start",
                    "2026-08-01",
                    "--end",
                    "2026-08-02",
                ],
            ),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            rc = garmin_data.main()

        self.assertEqual(rc, 0)
        request = get_client.call_args.kwargs["request"]
        self.assertEqual(request["start"], "2026-08-01")
        self.assertEqual(request["end"], "2026-08-02")
        self.assertEqual(request["components"], list(garmin_data.LIVE_SUMMARY_COMPONENTS))
        fetch.assert_called_once_with(
            client,
            None,
            "2026-08-01",
            "2026-08-02",
            components=request["components"],
        )

    def test_live_profile_reads_only_declared_full_name_field(self):
        client = Mock()
        client.get_full_name.return_value = "Synthetic User"
        result = garmin_data.fetch_profile(client)
        self.assertEqual(result["profile"], {"name": "Synthetic User"})
        self.assertEqual(result["authorized_scope"], {"fields": ["full_name"]})
        client.get_full_name.assert_called_once_with()
        self.assertFalse(hasattr(client, "get_user_summary") and client.get_user_summary.called)

    @patch.object(garmin_data.concurrent.futures, "ThreadPoolExecutor")
    def test_inline_daily_mapping_does_not_start_nested_pool(self, executor_mock):
        result = garmin_data._map_with_workers(lambda value: value * 2, [1, 2], 1)
        self.assertEqual(result, [2, 4])
        executor_mock.assert_not_called()

    def test_rate_limit_is_terminal_without_retry(self):
        calls = []

        def rate_limited():
            calls.append(True)
            raise RuntimeError("HTTP 429 synthetic")

        with self.assertRaisesRegex(garmin_data.LiveRequestError, "rate_limited"):
            garmin_data.fetch_with_retry(rate_limited, max_retries=5, base_delay=99)
        self.assertEqual(len(calls), 1)

    def test_body_composition_does_not_invent_height_for_bmi(self):
        client = types.SimpleNamespace(
            get_user_profile=lambda: {},
            get_body_composition=lambda *_args: {
                "dateWeightList": [{"weight": 70000, "bmi": None, "date": "2026-07-27"}]
            },
        )
        result = garmin_data.fetch_body_composition(client, "2026-07-27")
        self.assertEqual(result["bmi"], "--")
        self.assertIsNone(result["source_height"])
        self.assertTrue(result["data_gaps"])

    def test_live_sleep_preserves_respiration_and_spo2_as_separate_estimates(self):
        client = types.SimpleNamespace(
            get_sleep_data=lambda _date: {
                "dailySleepDTO": {
                    "sleepTimeSeconds": 28800,
                    "averageRespirationValue": 14.5,
                    "averageSpO2Value": 96,
                    "sleepScores": {"overall": {"value": 80}},
                }
            }
        )

        result = garmin_data.fetch_sleep(
            client,
            start="2026-07-27",
            end="2026-07-27",
            max_workers=1,
        )

        self.assertEqual(result["sleep"][0]["avg_respiration"], 14.5)
        self.assertEqual(result["sleep"][0]["avg_spo2"], 96)

    def test_hydration_missing_value_is_null_not_zero(self):
        client = types.SimpleNamespace(get_hydration_data=lambda _date: {"goalInML": 2000})

        result = garmin_data.fetch_hydration(client, "2026-07-27")

        self.assertIsNone(result["valueInML"])

    def test_body_composition_missing_weight_is_null_not_zero(self):
        client = types.SimpleNamespace(
            get_user_profile=lambda: {"height": 175},
            get_body_composition=lambda *_args: {
                "dateWeightList": [{"bmi": None, "date": "2026-07-27"}]
            },
        )

        result = garmin_data.fetch_body_composition(client, "2026-07-27")

        self.assertIsNone(result["weight"])
        self.assertEqual(result["bmi"], "--")
        self.assertTrue(any("Weight unavailable" in gap for gap in result["data_gaps"]))


if __name__ == "__main__":
    unittest.main()
