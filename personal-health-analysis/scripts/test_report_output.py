import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import garmin_chart
from report_output import build_report_paths, get_report_dir


class ReportOutputContractTests(unittest.TestCase):
    def test_default_archive_is_workspace_output(self):
        workspace = Path(r"C:\workspace")
        with patch.dict(os.environ, {}, clear=True):
            output_dir = get_report_dir(workspace=workspace)

        self.assertEqual(
            output_dir,
            workspace / "output" / "personal-health-analysis",
        )

    def test_report_dir_override_has_priority(self):
        with patch.dict(
            os.environ,
            {
                "GARMIN_REPORT_DIR": r"D:\private\garmin-reports",
                "GARMIN_OUTPUT_DIR": r"D:\legacy-output",
            },
            clear=True,
        ):
            output_dir = get_report_dir()

        self.assertEqual(output_dir, Path(r"D:\private\garmin-reports"))

    def test_markdown_and_html_share_one_stem(self):
        now = datetime(2026, 7, 27, 9, 30, 45)
        paths = build_report_paths(
            days=7,
            now=now,
            output_dir=Path(r"C:\archive"),
        )

        self.assertEqual(paths["markdown"].stem, paths["html"].stem)
        self.assertEqual(
            paths["markdown"].name,
            "health_analysis_7days_20260727_093045.md",
        )
        self.assertEqual(
            paths["html"].name,
            "health_analysis_7days_20260727_093045.html",
        )

    def test_create_dir_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output_dir = Path(temp_root) / "nested" / "garmin"
            self.assertFalse(output_dir.exists())

            build_report_paths(days=30, output_dir=output_dir, create_dir=False)
            self.assertFalse(output_dir.exists())

            build_report_paths(days=30, output_dir=output_dir, create_dir=True)
            self.assertTrue(output_dir.is_dir())

    def test_days_must_be_positive(self):
        with self.assertRaises(ValueError):
            build_report_paths(days=0)

    def test_dashboard_uses_archive_allocator_when_output_is_omitted(self):
        with tempfile.TemporaryDirectory() as temp_root:
            html_path = Path(temp_root) / "health_analysis_7days_test.html"
            allocator = Mock(return_value={"html": html_path})
            summary = {"sleep": [], "max_metrics": {}}
            insight = {
                "overall_insight": "",
                "audit_data": {},
                "period": {},
                "quant_scores": {},
            }

            with (
                patch.object(garmin_chart, "HAS_SQLITE", False),
                patch.object(garmin_chart, "get_client", return_value=object()),
                patch.object(garmin_chart, "fetch_summary", return_value=summary),
                patch.object(
                    garmin_chart,
                    "generate_chinese_insight",
                    return_value=insight,
                ),
                patch.object(garmin_chart, "build_overlay_data", return_value={}),
                patch.object(
                    garmin_chart,
                    "render_report",
                    return_value="<html>verified</html>",
                ),
                patch.object(garmin_chart, "build_report_paths", allocator),
                patch.object(
                    os.sys,
                    "argv",
                    ["garmin_chart.py", "dashboard", "--days", "7"],
                ),
            ):
                garmin_chart.main()

            allocator.assert_called_once_with(days=7, create_dir=True)
            self.assertEqual(
                html_path.read_text(encoding="utf-8"),
                "<html>verified</html>",
            )

    def test_overlay_preserves_missing_health_observations_as_null(self):
        date = "2026-07-28"
        overlay = garmin_chart.build_overlay_data(
            {
                "sleep": [
                    {
                        "date": date,
                        "sleep_time_seconds": None,
                        "deep_sleep_seconds": None,
                        "sleep_score": None,
                        "avg_spo2": None,
                    }
                ],
                "heart_rate": [
                    {"date": date, "resting_hr": None, "max_hr": None}
                ],
                "stress": [
                    {
                        "date": date,
                        "avg_stress": None,
                        "high_stress_duration": None,
                        "medium_stress_duration": None,
                        "steps": None,
                    }
                ],
                "body_battery": [
                    {"date": date, "highest": None, "lowest": None}
                ],
                "hrv": [
                    {"date": date, "last_night_avg": None, "status": None}
                ],
                "daily_summary": [
                    {"date": date, "sweat_loss": None, "rr_waking_avg": None}
                ],
            }
        )

        for field in (
            "stress_h",
            "bb_max",
            "bb_min",
            "rhr",
            "max_hr",
            "sleep_h",
            "sleep_deep_h",
            "sleep_light_h",
            "sleep_score",
            "hrv",
            "steps",
            "weighted_dissipation",
            "spo2_history",
            "waking_rr",
            "sweat_loss",
        ):
            self.assertEqual(overlay[field], [None], field)


if __name__ == "__main__":
    unittest.main()
