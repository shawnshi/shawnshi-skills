import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import garmin_chart
from garmin_capabilities import issue_capability


class GarminChartFailureContractTests(unittest.TestCase):
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
        wrong_components["components"] = ["sleep"]
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


if __name__ == "__main__":
    unittest.main()
