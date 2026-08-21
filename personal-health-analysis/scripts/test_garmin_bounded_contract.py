import importlib.util
import inspect
import io
import json
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pandas as pd


MODULE_PATH = Path(__file__).with_name("garmin_bounded.py")
SPEC = importlib.util.spec_from_file_location("garmin_intelligence_contract", MODULE_PATH)
garmin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(garmin)

ADAPTER_PATH = Path(__file__).with_name("garmin_sqlite_adapter.py")
ADAPTER_SPEC = importlib.util.spec_from_file_location(
    "garmin_sqlite_adapter_contract", ADAPTER_PATH
)
sqlite_adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
assert ADAPTER_SPEC.loader is not None
ADAPTER_SPEC.loader.exec_module(sqlite_adapter)


def run_main(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = garmin.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def bounded_summary(gaps=None):
    return {
        "sleep": [],
        "hrv": [],
        "body_battery": [],
        "heart_rate": [],
        "stress": [],
        "activities": [],
        "daily_summary": [],
        "training_status": {},
        "max_metrics": {},
        "body_composition": {},
        "biomechanics": [],
        "pmc": [],
        "is_stale": False,
        "_bounded_contract": True,
        "_data_gaps": list(gaps or []),
        "_accessed_days": 3,
    }


class GarminRuntimeContractTests(unittest.TestCase):
    def test_live_token_fallback_prefers_validated_garmindb_root(self):
        fake_stat = types.SimpleNamespace(st_size=1)
        with (
            mock.patch.dict(garmin.os.environ, {"GARMIN_TOKEN_DIR": ""}),
            mock.patch.object(garmin.Path, "home", return_value=Path("C:/Users/test")),
            mock.patch.object(garmin.Path, "is_file", return_value=True),
            mock.patch.object(garmin.Path, "stat", return_value=fake_stat),
        ):
            selected = garmin._live_token_path()

        self.assertEqual(selected, Path("C:/Users/test/.GarminDb/garmin_tokens.json"))

    def test_live_client_clears_persistent_token_binding_before_and_after_load(self):
        inner = mock.Mock()
        inner._tokenstore_path = "unexpected"
        outer = mock.Mock(client=inner)
        fake_garmin = mock.Mock(return_value=outer)
        fake_module = types.SimpleNamespace(Garmin=fake_garmin)
        token_path = mock.Mock()
        token_path.read_text.return_value = '{"fixture":"token"}'

        with (
            mock.patch.dict("sys.modules", {"garminconnect": fake_module}),
            mock.patch.object(garmin, "_live_token_path", return_value=token_path),
        ):
            result = garmin._load_live_client()

        self.assertIs(result, outer)
        fake_garmin.assert_called_once_with(retry_attempts=0)
        inner.loads.assert_called_once_with('{"fixture":"token"}')
        self.assertIsNone(inner._tokenstore_path)

    def test_sqlite_adapter_opens_database_in_read_only_mode(self):
        fake_connection = mock.MagicMock()
        fake_connection.cursor.return_value.fetchall.return_value = [("summary",)]
        with mock.patch.object(
            sqlite_adapter.sqlite3, "connect", return_value=fake_connection
        ) as connect:
            result = sqlite_adapter.get_connection(MODULE_PATH)

        self.assertIs(result, fake_connection)
        uri = connect.call_args.args[0]
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro"))
        self.assertTrue(connect.call_args.kwargs["uri"])

    def test_bounded_adapter_queries_have_explicit_upper_limits(self):
        summary_source = inspect.getsource(sqlite_adapter.get_summary)
        sleep_source = inspect.getsource(sqlite_adapter.get_sleep_data)
        hrv_source = inspect.getsource(sqlite_adapter.get_hrv_data)
        activities_source = inspect.getsource(sqlite_adapter.get_activities_data)

        self.assertIn("AND day <= '{end_date}'", summary_source)
        self.assertIn("AND day <= '{end_date}'", sleep_source)
        self.assertIn("AND day <= '{end_date}'", hrv_source)
        self.assertIn("AND start_time < '{end_exclusive}'", activities_source)

    def test_source_is_required_before_provider_load(self):
        with mock.patch.object(garmin, "_load_local_adapter") as loader:
            with self.assertRaises(SystemExit) as caught:
                run_main(["insight_cn", "--days", "3", "--allow-health-data"])
        self.assertEqual(caught.exception.code, 2)
        loader.assert_not_called()

    def test_health_consent_precedes_local_provider_load(self):
        with mock.patch.object(garmin, "_load_local_adapter") as loader:
            code, _, stderr = run_main(
                ["insight_cn", "--days", "3", "--source", "local"]
            )
        self.assertEqual(code, 2)
        self.assertIn("HEALTH_DATA_AUTH_REQUIRED", stderr)
        loader.assert_not_called()

    def test_live_requires_network_and_uses_bounded_provider(self):
        without_network = [
            "insight_cn",
            "--days",
            "3",
            "--source",
            "live",
            "--allow-health-data",
        ]
        code, _, stderr = run_main(without_network)
        self.assertEqual(code, 2)
        self.assertIn("NETWORK_AUTH_REQUIRED", stderr)

        fixture = bounded_summary(["resting_heart_rate_not_requested"])
        fixture["_source"] = "live"
        with (
            mock.patch.object(garmin, "fetch_live_summary", return_value=fixture) as fetch,
            mock.patch.object(
                garmin,
                "generate_chinese_insight",
                return_value={"analysis_type": "fixture"},
            ),
        ):
            code, stdout, stderr = run_main(without_network + ["--allow-network"])

        self.assertEqual(code, 0, stderr)
        fetch.assert_called_once_with(3)
        payload = json.loads(stdout)
        self.assertEqual(payload["provenance"]["source"], "live")
        self.assertTrue(payload["provenance"]["network_accessed"])
        self.assertFalse(payload["provenance"]["persisted"])

    def test_invalid_live_session_is_actionable_and_fail_fast(self):
        with mock.patch.object(
            garmin,
            "fetch_live_summary",
            side_effect=garmin.LiveAuthenticationError("fixture 401"),
        ):
            code, stdout, stderr = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "live",
                    "--allow-health-data",
                    "--allow-network",
                ]
            )

        self.assertEqual(code, 6, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "authentication_required")
        self.assertEqual(payload["error_code"], "LIVE_SESSION_INVALID")
        self.assertEqual(payload["data_gaps"], ["live_session_invalid"])
        self.assertTrue(payload["provenance"]["network_accessed"])
        self.assertFalse(payload["provenance"]["persisted"])

    def test_live_fetch_uses_no_profile_lane_and_preserves_missing_values(self):
        calls = []

        class FakeClient:
            def get_hrv_data_range(self, start, end):
                calls.append(("hrv", start, end))
                return {
                    "hrvSummaries": [
                        {
                            "calendarDate": end,
                            "lastNightAvg": 41,
                            "status": "BALANCED",
                        }
                    ]
                }

            def get_sleep_daily(self, start, end):
                calls.append(("sleep", start, end))
                return [
                    {
                        "calendarDate": end,
                        "values": {
                            "totalSleepTimeInSeconds": 25200,
                            "deepTime": 4500,
                            "remTime": 5100,
                            "sleepScore": 78,
                            "restingHeartRate": 57,
                        },
                    }
                ]

            def get_body_battery(self, start, end):
                calls.append(("body_battery", start, end))
                return [
                    {
                        "date": end,
                        "charged": 47,
                        "bodyBatteryValuesArray": [[1, 22], [2, 69]],
                    }
                ]

            def get_stress_data(self, day):
                calls.append(("stress", day))
                return {"calendarDate": day, "avgStressLevel": 31}

        with mock.patch.object(garmin, "_load_live_client", return_value=FakeClient()):
            result = garmin.fetch_live_summary(3)

        self.assertEqual(result["_source"], "live")
        self.assertEqual(result["_accessed_days"], 3)
        self.assertEqual(result["hrv"][0]["last_night_avg"], 41)
        self.assertEqual(result["sleep"][0]["sleep_time_seconds"], 25200)
        self.assertEqual(result["body_battery"][0]["highest"], 69)
        self.assertEqual(result["body_battery"][0]["lowest"], 22)
        self.assertEqual(len(result["stress"]), 3)
        self.assertEqual(result["heart_rate"][0]["resting_hr"], 57)
        self.assertNotIn("resting_heart_rate_observations", result["_data_gaps"])
        self.assertEqual(result["stress"][0]["avg_stress"], 31)
        self.assertNotIn("sleep_observations", result["_data_gaps"])
        self.assertFalse(any(call[0] in {"profile", "settings", "login"} for call in calls))

    def test_live_fetch_stops_after_first_authentication_failure(self):
        calls = []

        class FakeClient:
            def get_body_battery(self, start, end):
                calls.append("body_battery")
                raise RuntimeError("API Error 401")

        with mock.patch.object(garmin, "_load_live_client", return_value=FakeClient()):
            with self.assertRaises(garmin.LiveAuthenticationError):
                garmin.fetch_live_summary(3)

        self.assertEqual(calls, ["body_battery"])

    def test_unmigrated_analysis_modes_fail_closed_before_provider_read(self):
        with mock.patch.object(garmin, "_load_local_adapter") as loader:
            code, _, stderr = run_main(
                [
                    "readiness",
                    "--days",
                    "1",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(code, 5)
        self.assertIn("ANALYSIS_NOT_BOUNDED_SAFE", stderr)
        loader.assert_not_called()

    def test_exact_local_command_has_provenance_and_no_hidden_context(self):
        fixture = bounded_summary(["fixture_gap"])
        with (
            mock.patch.object(garmin, "fetch_local_summary", return_value=fixture) as fetch,
            mock.patch.object(
                garmin,
                "generate_chinese_insight",
                return_value={"analysis_type": "fixture"},
            ),
            mock.patch.object(
                garmin,
                "query_vector_lake",
                side_effect=AssertionError("unexpected Vector Lake read"),
            ) as vector_query,
        ):
            code, stdout, _ = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(code, 0)
        fetch.assert_called_once_with(3)
        vector_query.assert_not_called()
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["provenance"]["source"], "local")
        self.assertEqual(payload["provenance"]["requested_days"], 3)
        self.assertEqual(payload["provenance"]["accessed_days"], 3)
        self.assertFalse(payload["provenance"]["network_accessed"])
        self.assertFalse(payload["provenance"]["memory_context_accessed"])
        self.assertFalse(payload["provenance"]["persisted"])

    def test_local_no_data_is_terminal(self):
        with (
            mock.patch.object(
                garmin,
                "fetch_local_summary",
                side_effect=garmin.DataStaleError("empty"),
            ),
            mock.patch.object(
                garmin,
                "query_vector_lake",
                side_effect=AssertionError("unexpected fallback/context read"),
            ) as vector_query,
        ):
            code, stdout, _ = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "no_data")
        self.assertEqual(payload["data_status"], "no_data")
        self.assertEqual(payload["data_gaps"], ["local_window_no_observations"])
        self.assertEqual(payload["provenance"]["source"], "local")
        self.assertEqual(payload["provenance"]["requested_days"], 3)
        self.assertEqual(payload["provenance"]["accessed_days"], 3)
        self.assertFalse(payload["provenance"]["network_accessed"])
        self.assertFalse(payload["provenance"]["persisted"])
        vector_query.assert_not_called()

    def test_missing_local_database_reports_zero_accessed_days(self):
        with mock.patch.object(
            garmin,
            "fetch_local_summary",
            side_effect=FileNotFoundError("fixture database missing"),
        ):
            code, stdout, _ = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(code, 3)
        payload = json.loads(stdout)
        self.assertEqual(payload["data_gaps"], ["local_database_unavailable"])
        self.assertEqual(payload["accessed_days"], 0)
        self.assertEqual(payload["provenance"]["accessed_days"], 0)
        self.assertFalse(payload["provenance"]["network_accessed"])
        self.assertFalse(payload["provenance"]["persisted"])

    def test_local_failure_never_falls_back(self):
        with mock.patch.object(
            garmin, "fetch_local_summary", side_effect=RuntimeError("fixture failure")
        ):
            code, _, stderr = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )
        self.assertEqual(code, 4)
        self.assertIn("read_error", stderr)

    def test_local_adapter_window_is_exactly_three_calendar_days(self):
        calls = []

        class FakeAdapter:
            @staticmethod
            def get_summary(days, fill_missing=True):
                calls.append(("summary", days, fill_missing))
                return pd.DataFrame(
                    [
                        {
                            "date": f"2026-08-{day:02d}",
                            "resting_heart_rate": 60 + day,
                            "stress_avg": 25,
                            "body_battery_highest": 80,
                            "body_battery_lowest": 20,
                            "body_battery_charged": 60,
                        }
                        for day in (17, 18, 19)
                    ]
                )

            @staticmethod
            def get_sleep_data(days, fill_missing=True):
                calls.append(("sleep", days, fill_missing))
                return pd.DataFrame(
                    [
                        {
                            "date": "2026-08-19",
                            "sleep_time_seconds": 27000,
                            "sleep_score": 80,
                        }
                    ]
                )

            @staticmethod
            def get_hrv_data(days, fill_missing=True):
                calls.append(("hrv", days, fill_missing))
                return pd.DataFrame(
                    [
                        {
                            "date": "2026-08-19",
                            "hrv_avg": 42,
                            "status": "BALANCED",
                        }
                    ]
                )

            @staticmethod
            def get_activities_data(days):
                calls.append(("activities", days))
                return pd.DataFrame()

        with mock.patch.object(garmin, "_load_local_adapter", return_value=FakeAdapter):
            result = garmin.fetch_local_summary(3)

        self.assertEqual(
            calls,
            [
                ("summary", 2, False),
                ("sleep", 2, False),
                ("hrv", 2, False),
                ("activities", 2),
            ],
        )
        self.assertEqual(result["_accessed_days"], 3)
        self.assertEqual(len(result["heart_rate"]), 3)

    def test_bounded_fetch_preserves_missing_values_and_records_gaps(self):
        class MissingAdapter:
            @staticmethod
            def get_summary(days, fill_missing=True):
                self.assertFalse(fill_missing)
                return pd.DataFrame(
                    [
                        {
                            "date": "2026-08-19",
                            "resting_heart_rate": float("nan"),
                            "stress_avg": float("nan"),
                            "body_battery_highest": float("nan"),
                            "body_battery_lowest": float("nan"),
                            "body_battery_charged": float("nan"),
                        }
                    ]
                )

            @staticmethod
            def get_sleep_data(days, fill_missing=True):
                self.assertFalse(fill_missing)
                return pd.DataFrame()

            @staticmethod
            def get_hrv_data(days, fill_missing=True):
                self.assertFalse(fill_missing)
                return pd.DataFrame()

            @staticmethod
            def get_activities_data(days):
                return pd.DataFrame()

        with mock.patch.object(garmin, "_load_local_adapter", return_value=MissingAdapter):
            result = garmin.fetch_local_summary(3)

        self.assertIsNone(result["summary"]["avg_resting_hr"])
        self.assertIsNone(result["summary"]["avg_hrv_ms"])
        self.assertTrue(pd.isna(result["heart_rate"][0]["resting_hr"]))
        self.assertIn("resting_heart_rate_observations", result["_data_gaps"])
        self.assertIn("stress_observations", result["_data_gaps"])
        self.assertIn("body_battery_observations", result["_data_gaps"])

    def test_three_day_fixture_runs_full_insight_without_extra_reads(self):
        dates = ["2026-08-17", "2026-08-18", "2026-08-19"]
        fixture = {
            "summary": {
                "period": "2026-08-17 to 2026-08-19",
                "days": 3,
                "avg_body_battery_charged": 55,
            },
            "sleep": [
                {
                    "date": date,
                    "sleep_time_seconds": 27000,
                    "deep_sleep_seconds": 5400,
                    "rem_sleep_seconds": 5400,
                    "sleep_score": 80,
                    "avg_spo2": 96,
                }
                for date in dates
            ],
            "hrv": [
                {"date": date, "last_night_avg": 42, "status": "BALANCED"}
                for date in dates
            ],
            "body_battery": [
                {"date": date, "highest": 80, "lowest": 25, "charged": 55}
                for date in dates
            ],
            "heart_rate": [
                {"date": date, "resting_hr": value}
                for date, value in zip(dates, (61, 60, 60))
            ],
            "stress": [
                {
                    "date": date,
                    "avg_stress": 28,
                    "high_stress_duration": 1800,
                    "medium_stress_duration": 3600,
                    "rest_stress_duration": 7200,
                }
                for date in dates
            ],
            "activities": [],
            "daily_summary": [],
            "training_status": {},
            "max_metrics": {},
            "body_composition": {},
            "biomechanics": [],
            "pmc": [],
            "hydration": {},
            "is_stale": False,
            "_bounded_contract": True,
            "_data_gaps": ["long_horizon_baseline_not_authorized"],
            "_accessed_days": 3,
        }
        with (
            mock.patch.object(garmin, "fetch_local_summary", return_value=fixture),
            mock.patch.object(
                garmin,
                "query_vector_lake",
                side_effect=AssertionError("unexpected Vector Lake read"),
            ) as vector_query,
            mock.patch.object(
                garmin,
                "_load_local_adapter",
                side_effect=AssertionError("unexpected second provider read"),
            ) as adapter_loader,
        ):
            code, stdout, stderr = run_main(
                [
                    "insight_cn",
                    "--days",
                    "3",
                    "--source",
                    "local",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["analysis_type"], "bounded_descriptive_snapshot")
        self.assertIn("overall_insight", payload)
        self.assertIn("observations", payload)
        self.assertNotIn("audit_data", payload)
        self.assertNotIn("quant_scores", payload)
        self.assertEqual(payload["execution_bandwidth"], "[DATA_UNAVAILABLE]")
        self.assertEqual(payload["sleep_debt"], "[DATA_UNAVAILABLE]")
        self.assertNotIn("必须砍掉", payload["overall_insight"])
        self.assertNotIn("严禁执行", payload["overall_insight"])
        self.assertEqual(payload["data_status"], "partial")
        vector_query.assert_not_called()
        adapter_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
