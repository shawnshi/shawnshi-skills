import base64
import json
import re
import shutil
import subprocess
import unittest
from datetime import date, timedelta

import garmin_chart
import garmin_intelligence
import garmin_patterns


def _dates(start: str, count: int) -> list[str]:
    first = date.fromisoformat(start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(count)]


def _known_epoch_summary(start: str = "2026-07-01", count: int = 28) -> dict:
    days = _dates(start, count)
    historical_count = max(0, count - 7)
    historical = [(index % 21) + 1 for index in range(historical_count)]
    recent = [30] * min(7, count)
    values = historical + recent
    return {
        "summary": {"days": count},
        "heart_rate": [
            {"date": day, "resting_hr": 50 + value}
            for day, value in zip(days, values, strict=True)
        ],
        "hrv": [
            {"date": day, "last_night_avg": 35 + value}
            for day, value in zip(days, values, strict=True)
        ],
        "sleep": [
            {
                "date": day,
                "sleep_time_seconds": 21600 + value * 120,
                "avg_respiration": 11 + value / 10,
                "avg_spo2": 90 + value / 20,
            }
            for day, value in zip(days, values, strict=True)
        ],
        "training_load_series": [
            {"date": day, "acute_load": float(index + 1)}
            for index, day in enumerate(days)
        ],
        "component_status": {
            "sleep": {"status": "complete"},
            "hrv": {"status": "complete"},
            "heart_rate": {"status": "complete"},
            "training_load_series": {
                "status": "observed",
                "coverage_semantics": "event_stream",
                "zero_semantics": "unknown",
            },
        },
        "measurement_epoch_evidence": {
            "analysis_algorithm_epoch": "test:patterns:v1",
            "manufacturer_algorithm_epoch": "synthetic-manufacturer-v1",
            "observation_attributions": [
                {"component": component, "date": day, "serial_number": "synthetic-device", "software_version": "1.0"}
                for component in ("heart_rate", "hrv", "sleep", "training_load_series")
                for day in days
            ],
            "firmware_history": [
                {
                    "timestamp": "2026-06-01T00:00:00+08:00",
                    "serial_number": "synthetic-device",
                    "software_version": "1.0",
                }
            ],
        },
    }


def _embedded_payload(html: str) -> dict:
    encoded = re.search(
        r'<script id="health-data"[^>]*>(.*?)</script>', html, re.DOTALL
    ).group(1)
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


class ReviewedCandidateScopeTests(unittest.TestCase):
    def mutate_attribution(self, summary, component, day, mutation):
        entries = summary["measurement_epoch_evidence"]["observation_attributions"]
        item = next(entry for entry in entries if entry["component"] == component and entry["date"] == day)
        if mutation == "missing":
            entries.remove(item)
        elif mutation == "conflict":
            entries.append({**item, "serial_number": "conflicting-synthetic-device"})
        else:
            item["serial_number"] = "other-synthetic-device"

    def analyze(self, summary, count):
        return garmin_intelligence.analyze_health_patterns(
            summary, requested_start="2026-07-01", requested_end=_dates("2026-07-01", count)[-1]
        )

    def timestamp_summary(self):
        summary = _known_epoch_summary(count=14)
        summary["sleep"] = [
            {"date": day, "sleep_start": f"{day}T00:00:00+08:00", "sleep_end": f"{day}T08:00:00+08:00"}
            for day in _dates("2026-07-01", 14)[-7:]
        ]
        return summary

    def test_sleep_ignores_attribution_before_actual_trailing_window(self):
        for mutation in ("missing", "cross", "conflict"):
            with self.subTest(mutation=mutation):
                summary = _known_epoch_summary(count=28)
                self.mutate_attribution(summary, "sleep", "2026-07-01", mutation)
                sleep = self.analyze(summary, 28)["sleep_regularity"]
                self.assertEqual(sleep["duration_status"], "eligible")
                self.assertEqual(sleep["duration_observed_nights"], 14)

    def test_lag_ignores_unpaired_final_exposure_and_initial_outcome(self):
        for component, day in (("training_load_series", "2026-07-29"), ("hrv", "2026-07-01")):
            for mutation in ("missing", "cross", "conflict"):
                with self.subTest(component=component, mutation=mutation):
                    summary = _known_epoch_summary(count=29)
                    summary["component_status"]["training_load_series"]["zero_semantics"] = "explicit_daily_zero"
                    self.mutate_attribution(summary, component, day, mutation)
                    association = self.analyze(summary, 29)["lagged_associations"]["hrv"]
                    self.assertEqual(association["status"], "eligible")
                    self.assertEqual(association["pair_count"], 28)
                    self.assertIsNotNone(association["spearman_rho"])

    def test_actual_sleep_and_lag_participants_still_require_unambiguous_attribution(self):
        for mutation, expected in (("missing", "device_attribution_unknown"), ("conflict", "device_attribution_conflict"), ("cross", "cross_epoch")):
            with self.subTest(mutation=mutation):
                summary = _known_epoch_summary(count=28)
                self.mutate_attribution(summary, "sleep", "2026-07-28", mutation)
                sleep = self.analyze(summary, 28)["sleep_regularity"]
                self.assertEqual(sleep["epoch_status"], expected)
                self.assertIsNone(sleep["duration_sd_hours"])
                for component, day in (("training_load_series", "2026-07-01"), ("hrv", "2026-07-02")):
                    summary = _known_epoch_summary(count=29)
                    summary["component_status"]["training_load_series"]["zero_semantics"] = "explicit_daily_zero"
                    self.mutate_attribution(summary, component, day, mutation)
                    association = self.analyze(summary, 29)["lagged_associations"]["hrv"]
                    self.assertEqual(association["epoch_status"], expected)
                    self.assertIsNone(association["spearman_rho"])

    def test_timestamp_duration_counts_follow_selected_source_under_both_epoch_gates(self):
        for comparable in (True, None):
            for sparse_direct in (False, True):
                with self.subTest(comparable=comparable, sparse_direct=sparse_direct):
                    rows = self.timestamp_summary()["sleep"]
                    if sparse_direct:
                        for row in rows[:3]:
                            row["sleep_time_seconds"] = 21600
                    result = garmin_patterns.sleep_regularity_snapshot(
                        rows + rows, _dates("2026-07-01", 14), comparable,
                        "single_known_epoch" if comparable else "device_attribution_unknown",
                    )
                    self.assertEqual(result["duration_observed_nights"], 7)
                    self.assertEqual(result["duration_source"], "timestamp_interval_seconds")
                    if comparable:
                        self.assertEqual(result["duration_valid_nights"], 7)
                        self.assertEqual(result["duration_status"], "eligible")
                    else:
                        self.assertIsNone(result["duration_sd_hours"])

    def test_duration_candidates_do_not_union_incompatible_sources(self):
        rows = self.timestamp_summary()["sleep"][:4]
        rows += [{"date": day, "sleep_time_seconds": 21600} for day in _dates("2026-07-01", 3)]
        result = garmin_patterns.sleep_regularity_snapshot(rows, _dates("2026-07-01", 14), True, "single_known_epoch")
        self.assertEqual(result["duration_observed_nights"], 3)
        self.assertEqual(result["duration_status"], "insufficient_valid_nights")
        self.assertIsNone(result["duration_sd_hours"])

    @unittest.skipUnless(shutil.which("node"), "Node required for existing DOM contract")
    def test_timestamp_duration_samples_reach_dashboard_eligibility_table(self):
        for attributed in (True, False):
            with self.subTest(attributed=attributed):
                summary = self.timestamp_summary()
                if not attributed:
                    summary["measurement_epoch_evidence"]["observation_attributions"] = []
                payload = garmin_chart.build_dashboard_payload(
                    summary, days=14, requested_source="local", effective_source="local",
                    selected_components=("sleep",), live_fallback_attempted=False,
                    requested_start="2026-07-01", requested_end="2026-07-14",
                    generated_at="2026-07-14T12:00:00+08:00",
                )
                html = garmin_chart.render_report(payload)
                embedded = _embedded_payload(html)
                entry = next(item for item in embedded["patterns"]["eligibility"] if item["id"] == "sleep_duration_regularity")
                self.assertEqual(entry["observed_days"], 7)
                runtime = re.findall(r"<script(?: [^>]*)?>(.*?)</script>", html, re.DOTALL)[-1]
                renderer = "function renderAnalysisReadiness" + runtime.split("function renderAnalysisReadiness", 1)[1].split("function renderList", 1)[0]
                harness = """
class Node { constructor(){this.children=[];this.textContent='';} append(...nodes){this.children.push(...nodes);} replaceChildren(...nodes){this.children=nodes;} setAttribute(){} }
const body=new Node(); const document={createElement(){return new Node();}};
function byId(){return body;} function text(){}
""" + renderer + "\nrenderAnalysisReadiness(" + json.dumps(embedded) + ");\nconsole.log(JSON.stringify(body.children.map(row=>row.children.map(cell=>cell.textContent))));"
                completed = subprocess.run([shutil.which("node"), "-"], input=harness, capture_output=True, text=True, encoding="utf-8", check=True)
                row = next(item for item in json.loads(completed.stdout) if item[0] == "睡眠时长离散度")
                self.assertEqual(row[2], "7/7")
                self.assertEqual(row[1], "可计算" if attributed else "时期未知")


class HealthPatternIntegrationTests(unittest.TestCase):
    def test_missing_attribution_preserves_source_sample_counts_without_comparison(self):
        summary = _known_epoch_summary(count=7)
        summary["measurement_epoch_evidence"]["observation_attributions"] = []
        result = garmin_intelligence.analyze_health_patterns(
            summary, requested_start="2026-07-01", requested_end="2026-07-07"
        )
        sleep = result["sleep_regularity"]
        self.assertEqual(sleep["duration_observed_nights"], 7)
        self.assertEqual(sleep["status"], "insufficient_window")
        self.assertIsNone(sleep["duration_sd_hours"])
        entry = next(item for item in result["eligibility"] if item["id"] == "sleep_duration_regularity")
        self.assertEqual(entry["observed_days"], 7)
        self.assertEqual(result["trends"]["rhr"]["epoch_status"], "device_attribution_unknown")
        self.assertIn("归属未知", result["eligibility"][0]["reason"])

    def test_lag_comparison_requires_both_component_attributions(self):
        summary = _known_epoch_summary(count=29)
        summary["component_status"]["training_load_series"]["zero_semantics"] = "explicit_daily_zero"
        evidence = summary["measurement_epoch_evidence"]
        evidence["observation_attributions"] = [
            item for item in evidence["observation_attributions"] if item["component"] != "training_load_series"
        ]
        result = garmin_intelligence.analyze_health_patterns(
            summary, requested_start="2026-07-01", requested_end="2026-07-29"
        )
        for item in result["lagged_associations"].values():
            self.assertEqual(item["epoch_status"], "device_attribution_unknown")
            self.assertIsNone(item["spearman_rho"])

    def test_patterns_use_exact_scope_and_fail_closed_for_load_semantics(self):
        summary = _known_epoch_summary()
        summary["sleep"].append(
            {
                "date": "2026-06-30",
                "sleep_time_seconds": 999999,
                "avg_respiration": 999,
                "avg_spo2": 999,
            }
        )

        result = garmin_intelligence.analyze_health_patterns(
            summary,
            requested_start="2026-07-01",
            requested_end="2026-07-28",
        )

        self.assertEqual(result["analysis_type"], "descriptive_health_patterns")
        self.assertEqual(result["requested_range"]["days"], 28)
        self.assertEqual(result["trends"]["rhr"]["status"], "eligible")
        self.assertEqual(result["trends"]["hrv"]["status"], "eligible")
        self.assertEqual(
            result["trends"]["sleep_respiration"]["status"], "eligible"
        )
        self.assertEqual(result["sleep_regularity"]["status"], "partial_available")
        self.assertEqual(result["sleep_regularity"]["duration_status"], "eligible")
        self.assertEqual(
            result["sleep_regularity"]["timing_status"], "source_not_supported"
        )
        for association in result["lagged_associations"].values():
            self.assertEqual(association["status"], "load_coverage_unknown")
            self.assertIsNone(association["spearman_rho"])
        self.assertNotIn("2026-06-30", result["continuity"]["sleep_duration"]["observed_dates"])
        json.dumps(result, allow_nan=False)

    def test_short_scope_is_not_expanded_to_manufacture_a_baseline(self):
        summary = _known_epoch_summary(count=7)
        result = garmin_intelligence.analyze_health_patterns(
            summary,
            requested_start="2026-07-01",
            requested_end="2026-07-07",
        )

        self.assertEqual(result["requested_range"]["days"], 7)
        self.assertEqual(
            result["trends"]["rhr"]["status"],
            "historical_baseline_insufficient",
        )
        self.assertEqual(result["sleep_regularity"]["status"], "insufficient_window")

    def test_explicit_daily_zero_semantics_can_unlock_exact_lag_pairs(self):
        summary = _known_epoch_summary(count=29)
        days = _dates("2026-07-01", 29)
        exposures = [float(index + 1) for index in range(29)]
        summary["training_load_series"] = [
            {"date": day, "acute_load": value}
            for day, value in zip(days, exposures, strict=True)
        ]
        summary["heart_rate"] = [
            {"date": day, "resting_hr": exposure}
            for day, exposure in zip(days[1:], exposures[:-1], strict=True)
        ]
        summary["hrv"] = [
            {"date": day, "last_night_avg": exposure}
            for day, exposure in zip(days[1:], exposures[:-1], strict=True)
        ]
        summary["sleep"] = [
            {"date": day, "sleep_time_seconds": exposure * 60}
            for day, exposure in zip(days[1:], exposures[:-1], strict=True)
        ]
        summary["component_status"]["training_load_series"].update(
            {
                "coverage_semantics": "daily_zero_observable",
                "zero_semantics": "explicit_daily_zero",
            }
        )

        result = garmin_intelligence.analyze_health_patterns(
            summary,
            requested_start=days[0],
            requested_end=days[-1],
        )

        for association in result["lagged_associations"].values():
            self.assertEqual(association["status"], "eligible")
            self.assertEqual(association["pair_count"], 28)
            self.assertAlmostEqual(association["spearman_rho"], 1.0)
            self.assertFalse(association["causal_interpretation"])
        association_rows = [
            item
            for item in result["eligibility"]
            if item["id"].startswith("load_to_next_day_")
        ]
        self.assertTrue(
            all("相关不代表因果" in item["reason"] for item in association_rows)
        )

    def test_association_is_not_requested_when_outcomes_are_out_of_scope(self):
        summary = _known_epoch_summary(count=29)
        summary.pop("heart_rate")
        summary.pop("hrv")
        summary.pop("sleep")
        summary["component_status"] = {
            "training_load_series": {
                "status": "complete",
                "coverage_semantics": "daily_zero_observable",
                "zero_semantics": "explicit_daily_zero",
            }
        }

        result = garmin_intelligence.analyze_health_patterns(
            summary,
            requested_start="2026-07-01",
            requested_end="2026-07-29",
        )

        self.assertTrue(
            all(
                association["status"] == "not_requested"
                for association in result["lagged_associations"].values()
            )
        )

    def test_composed_lag_and_timing_conflicts_fail_closed(self):
        summary = _known_epoch_summary(count=30)
        summary["component_status"]["training_load_series"].update(
            {
                "coverage_semantics": "daily_zero_observable",
                "zero_semantics": "explicit_daily_zero",
            }
        )
        summary["training_load_series"].append(
            {"date": "2026-07-01", "acute_load": 999}
        )
        for index, record in enumerate(summary["sleep"][-8:]):
            day = date.fromisoformat(record["date"])
            record["sleep_start"] = f"{day.isoformat()}T23:00:00+08:00"
            record["sleep_end"] = (
                f"{(day + timedelta(days=1)).isoformat()}T07:00:00+08:00"
            )
        summary["sleep"].append(
            {
                "date": summary["sleep"][-8]["date"],
                "sleep_time_seconds": summary["sleep"][-8]["sleep_time_seconds"],
                "sleep_start": (
                    f"{summary['sleep'][-8]['date']}T22:00:00+08:00"
                ),
                "sleep_end": (
                    f"{(date.fromisoformat(summary['sleep'][-8]['date']) + timedelta(days=1)).isoformat()}T06:00:00+08:00"
                ),
            }
        )

        result = garmin_intelligence.analyze_health_patterns(
            summary,
            requested_start="2026-07-01",
            requested_end="2026-07-30",
        )

        self.assertTrue(
            all(
                association["status"] == "duplicate_conflict"
                for association in result["lagged_associations"].values()
            )
        )
        self.assertEqual(
            result["sleep_regularity"]["timing_status"], "duplicate_conflict"
        )
        self.assertIsNone(
            result["sleep_regularity"]["midpoint_circular_sd_hours"]
        )

    def test_dashboard_marks_unrequested_load_and_strips_forged_derived_values(self):
        summary = _known_epoch_summary()
        payload = garmin_chart.build_dashboard_payload(
            summary,
            days=28,
            requested_source="local",
            effective_source="local",
            selected_components=garmin_chart.DASHBOARD_DEFAULT_COMPONENTS,
            live_fallback_attempted=False,
            requested_start="2026-07-01",
            requested_end="2026-07-28",
            generated_at="2026-08-09T12:00:00+08:00",
        )

        self.assertIn("patterns", payload)
        for association in payload["patterns"]["lagged_associations"].values():
            self.assertEqual(association["status"], "not_requested")
            self.assertIsNone(association["spearman_rho"])

        payload["patterns"]["trends"]["rhr"].update(
            {"status": "epoch_unknown", "robust_z": 999, "absolute_delta": 999}
        )
        payload["patterns"]["sleep_regularity"].update(
            {
                "timing_status": "source_not_supported",
                "midpoint_circular_sd_hours": 999,
            }
        )
        payload["patterns"]["lagged_associations"]["rhr"].update(
            {"status": "load_coverage_unknown", "spearman_rho": 1.0}
        )

        embedded = _embedded_payload(garmin_chart.render_report(payload))
        self.assertIsNone(embedded["patterns"]["trends"]["rhr"]["robust_z"])
        self.assertIsNone(
            embedded["patterns"]["trends"]["rhr"]["absolute_delta"]
        )
        self.assertIsNone(
            embedded["patterns"]["sleep_regularity"][
                "midpoint_circular_sd_hours"
            ]
        )
        self.assertIsNone(
            embedded["patterns"]["lagged_associations"]["rhr"]["spearman_rho"]
        )


if __name__ == "__main__":
    unittest.main()
