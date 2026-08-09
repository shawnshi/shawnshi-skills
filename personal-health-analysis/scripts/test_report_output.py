import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from garmin_capabilities import require_capability

import garmin_chart
from report_output import build_report_paths, get_report_dir


class ReportOutputContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for DOM runtime validation")
    def test_dashboard_runtime_keeps_missing_values_distinct_from_zero(self):
        html = garmin_chart.render_report(
            {
                "audit_data": {
                    "system_status": {"rhr": {"current": None, "baseline": None}}
                },
                "overlay_data": {
                    "dates": ["2026-08-09"],
                    "rhr": [None],
                    "hrv": [None],
                    "sleep_h": [0],
                    "sleep_deep_h": [None],
                    "sleep_rem_h": [None],
                    "sleep_light_h": [None],
                    "bb_max": [None],
                    "bb_min": [None],
                },
                "heatmap": [
                    {"date": "2026-08-08", "score": None},
                    {"date": "2026-08-09", "score": 0},
                ],
                "overall_insight": "synthetic",
            }
        )
        encoded = re.search(
            r'<script id="health-data"[^>]*>(.*?)</script>', html, re.DOTALL
        ).group(1)
        runtime_source = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, re.DOTALL)[-1]
        harness = f"""
class Node {{
  constructor() {{ this.textContent=''; this.children=[]; this.style={{}}; this.className=''; }}
  setAttribute() {{}}
  append(...nodes) {{ this.children.push(...nodes); }}
  replaceChildren(...nodes) {{ this.children = nodes; }}
}}
const elements = {{}};
elements['health-data'] = new Node();
elements['health-data'].textContent = {json.dumps(encoded)};
const document = {{
  getElementById(id) {{ return elements[id] || (elements[id] = new Node()); }},
  createElement() {{ return new Node(); }},
  createElementNS() {{ return new Node(); }}
}};
const window = {{ addEventListener(event, callback) {{ if (event === 'DOMContentLoaded') callback(); }} }};
{runtime_source}
console.log(JSON.stringify({{
  rhr: elements['kpi-rhr'].textContent,
  hrv: elements['kpi-hrv'].textContent,
  sleep: elements['kpi-sleep'].textContent,
  cardio_empty: elements['cardio-chart'].children[0].textContent,
  battery_empty: elements['battery-chart'].children[0].textContent,
  missing_score: elements['heatmap'].children[0].children[1].textContent,
  observed_zero_score: elements['heatmap'].children[1].children[1].textContent
}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(
            json.loads(completed.stdout),
            {
                "rhr": "--",
                "hrv": "--",
                "sleep": "0 h",
                "cardio_empty": "无可绘制观测",
                "battery_empty": "无可绘制观测",
                "missing_score": "—",
                "observed_zero_score": "0",
            },
        )

    def test_default_archive_is_workspace_output(self):
        workspace = Path(r"C:\workspace")
        with patch.dict(os.environ, {}, clear=True):
            output_dir = get_report_dir(workspace=workspace)

        self.assertEqual(
            output_dir,
            (workspace / "output" / "personal-health-analysis").resolve(),
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

        self.assertEqual(output_dir, Path(r"D:\private\garmin-reports").resolve())

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
            "health_analysis_7days_20260727_093045_000000.md",
        )
        self.assertEqual(
            paths["html"].name,
            "health_analysis_7days_20260727_093045_000000.html",
        )

    def test_relative_output_is_resolved_to_absolute_path(self):
        paths = build_report_paths(days=7, output_dir=Path("relative-reports"))
        self.assertTrue(paths["output_dir"].is_absolute())
        self.assertTrue(paths["markdown"].is_absolute())
        self.assertTrue(paths["html"].is_absolute())

    def test_existing_report_is_not_overwritten_without_explicit_opt_in(self):
        now = datetime(2026, 7, 27, 9, 30, 45, 123456)
        with tempfile.TemporaryDirectory() as temp_root:
            output_dir = Path(temp_root)
            existing = build_report_paths(days=7, now=now, output_dir=output_dir)
            existing["markdown"].write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                build_report_paths(days=7, now=now, output_dir=output_dir)

            allowed = build_report_paths(
                days=7, now=now, output_dir=output_dir, allow_overwrite=True
            )
            self.assertEqual(allowed["markdown"], existing["markdown"])

    def test_microseconds_reduce_same_second_name_collisions(self):
        first = build_report_paths(
            days=7,
            now=datetime(2026, 7, 27, 9, 30, 45, 1),
            output_dir=Path(r"C:\archive"),
        )
        second = build_report_paths(
            days=7,
            now=datetime(2026, 7, 27, 9, 30, 45, 2),
            output_dir=Path(r"C:\archive"),
        )
        self.assertNotEqual(first["markdown"], second["markdown"])

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

            client = Mock(side_effect=AssertionError("local mode must not initialize client"))
            live_fetch = Mock(side_effect=AssertionError("local mode must not fetch live data"))
            with (
                patch.object(garmin_chart, "HAS_SQLITE", True),
                patch.object(garmin_chart, "fetch_local_summary", return_value=summary),
                patch.object(garmin_chart, "get_client", client),
                patch.object(garmin_chart, "fetch_summary", live_fetch),
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
                    [
                        "garmin_chart.py",
                        "dashboard",
                        "--days",
                        "7",
                        "--allow-health-data",
                    ],
                ),
            ):
                result = garmin_chart.main()

            self.assertEqual(result, 0)
            client.assert_not_called()
            live_fetch.assert_not_called()
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
                        "rem_sleep_seconds": None,
                        "light_sleep_seconds": None,
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
            "sleep_rem_h",
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

    def test_default_local_failure_never_falls_back_live(self):
        client = Mock(side_effect=AssertionError("client must not be initialized"))
        live_fetch = Mock(side_effect=AssertionError("live fetch must not run"))
        with (
            patch.object(garmin_chart, "HAS_SQLITE", True),
            patch.object(
                garmin_chart,
                "fetch_local_summary",
                side_effect=RuntimeError("synthetic local failure"),
            ),
            patch.object(garmin_chart, "get_client", client),
            patch.object(garmin_chart, "fetch_summary", live_fetch),
        ):
            result = garmin_chart.main(
                ["dashboard", "--days", "7", "--allow-health-data"]
            )

        self.assertEqual(result, 1)
        client.assert_not_called()
        live_fetch.assert_not_called()

    def test_live_source_requires_separate_network_authorization(self):
        client = Mock(side_effect=AssertionError("client must not be initialized"))
        live_fetch = Mock(side_effect=AssertionError("live fetch must not run"))
        with (
            patch.object(garmin_chart, "get_client", client),
            patch.object(garmin_chart, "fetch_summary", live_fetch),
        ):
            result = garmin_chart.main(["dashboard", "--source", "live"])

        self.assertEqual(result, 2)
        client.assert_not_called()
        live_fetch.assert_not_called()

    def test_live_summary_loader_rejects_plain_bool_capability(self):
        client = Mock(side_effect=AssertionError("client must not be initialized"))
        with patch.object(garmin_chart, "get_client", client):
            with self.assertRaisesRegex(RuntimeError, "NETWORK_ACCESS_NOT_AUTHORIZED"):
                garmin_chart._load_summary(
                    7,
                    "live",
                    network_capability=True,
                )
        client.assert_not_called()

    def test_live_source_with_network_authorization_uses_mocked_client(self):
        summary = {"sleep": [], "max_metrics": {}}
        insight = {
            "overall_insight": "",
            "audit_data": {},
            "period": {},
            "quant_scores": {},
        }
        synthetic_client = object()
        with tempfile.TemporaryDirectory() as temp_root:
            output_path = Path(temp_root) / "authorized-live.html"
            with (
                patch.object(garmin_chart, "get_client", return_value=synthetic_client) as client,
                patch.object(garmin_chart, "fetch_summary", return_value=summary) as live_fetch,
                patch.object(garmin_chart, "generate_chinese_insight", return_value=insight),
                patch.object(garmin_chart, "build_overlay_data", return_value={}),
                patch.object(garmin_chart, "render_report", return_value="<html>synthetic</html>"),
            ):
                result = garmin_chart.main(
                    [
                        "dashboard",
                        "--source",
                        "live",
                        "--allow-network",
                        "--allow-health-data",
                        "--days",
                        "7",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(result, 0)
            client.assert_called_once()
            self.assertEqual(client.call_args.kwargs["operation"], "dashboard_live")
            require_capability(
                client.call_args.kwargs["network_capability"],
                scope="network",
                operation="dashboard_live",
                request=client.call_args.kwargs["request"],
            )
            request = client.call_args.kwargs["request"]
            live_fetch.assert_called_once_with(
                synthetic_client,
                start=request["start"],
                end=request["end"],
                components=request["components"],
            )
            self.assertEqual(output_path.read_text(encoding="utf-8"), "<html>synthetic</html>")

    def test_existing_output_is_preserved_without_overwrite(self):
        summary = {"sleep": [], "max_metrics": {}}
        insight = {
            "overall_insight": "",
            "audit_data": {},
            "period": {},
            "quant_scores": {},
        }
        with tempfile.TemporaryDirectory() as temp_root:
            output_path = Path(temp_root) / "existing.html"
            output_path.write_text("original", encoding="utf-8")
            with (
                patch.object(garmin_chart, "HAS_SQLITE", True),
                patch.object(garmin_chart, "fetch_local_summary", return_value=summary),
                patch.object(garmin_chart, "generate_chinese_insight", return_value=insight),
                patch.object(garmin_chart, "build_overlay_data", return_value={}),
                patch.object(garmin_chart, "render_report", return_value="replacement"),
            ):
                result = garmin_chart.main(
                    [
                        "dashboard",
                        "--allow-health-data",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(result, 1)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(output_path.parent.glob(".existing.html.*.tmp")), [])

    def test_explicit_overwrite_uses_atomic_replace_and_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output_path = Path(temp_root) / "replace.html"
            output_path.write_text("original", encoding="utf-8")
            real_replace = os.replace
            with patch.object(garmin_chart.os, "replace", wraps=real_replace) as replace:
                garmin_chart._atomic_write_text(
                    output_path,
                    "replacement",
                    overwrite=True,
                )

            replace.assert_called_once()
            self.assertEqual(output_path.read_text(encoding="utf-8"), "replacement")
            self.assertEqual(list(output_path.parent.glob(".replace.html.*.tmp")), [])

    def test_overlay_uses_union_of_dates_and_source_sleep_stages(self):
        overlay = garmin_chart.build_overlay_data(
            {
                "heart_rate": [{"date": "2026-07-26", "resting_hr": 56}],
                "sleep": [
                    {
                        "date": "2026-07-27",
                        "sleep_time_seconds": 28800,
                        "deep_sleep_seconds": 7200,
                        "rem_sleep_seconds": 5400,
                        "light_sleep_seconds": 12600,
                    },
                    {
                        "date": "2026-07-28",
                        "sleep_time_seconds": 25200,
                        "deep_sleep_seconds": 5400,
                        "rem_sleep_seconds": 3600,
                    },
                ],
                "hrv": [{"date": "2026-07-29", "last_night_avg": 44}],
            }
        )

        self.assertEqual(
            overlay["dates"],
            ["2026-07-26", "2026-07-27", "2026-07-28", "2026-07-29"],
        )
        self.assertEqual(overlay["sleep_h"], [None, 8.0, 7.0, None])
        self.assertEqual(overlay["sleep_deep_h"], [None, 2.0, 1.5, None])
        self.assertEqual(overlay["sleep_rem_h"], [None, 1.5, 1.0, None])
        self.assertEqual(overlay["sleep_light_h"], [None, 3.5, None, None])

    def test_heatmap_preserves_missing_score_as_null(self):
        heatmap = garmin_chart.build_heatmap_data(
            {"sleep": [{"date": "2026-07-27"}, {"date": "2026-07-28", "sleep_score": 0}]}
        )
        self.assertIsNone(heatmap[0]["score"])
        self.assertEqual(heatmap[1]["score"], 0.0)

    def test_dashboard_template_is_offline_dom_safe_and_placeholder_complete(self):
        template = garmin_chart.TEMPLATE_FILE.read_text(encoding="utf-8")
        lowered = template.lower()
        self.assertNotRegex(lowered, r"<(?:script|link)[^>]+(?:src|href)\s*=\s*[\"']https?://")
        self.assertNotIn("@import", lowered)
        self.assertNotIn("innerhtml", lowered)
        self.assertIn("connect-src 'none'", lowered)
        self.assertIn("default-src 'none'", lowered)
        self.assertNotIn("#10b981", lowered)
        self.assertNotIn("#ef4444", lowered)

        html = garmin_chart.render_report(
            {
                "audit_data": {"system_status": {"rhr": {"current": None, "baseline": None}}},
                "overlay_data": {"dates": [], "weighted_dissipation": []},
                "overall_insight": "synthetic",
            }
        )
        self.assertNotIn("%%", html)
        self.assertIn('<strong class="delta">--%</strong>', html)


if __name__ == "__main__":
    unittest.main()
