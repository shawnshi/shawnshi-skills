import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from garmin_capabilities import require_capability

import garmin_chart
from report_output import build_report_paths, get_report_dir


def decode_dashboard_payload(html):
    encoded = re.search(
        r'<script id="health-data"[^>]*>(.*?)</script>', html, re.DOTALL
    ).group(1)
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


def comparable_summary(start_day, prior_days):
    hrv = []
    heart_rate = []
    sleep = []
    for offset in range(prior_days + 1):
        day = (start_day + timedelta(days=offset)).isoformat()
        hrv.append({"date": day, "last_night_avg": 45 + (offset % 5)})
        heart_rate.append({"date": day, "resting_hr": 54 + (offset % 4)})
        sleep.append({"date": day, "sleep_time_seconds": 25200 + offset * 60})
    return {
        "summary": {
            "period": f"{start_day.isoformat()} to {heart_rate[-1]['date']}",
            "days": prior_days + 1,
        },
        "heart_rate": heart_rate,
        "hrv": hrv,
        "sleep": sleep,
        "body_battery": [],
        "stress": [],
        "device_info": [
            {
                "serial_number": "must-not-be-embedded",
                "software_version": "19.00",
            }
        ],
        "measurement_epoch_evidence": {
            "analysis_algorithm_epoch": "personal-health-analysis:baseline-change:v2",
            "manufacturer_algorithm_epoch": "synthetic-manufacturer-v1",
            "firmware_history": [
                {
                    "timestamp": f"{start_day.isoformat()}T00:00:00",
                    "serial_number": "must-not-be-embedded",
                    "software_version": "19.00",
                }
            ],
        },
        "activities": [{"date": start_day.isoformat(), "steps": 999999}],
        "is_stale": False,
        "data_gaps": [],
        "data_integrity": {
            "status": "verified_unchanged",
            "databases": [
                {
                    "database": "garmin.db",
                    "sha256": "a" * 64,
                    "storage_sha256": "b" * 64,
                }
            ],
        },
    }


class ReportOutputContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for DOM runtime validation")
    def test_dashboard_keeps_history_and_marks_unsynced_terminal_day(self):
        start = date(2026, 8, 23)
        end = start + timedelta(days=1)
        summary = {
            "summary": {"period": f"{start} to {end}", "days": 2},
            "heart_rate": [{"date": start.isoformat(), "resting_hr": 52}],
            "hrv": [{"date": start.isoformat(), "last_night_avg": 44}],
            "sleep": [{"date": start.isoformat(), "sleep_time_seconds": 28200, "deep_sleep_seconds": 5400, "rem_sleep_seconds": 7200, "light_sleep_seconds": 15600, "avg_respiration": 15, "avg_spo2": 96}],
            "body_battery": [{"date": start.isoformat(), "highest": 100, "lowest": 41}],
            "stress": [{"date": start.isoformat(), "avg_stress": 19, "steps": 3385}],
            "measurement_epoch_evidence": {},
        }
        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=2,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep", "hrv", "body_battery", "heart_rate", "stress"),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-24T12:00:00+08:00",
        )
        html = garmin_chart.render_report(payload)
        encoded = re.search(r'<script id="health-data"[^>]*>(.*?)</script>', html, re.DOTALL).group(1)
        runtime_source = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, re.DOTALL)[-1]
        harness = f"""
class Node {{
  constructor(name='node') {{ this.nodeName=name; this.textContent=''; this.children=[]; this.style={{}}; this.className=''; this.attributes={{}}; }}
  setAttribute(key,value) {{ this.attributes[key]=String(value); }}
  removeAttribute(key) {{ delete this.attributes[key]; }}
  append(...nodes) {{ this.children.push(...nodes); }}
  replaceChildren(...nodes) {{ this.children = nodes; }}
}}
const elements = {{}};
elements['health-data'] = new Node('script');
elements['health-data'].textContent = {json.dumps(encoded)};
const document = {{ getElementById(id) {{ return elements[id] || (elements[id] = new Node()); }}, createElement(name) {{ return new Node(name); }}, createElementNS(_namespace,name) {{ return new Node(name); }} }};
const window = {{ addEventListener(event, callback) {{ if (event === 'DOMContentLoaded') callback(); }} }};
{runtime_source}
const ids=['rhr-chart','hrv-chart','sleep-chart','battery-chart','steps-chart','stress-chart','respiration-chart','spo2-chart'];
console.log(JSON.stringify(Object.fromEntries(ids.map(id=>[id,{{children:elements[id].children.length,note:elements[id].children[1]?.textContent||'',svg:elements[id].children[0]?.nodeName||''}}]))));
"""
        completed = subprocess.run([shutil.which("node"), "-"], input=harness, check=True, capture_output=True, text=True, encoding="utf-8")
        rendered = json.loads(completed.stdout)
        for item in rendered.values():
            self.assertEqual(item["children"], 2)
            self.assertEqual(item["svg"], "svg")
            self.assertEqual(item["note"], "2026-08-24 当日未同步；图表保留此前已同步观测。")
        self.assertIn("整体评价与后续建议", html)
        self.assertIn("后续建议（非处方）", html)

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
  constructor(name='node') {{
    this.nodeName=name; this.textContent=''; this.children=[]; this.style={{}};
    this.className=''; this.attributes={{}};
  }}
  setAttribute(key,value) {{ this.attributes[key]=String(value); }}
  removeAttribute(key) {{ delete this.attributes[key]; }}
  append(...nodes) {{ this.children.push(...nodes); }}
  replaceChildren(...nodes) {{ this.children = nodes; }}
}}
const elements = {{}};
elements['health-data'] = new Node('script');
elements['health-data'].textContent = {json.dumps(encoded)};
const document = {{
  getElementById(id) {{ return elements[id] || (elements[id] = new Node()); }},
  createElement(name) {{ return new Node(name); }},
  createElementNS(_namespace,name) {{ return new Node(name); }}
}};
const window = {{ addEventListener(event, callback) {{ if (event === 'DOMContentLoaded') callback(); }} }};
{runtime_source}
console.log(JSON.stringify({{
  rhr: elements['kpi-rhr'].textContent,
  hrv: elements['kpi-hrv'].textContent,
  sleep: elements['kpi-sleep'].textContent,
  rhr_empty: elements['rhr-chart'].children[0].textContent,
  hrv_empty: elements['hrv-chart'].children[0].textContent,
  battery_empty: elements['battery-chart'].children[0].textContent,
  missing_score: elements['sleep-score-heatmap'].children[0].children[1].textContent,
  observed_zero_score: elements['sleep-score-heatmap'].children[1].children[1].textContent,
  baseline: elements['baseline-value'].textContent,
  requested_range: elements['trust-requested-range'].textContent
}}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-"],
            input=harness,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(
            json.loads(completed.stdout),
            {
                "rhr": "—",
                "hrv": "—",
                "sleep": "0 h",
                "rhr_empty": "无可绘制观测",
                "hrv_empty": "无可绘制观测",
                "battery_empty": "无可绘制观测",
                "missing_score": "缺失",
                "observed_zero_score": "0",
                "baseline": "未计算",
                "requested_range": "2026-08-09 至 2026-08-09（1 天）",
            },
        )

    def test_dashboard_payload_is_minimal_and_baseline_is_gated(self):
        start = date(2026, 7, 1)
        summary = comparable_summary(start, 6)
        summary["overlay_only_secret"] = "must-not-be-embedded"
        summary["data_integrity"]["databases"] = [
            {"database": r"C:\private\health\garmin.db", "sha256": "a" * 64},
            {"database": r"\\private-host\health\activities.db", "sha256": "b" * 64},
        ]

        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=7,
            requested_source="local",
            effective_source="local",
            selected_components=tuple(garmin_chart.LIVE_SUMMARY_COMPONENTS),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=(start + timedelta(days=6)).isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )
        html = garmin_chart.render_report(payload)
        embedded = decode_dashboard_payload(html)
        serialized = json.dumps(embedded, ensure_ascii=False)

        self.assertEqual(
            set(embedded),
            {
                "schema_version",
                "meta",
                "coverage",
                "baseline",
                "kpis",
                "series",
                "heatmap",
                "patterns",
                "narrative",
            },
        )
        self.assertEqual(embedded["schema_version"], "dashboard.v3")
        self.assertEqual(embedded["baseline"]["status"], "insufficient_baseline")
        self.assertIsNone(embedded["baseline"]["rhr"]["delta_pct"])
        self.assertNotIn("serial_number", serialized)
        self.assertNotIn("must-not-be-embedded", serialized)
        self.assertNotIn("weighted_dissipation", serialized)
        self.assertNotIn("quant_scores", serialized)
        self.assertIn('"steps"', serialized)
        self.assertNotIn("999999", serialized)
        self.assertNotIn('"sha256"', serialized)
        self.assertNotIn(r"C:\private\health", serialized)
        self.assertNotIn("private-host", serialized)
        self.assertEqual(embedded["meta"]["integrity"]["database_count"], 2)
        self.assertNotIn("databases", embedded["meta"]["integrity"])

    def test_dashboard_builder_discards_unrequested_source_metrics(self):
        start = date(2026, 7, 27)
        end = start + timedelta(days=13)
        summary = {
            "summary": {"period": f"{start} to {end}", "days": 14},
            "sleep": [
                {
                    "date": end.isoformat(),
                    "sleep_time_seconds": 0,
                    "sleep_score": 0,
                }
            ],
            "heart_rate": [{"date": end.isoformat(), "resting_hr": 199}],
            "hrv": [{"date": end.isoformat(), "last_night_avg": 199}],
            "stress": [{"date": end.isoformat(), "avg_stress": 199}],
            "body_battery": [
                {"date": end.isoformat(), "highest": 199, "lowest": 199}
            ],
            "activities": [{"date": end.isoformat(), "steps": 199199}],
            "data_gaps": ["untrusted-source-gap-secret"],
        }

        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=14,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep",),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(all(value is None for value in payload["series"]["rhr_bpm"]))
        self.assertTrue(all(value is None for value in payload["series"]["hrv_ms"]))
        self.assertIsNone(payload["kpis"]["rhr"]["value"])
        self.assertIsNone(payload["kpis"]["hrv"]["value"])
        self.assertIsNone(payload["kpis"]["stress"]["value"])
        self.assertEqual(payload["coverage"]["rhr"]["status"], "not_requested")
        self.assertEqual(payload["coverage"]["stress"]["status"], "not_requested")
        self.assertEqual(payload["baseline"]["status"], "not_requested")
        self.assertEqual(payload["heatmap"]["status"], "available")
        self.assertEqual(payload["heatmap"]["items"][-1]["score"], 0)
        self.assertIn("睡眠总时长 0 h", payload["narrative"]["overall"])
        self.assertNotIn("静息心率 None", payload["narrative"]["overall"])
        self.assertNotIn("199", serialized)
        self.assertNotIn("untrusted-source-gap-secret", serialized)

    def test_dashboard_rhr_delta_requires_qualified_comparable_baseline(self):
        start = date(2026, 7, 1)
        summary = comparable_summary(start, garmin_chart.MIN_PAIRED_BASELINE_DAYS)
        end = start + timedelta(days=garmin_chart.MIN_PAIRED_BASELINE_DAYS)

        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=garmin_chart.MIN_PAIRED_BASELINE_DAYS + 1,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep", "hrv", "heart_rate"),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )

        self.assertEqual(payload["baseline"]["status"], "qualified")
        self.assertTrue(payload["baseline"]["qualified"])
        self.assertEqual(
            payload["baseline"]["paired_baseline_days"],
            garmin_chart.MIN_PAIRED_BASELINE_DAYS,
        )
        self.assertEqual(payload["baseline"]["baseline_start"], start.isoformat())
        self.assertEqual(
            payload["baseline"]["baseline_end"],
            (end - timedelta(days=1)).isoformat(),
        )
        self.assertIsNotNone(payload["baseline"]["rhr"]["delta_pct"])

        summary["measurement_epoch_evidence"]["firmware_history"] = []
        unknown_epoch = garmin_chart.build_dashboard_payload(
            summary,
            days=garmin_chart.MIN_PAIRED_BASELINE_DAYS + 1,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep", "hrv", "heart_rate"),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )
        self.assertEqual(unknown_epoch["baseline"]["status"], "epoch_unknown")
        self.assertFalse(unknown_epoch["baseline"]["qualified"])
        self.assertIsNone(unknown_epoch["baseline"]["rhr"]["delta_pct"])

    def test_render_report_strips_forged_unqualified_baseline_values(self):
        start = date(2026, 7, 1)
        summary = comparable_summary(start, garmin_chart.MIN_PAIRED_BASELINE_DAYS)
        end = start + timedelta(days=garmin_chart.MIN_PAIRED_BASELINE_DAYS)
        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=garmin_chart.MIN_PAIRED_BASELINE_DAYS + 1,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep", "hrv", "heart_rate"),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )
        payload["baseline"]["qualified"] = False
        payload["baseline"]["status"] = "epoch_unknown"
        payload["baseline"]["rhr"]["baseline"] = 999
        payload["baseline"]["rhr"]["delta_pct"] = 999
        payload["baseline"]["hrv"]["baseline"] = 999

        embedded = decode_dashboard_payload(garmin_chart.render_report(payload))

        self.assertFalse(embedded["baseline"]["qualified"])
        self.assertIsNone(embedded["baseline"]["rhr"]["baseline"])
        self.assertIsNone(embedded["baseline"]["rhr"]["delta_pct"])
        self.assertIsNone(embedded["baseline"]["hrv"]["baseline"])

    def test_dashboard_kpis_bind_dates_and_use_raw_stress_fields(self):
        start = date(2026, 8, 1)
        end = start + timedelta(days=6)
        summary = {
            "summary": {"period": f"{start} to {end}", "days": 7},
            "heart_rate": [{"date": end.isoformat(), "resting_hr": 59}],
            "hrv": [
                {
                    "date": (end - timedelta(days=1)).isoformat(),
                    "last_night_avg": 43,
                }
            ],
            "sleep": [
                {
                    "date": (end - timedelta(days=2)).isoformat(),
                    "sleep_time_seconds": 0,
                    "deep_sleep_seconds": None,
                    "rem_sleep_seconds": None,
                    "light_sleep_seconds": None,
                    "sleep_score": 0,
                }
            ],
            "stress": [
                {
                    "date": (end - timedelta(days=3)).isoformat(),
                    "avg_stress": 32,
                    "steps": 6789,
                    "high_stress_duration": 3600,
                    "medium_stress_duration": 7200,
                    "rest_stress_duration": 10800,
                }
            ],
            "body_battery": [],
            "device_info": [],
            "measurement_epoch_evidence": {},
            "is_stale": False,
            "data_gaps": [],
        }

        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=7,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep", "hrv", "heart_rate", "stress"),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )

        self.assertEqual(payload["series"]["dates"][0], start.isoformat())
        self.assertEqual(payload["series"]["dates"][-1], end.isoformat())
        self.assertEqual(len(payload["series"]["dates"]), 7)
        self.assertEqual(payload["kpis"]["rhr"]["observed_date"], end.isoformat())
        self.assertEqual(
            payload["kpis"]["hrv"]["observed_date"],
            (end - timedelta(days=1)).isoformat(),
        )
        self.assertEqual(payload["kpis"]["sleep"]["value"], 0)
        self.assertEqual(
            payload["kpis"]["stress"]["observed_date"],
            (end - timedelta(days=3)).isoformat(),
        )
        self.assertEqual(payload["kpis"]["stress"]["value"], 32)
        self.assertEqual(payload["series"]["stress_avg"][3], 32)
        self.assertEqual(payload["series"]["steps"][3], 6789)
        self.assertEqual(payload["coverage"]["stress"]["observed_days"], 1)
        self.assertEqual(payload["coverage"]["steps"]["observed_days"], 1)
        self.assertEqual(
            payload["kpis"]["stress"]["details"],
            {"high_h": 1.0, "medium_h": 2.0, "rest_h": 3.0},
        )
        self.assertEqual(payload["coverage"]["rhr"]["observed_days"], 1)
        self.assertEqual(payload["coverage"]["sleep_total"]["observed_days"], 1)

    def test_dashboard_projects_sleep_respiration_spo2_and_missing_streaks(self):
        start = date(2026, 8, 1)
        end = start + timedelta(days=6)
        summary = {
            "summary": {"days": 7},
            "sleep": [
                {
                    "date": start.isoformat(),
                    "sleep_time_seconds": 28800,
                    "avg_respiration": 14.5,
                    "avg_spo2": 96,
                },
                {
                    "date": end.isoformat(),
                    "sleep_time_seconds": 0,
                    "avg_respiration": 0,
                    "avg_spo2": 0,
                },
            ],
            "component_status": {"sleep": {"status": "partial"}},
            "measurement_epoch_evidence": {},
        }

        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=7,
            requested_source="local",
            effective_source="local",
            selected_components=("sleep",),
            live_fallback_attempted=False,
            requested_start=start.isoformat(),
            requested_end=end.isoformat(),
            generated_at="2026-08-09T12:00:00+08:00",
        )

        self.assertEqual(payload["series"]["sleep_respiration_brpm"], [14.5, None, None, None, None, None, 0])
        self.assertEqual(payload["series"]["sleep_spo2_pct"], [96, None, None, None, None, None, 0])
        self.assertEqual(payload["coverage"]["sleep_respiration"]["observed_days"], 2)
        self.assertEqual(payload["coverage"]["sleep_respiration"]["observed_zero_days"], 1)
        self.assertEqual(
            payload["coverage"]["sleep_respiration"]["longest_missing_streak_days"],
            5,
        )
        self.assertEqual(
            payload["coverage"]["sleep_respiration"]["current_missing_streak_days"],
            0,
        )

    def test_conflicting_same_day_values_are_not_silently_last_write_wins(self):
        records = [
            {"date": "2026-08-09", "last_night_avg": 40},
            {"date": "2026-08-09", "last_night_avg": 55},
        ]
        identical = [
            {"date": "2026-08-09", "last_night_avg": 40},
            {"date": "2026-08-09", "last_night_avg": 40},
        ]

        self.assertIsNone(garmin_chart._dated_map(records, "last_night_avg")["2026-08-09"])
        self.assertEqual(
            garmin_chart._dated_map(identical, "last_night_avg")["2026-08-09"],
            40,
        )

    def test_default_archive_is_canonical_garmin_raw_directory(self):
        workspace = Path(r"C:\workspace")
        with patch.dict(os.environ, {}, clear=True):
            output_dir = get_report_dir(workspace=workspace)

        self.assertEqual(
            output_dir,
            Path(r"C:\Users\shich\MEMORY\raw\garmin").resolve(),
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
        self.assertNotIn("fetch(", lowered)
        self.assertNotIn("xmlhttprequest", lowered)
        self.assertNotIn("websocket", lowered)
        self.assertIn('id="trust-bar"', lowered)
        self.assertIn('id="rhr-chart"', lowered)
        self.assertIn('id="hrv-chart"', lowered)
        self.assertNotIn('id="cardio-chart"', lowered)
        self.assertIn('@media print', lowered)
        self.assertIn('@media(max-width:520px)', lowered.replace(" ", ""))
        self.assertIn("flex-wrap:wrap", lowered.replace(" ", ""))
        self.assertNotRegex(lowered, r"<details\s+open")
        self.assertNotIn("%%RHR_DELTA%%", template)
        self.assertNotIn("%%WEIGHTED_VAL%%", template)
        self.assertNotIn("记录压力时长", template)

        html = garmin_chart.render_report(
            {
                "audit_data": {"system_status": {"rhr": {"current": None, "baseline": None}}},
                "overlay_data": {"dates": [], "weighted_dissipation": []},
                "overall_insight": "synthetic",
            }
        )
        self.assertNotIn("%%", html)
        self.assertIn('id="baseline-value"', html)


if __name__ == "__main__":
    unittest.main()
