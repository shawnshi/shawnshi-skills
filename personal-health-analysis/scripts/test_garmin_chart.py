import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

import garmin_chart
import garmin_intelligence
from garmin_capabilities import issue_capability


class _VerifiedWindowStub:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def public_summary(self):
        return {"status": "verified_unchanged", "databases": []}


class GarminChartFailureContractTests(unittest.TestCase):
    def test_default_dashboard_reads_only_rendered_components(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "default-scope.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "no_data"},
                ) as fetch_local,
                patch.object(
                    garmin_chart,
                    "build_dashboard_payload",
                    return_value={"schema_version": "dashboard.v3"},
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        fetch_local.assert_called_once_with(
            7, components=garmin_chart.DASHBOARD_DEFAULT_COMPONENTS
        )
        self.assertNotIn("activities", garmin_chart.DASHBOARD_DEFAULT_COMPONENTS)
        self.assertNotIn("training_load_series", garmin_chart.DASHBOARD_DEFAULT_COMPONENTS)

    def test_local_dashboard_requires_health_data_permission_before_read(self):
        stderr = io.StringIO()
        with (
            patch.object(
                garmin_chart,
                "fetch_local_summary",
                side_effect=AssertionError("permission gate must run before local read"),
            ) as fetch_local,
            patch("sys.stderr", stderr),
        ):
            result = garmin_chart.main(["dashboard", "--days", "7"])

        self.assertEqual(result, 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["status"],
            "HEALTH_DATA_ACCESS_NOT_AUTHORIZED",
        )
        fetch_local.assert_not_called()

    def test_invalid_period_stops_before_live_client_initialization(self):
        stderr = io.StringIO()
        with (
            patch.object(garmin_chart, "get_client") as get_client,
            patch("sys.stderr", stderr),
        ):
            result = garmin_chart.main(
                [
                    "dashboard",
                    "--source",
                    "live",
                    "--period",
                    "0d",
                    "--allow-network",
                    "--allow-health-data",
                ]
            )
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(stderr.getvalue())["status"], "INVALID_PERIOD_SCOPE")
        get_client.assert_not_called()

    def test_malformed_bound_scope_stops_before_live_client_initialization(self):
        base = {
            "chart": "dashboard",
            "source": "live",
            "start": "2026-08-01",
            "end": "2026-08-02",
            "components": list(garmin_chart.LIVE_SUMMARY_COMPONENTS),
        }
        malformed = []
        wrong_components = dict(base)
        wrong_components["components"] = ["sleep", "profile"]
        malformed.append(wrong_components)
        wrong_window = dict(base)
        wrong_window["end"] = "2026-08-03"
        malformed.append(wrong_window)
        invalid_date = dict(base)
        invalid_date["start"] = "not-a-date"
        malformed.append(invalid_date)

        for request in malformed:
            with self.subTest(request=request), patch.object(
                garmin_chart, "get_client"
            ) as get_client:
                with self.assertRaisesRegex(RuntimeError, "LIVE_SCOPE_INVALID"):
                    garmin_chart._load_summary(
                        2,
                        "live",
                        network_capability=issue_capability(
                            scope="network",
                            operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                            request=request,
                        ),
                        health_data_capability=issue_capability(
                            scope="health_data",
                            operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                            request=request,
                        ),
                        request=request,
                    )
                get_client.assert_not_called()

    def test_live_dashboard_uses_exact_bound_window_and_fixed_components(self):
        request = {
            "chart": "dashboard",
            "source": "live",
            "start": "2026-08-01",
            "end": "2026-08-02",
            "components": list(garmin_chart.LIVE_SUMMARY_COMPONENTS),
        }
        client = object()
        with (
            patch.object(garmin_chart, "get_client", return_value=client),
            patch.object(
                garmin_chart, "fetch_summary", return_value={"summary": {}}
            ) as fetch,
        ):
            result = garmin_chart._load_summary(
                2,
                "live",
                network_capability=issue_capability(
                    scope="network",
                    operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                    request=request,
                ),
                health_data_capability=issue_capability(
                    scope="health_data",
                    operation=garmin_chart.DASHBOARD_LIVE_OPERATION,
                    request=request,
                ),
                request=request,
            )

        self.assertEqual(result, {"summary": {}})
        fetch.assert_called_once_with(
            client,
            start="2026-08-01",
            end="2026-08-02",
            components=request["components"],
        )

    def test_database_change_fails_before_dashboard_write(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "dashboard.html"
            stderr = io.StringIO()
            with (
                patch.object(garmin_chart, "HAS_SQLITE", True),
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    side_effect=RuntimeError("database_changed_during_read"),
                ),
                patch("sys.stderr", stderr),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertFalse(output.exists())
            payload = json.loads(stderr.getvalue())
            self.assertEqual(payload["status"], "DATA_SOURCE_UNAVAILABLE")
            self.assertEqual(payload["source"], "local")
            self.assertFalse(payload["live_fallback_attempted"])

    def test_no_data_fallback_requires_explicit_network_authorization(self):
        stderr = io.StringIO()
        with (
            patch.object(garmin_chart, "fetch_local_summary") as fetch_local,
            patch.object(garmin_chart, "get_client") as get_client,
            patch("sys.stderr", stderr),
        ):
            rc = garmin_chart.main(
                [
                    "dashboard",
                    "--days",
                    "7",
                    "--source",
                    "local",
                    "--fallback-live",
                    "--components",
                    "sleep,hrv,body_battery,heart_rate,activities,stress",
                    "--allow-health-data",
                ]
            )

        self.assertEqual(rc, 2)
        self.assertEqual(
            json.loads(stderr.getvalue())["status"],
            "NETWORK_ACCESS_NOT_AUTHORIZED",
        )
        fetch_local.assert_not_called()
        get_client.assert_not_called()

    def test_local_no_data_falls_back_to_exact_authorized_components(self):
        components = [
            "sleep",
            "hrv",
            "body_battery",
            "heart_rate",
            "activities",
            "stress",
        ]
        insight = {
            "overall_insight": "fixture",
            "audit_data": {},
            "period": "fixture",
            "quant_scores": {},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "fallback.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "no_data"},
                ),
                patch.object(garmin_chart, "get_client", return_value=object()) as get_client,
                patch.object(
                    garmin_chart,
                    "fetch_summary",
                    return_value={"status": "partial", "sleep": []},
                ) as fetch_summary,
                patch.object(
                    garmin_chart, "generate_chinese_insight", return_value=insight
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--fallback-live",
                        "--components",
                        ",".join(components),
                        "--allow-network",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        request = get_client.call_args.kwargs["request"]
        self.assertEqual(request["components"], components)
        fetch_summary.assert_called_once_with(
            get_client.return_value,
            start=request["start"],
            end=request["end"],
            components=components,
        )

    def test_real_local_no_data_contract_triggers_authorized_live_fallback(self):
        components = list(garmin_chart.LIVE_SUMMARY_COMPONENTS)
        null_summary = garmin_intelligence.pd.DataFrame(
            [
                {
                    "date": date.today().isoformat(),
                    "resting_heart_rate": None,
                    "stress_avg": None,
                    "body_battery_highest": None,
                }
            ]
        )
        empty = garmin_intelligence.pd.DataFrame()
        observed_local = []
        real_fetch_local = garmin_intelligence.fetch_local_summary

        def fetch_real_no_data(days, *, components=None):
            result = real_fetch_local(days, components=components)
            observed_local.append(result)
            return result

        with tempfile.TemporaryDirectory() as temp_root, ExitStack() as stack:
            output = Path(temp_root) / "real-no-data-fallback.html"
            stack.enter_context(patch.object(garmin_intelligence, "HAS_SQLITE", True))
            stack.enter_context(
                patch.object(
                    garmin_intelligence,
                    "_verified_local_read_window",
                    return_value=_VerifiedWindowStub(),
                )
            )
            stack.enter_context(
                patch.object(
                    garmin_intelligence, "sqlite_summary", return_value=null_summary
                )
            )
            for name in (
                "sqlite_sleep",
                "sqlite_hrv",
                "sqlite_activities",
                "sqlite_biomechanics",
                "get_body_composition_detailed",
                "get_devices_info",
                "get_device_firmware_history",
            ):
                stack.enter_context(
                    patch.object(garmin_intelligence, name, return_value=empty)
                )
            stack.enter_context(
                patch.object(garmin_intelligence, "usable_method_config", return_value=None)
            )
            stack.enter_context(
                patch.object(garmin_chart, "fetch_local_summary", side_effect=fetch_real_no_data)
            )
            get_client = stack.enter_context(
                patch.object(garmin_chart, "get_client", return_value=object())
            )
            fetch_summary = stack.enter_context(
                patch.object(
                    garmin_chart,
                    "fetch_summary",
                    return_value={"status": "partial", "sleep": []},
                )
            )
            stack.enter_context(
                patch.object(
                    garmin_chart, "render_report", return_value="<html></html>"
                )
            )

            rc = garmin_chart.main(
                [
                    "dashboard",
                    "--days",
                    "7",
                    "--source",
                    "local",
                    "--fallback-live",
                    "--components",
                    ",".join(components),
                    "--allow-network",
                    "--allow-health-data",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(rc, 0)
        self.assertEqual(observed_local[0]["status"], "no_data")
        self.assertTrue(
            all(
                observed_local[0]["component_status"][name]["status"] == "no_data"
                for name in components
            )
        )
        request = get_client.call_args.kwargs["request"]
        fetch_summary.assert_called_once_with(
            get_client.return_value,
            start=request["start"],
            end=request["end"],
            components=components,
        )

    def test_partial_local_data_does_not_fall_back_live(self):
        insight = {
            "overall_insight": "fixture",
            "audit_data": {},
            "period": "fixture",
            "quant_scores": {},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            output = Path(temp_root) / "local-partial.html"
            with (
                patch.object(
                    garmin_chart,
                    "fetch_local_summary",
                    return_value={"status": "partial", "sleep": []},
                ),
                patch.object(garmin_chart, "get_client") as get_client,
                patch.object(
                    garmin_chart, "generate_chinese_insight", return_value=insight
                ),
                patch.object(garmin_chart, "render_report", return_value="<html></html>"),
            ):
                rc = garmin_chart.main(
                    [
                        "dashboard",
                        "--days",
                        "7",
                        "--source",
                        "local",
                        "--fallback-live",
                        "--components",
                        "sleep,hrv,body_battery,heart_rate,activities,stress",
                        "--allow-network",
                        "--allow-health-data",
                        "--output",
                        str(output),
                    ]
                )

        self.assertEqual(rc, 0)
        get_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
