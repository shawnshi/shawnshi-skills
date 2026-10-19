from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from engine import aggregate, aggregate_path
from token_analysis import TokenAnalysis

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_agent_audit import validate_report_payload


def usage(identity="a", **fields):
    return {"event_type": "token_usage", "event_id": identity, "session_id": "s1",
            "root_task_id": "r1", "actor_id": "root", "timestamp": "2026-10-09T16:30:00Z",
            "provider": "p1", "model": "model-a", "work_type": "coding",
            "input_tokens": 100, "output_tokens": 20, **fields}


def ledger(records, **options):
    state = TokenAnalysis(**options)
    for record in records:
        state.update(record)
    return state.finalize({"status": "complete"})


class TokenAnalysisTests(unittest.TestCase):
    def test_local_date_hour_and_all_dimensions_reconcile(self):
        report = ledger([usage(), usage("b", timestamp="2026-10-10T02:00:00Z", model="model-b",
                                       work_type="research", input_tokens=50, output_tokens=10)], bucket_hours=6)
        self.assertEqual(report["status"], "complete")
        values = report["reported"]
        self.assertEqual(values["totals"]["total_tokens"], 180)
        self.assertEqual(values["by_date"][0]["date"], "2026-10-10")
        self.assertEqual(values["by_time_bucket"][0]["start"], "2026-10-10T00:00:00+08:00")
        self.assertEqual(values["by_time_period"][1]["start_hour"], "06:00")
        for dimension, rows in values.items():
            if dimension != "totals":
                self.assertEqual(sum(row["total_tokens"] for row in rows), 180, dimension)
                self.assertEqual(sum(row["usage_count"] for row in rows), 2, dimension)
        self.assertEqual(values["by_model"][0]["share"], 0.666667)

    def test_same_hour_across_dates_and_end_exclusive(self):
        records = [usage("before", timestamp="2026-10-09T15:59:59Z"), usage(),
                   usage("b", timestamp="2026-10-10T16:30:00Z"),
                   usage("end", timestamp="2026-10-11T16:00:00Z")]
        report = ledger(records, start="2026-10-10", end="2026-10-12")
        self.assertEqual(report["reported"]["totals"]["usage_count"], 2)
        self.assertEqual(len(report["reported"]["by_time_period"]), 1)
        self.assertEqual(len(report["reported"]["by_date"]), 2)
        self.assertEqual(report["coverage"]["excluded_by_window_or_missing_time_count"], 2)
        exact = ledger([usage()], start="2026-10-10T00:30:00+08:00", end="2026-10-10T00:31:00+08:00")
        self.assertEqual(exact["reported"]["totals"]["total_tokens"], 120)

    def test_duplicates_are_scoped_and_conflicts_fail_closed(self):
        first = usage()
        report = ledger([first, dict(first), usage(actor_id="child"), usage(session_id="s2")])
        self.assertEqual(report["reported"]["totals"]["total_tokens"], 360)
        self.assertEqual(report["coverage"]["duplicate_delivery_count"], 1)
        report = ledger([first, usage(output_tokens=21), first])
        self.assertEqual(report["coverage"]["conflicting_identity_count"], 1)
        self.assertIsNone(report["reported"]["totals"]["total_tokens"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(ledger([usage(), usage(timestamp="2026-10-10T00:30:00+08:00")])["coverage"]["duplicate_delivery_count"], 1)
        invalid = ledger([usage(input_tokens=-1), usage()])
        self.assertEqual(invalid["coverage"]["invalid_identity_count"], 1)
        self.assertEqual(invalid["coverage"]["conflicting_identity_count"], 0)
        self.assertEqual(invalid["coverage"]["unique_usage_identity_count"], 1)
        self.assertIsNone(invalid["reported"]["totals"]["total_tokens"])

    def test_noncanonical_events_do_not_double_count_and_estimates_are_separate(self):
        report = ledger([usage(), usage("e", measurement_kind="estimated", input_tokens=80),
                         usage("context", event_type="model_input_usage"),
                         usage("summary", event_type="subagent_result"),
                         usage("load", event_type="skill_load")])
        self.assertEqual(report["reported"]["totals"]["total_tokens"], 120)
        self.assertEqual(report["estimated"]["totals"]["total_tokens"], 100)
        self.assertEqual(report["coverage"]["token_usage_event_count"], 2)

    def test_cache_and_reasoning_are_subsets_not_extra_tokens(self):
        report = ledger([usage(cached_input_tokens=40, cache_creation_input_tokens=10, reasoning_tokens=5)])
        self.assertEqual(report["reported"]["totals"]["total_tokens"], 120)
        self.assertEqual(report["reported"]["totals"]["cached_input_tokens"], 40)
        partial = ledger([usage(cached_input_tokens=40), usage("b")])["reported"]["totals"]
        self.assertIsNone(partial["cached_input_tokens"])
        self.assertEqual(partial["cached_input_tokens_observed_sum"], 40)
        self.assertEqual(partial["cached_input_tokens_coverage_count"], 1)

    def test_bad_counts_identity_cumulative_and_subsets_are_rejected(self):
        for fields in ({"input_tokens": None}, {"input_tokens": -1}, {"output_tokens": True},
                       {"input_tokens": 1.5}, {"usage_mode": "cumulative"}, {"event_id": ""},
                       {"actor_id": ""}, {"cached_input_tokens": 101}, {"reasoning_tokens": 21},
                       {"cached_input_tokens": 60, "cache_creation_input_tokens": 50},
                       {"measurement_kind": "bogus"}):
            with self.subTest(fields=fields):
                result = ledger([usage(**fields)])
                self.assertEqual(result["status"], "partial")
                self.assertIsNone(result["reported"]["totals"]["total_tokens"])

    def test_unknown_dimensions_are_visible_and_missing_time_is_not_guessed(self):
        result = ledger([usage(model=None, work_type=None, timestamp="2026-10-10T01:00:00")])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["reported"]["by_date"][0]["date"], "unknown")
        self.assertEqual(result["reported"]["by_model"][0]["model"], "unknown")
        self.assertEqual(result["reported"]["by_work_type"][0]["work_type"], "unknown")
        self.assertEqual(result["reported"]["totals"]["total_tokens"], 120)
        window = ledger([usage(timestamp=None)], start="2026-10-10")
        self.assertIsNone(window["reported"]["totals"]["total_tokens"])
        self.assertEqual(window["coverage"]["missing_timestamp_count"], 1)

    def test_empty_zero_and_invalid_configuration(self):
        self.assertEqual(ledger([])["status"], "unavailable")
        self.assertIsNone(ledger([])["reported"]["totals"]["total_tokens"])
        zero = ledger([usage(input_tokens=0, output_tokens=0)])
        self.assertEqual(zero["reported"]["totals"]["total_tokens"], 0)
        self.assertIsNone(zero["reported"]["by_model"][0]["share"])
        self.assertEqual(ledger([usage()], start="2026-10-11")["status"], "empty_window")
        for options in ({"bucket_hours": 5}, {"timezone_offset": "Asia/Shanghai"},
                        {"timezone_offset": "+24:00"}, {"timezone_offset": "+08:60"},
                        {"start": "bad"}, {"start": "2026-10-10T00:00:00"},
                        {"start": "2026-10-12", "end": "2026-10-10"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                TokenAnalysis(**options)

    def test_stream_list_validator_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "events.jsonl"
            records = [usage(), usage("b", model="model-b", work_type="review")]
            source.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            streamed = aggregate_path(source)
            listed = aggregate(records, coverage=streamed["coverage"])
            self.assertEqual(streamed, listed)
            self.assertEqual(validate_report_payload(streamed), [])
            changed = deepcopy(streamed)
            changed["token_analysis"]["reported"]["by_date"][0]["total_tokens"] += 1
            self.assertTrue(any("reconcile" in error for error in validate_report_payload(changed)))
            command = [sys.executable, str(ROOT / "generate_final_report.py"), "--input", str(source),
                       "--strict", "--token-start", "2026-10-10", "--token-end", "2026-10-11"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["token_analysis"]["reported"]["totals"]["total_tokens"], 240)
            source.write_text(json.dumps(usage(work_type=None)), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 2, result.stderr)
            result = subprocess.run(command + ["--token-timezone", "invalid"], capture_output=True,
                                    text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertIn("timezone", result.stderr)

    def test_codex_model_cache_session_and_gap_end_to_end(self):
        def raw(ts, kind, payload):
            return {"timestamp": ts, "type": kind, "payload": payload}
        records = [
            raw("2026-10-09T16:00:00Z", "session_meta", {"id": "private-session", "model_provider": "p1"}),
            raw("2026-10-09T16:00:01Z", "turn_context", {"turn_id": "r1", "model": "model-a"}),
            raw("2026-10-09T16:00:02Z", "event_msg", {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 40},
                "last_token_usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 40}}}),
            raw("2026-10-09T16:00:03Z", "turn_context", {"turn_id": "r2", "model": "model-b"}),
            raw("2026-10-09T16:00:04Z", "event_msg", {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 150, "output_tokens": 30, "cached_input_tokens": 50}}}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source, target, summary = [Path(directory) / p for p in ("raw.jsonl", "events.jsonl", "summary.json")]
            source.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "standardize_codex_rollout.py"),
                       "--input", str(source), "--output", str(target), "--summary", str(summary),
                       "--start", "2026-10-09T16:00:00Z", "--work-type", "research"]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("private-session", target.read_text(encoding="utf-8"))
            report = aggregate_path(target)
            tokens = report["token_analysis"]
            self.assertEqual(tokens["status"], "complete")
            self.assertEqual(tokens["reported"]["totals"]["total_tokens"], 180)
            self.assertEqual(tokens["reported"]["totals"]["cached_input_tokens"], 50)
            self.assertEqual([row["model"] for row in tokens["reported"]["by_model"]], ["model-a", "model-b"])
            self.assertEqual(validate_report_payload(report), [])
            target.unlink()
            summary.unlink()
            records = records[:2] + [raw("2026-10-09T16:00:02Z", "event_msg", {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 100, "output_tokens": 20}}})]
            source.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            gap = aggregate_path(target)["token_analysis"]
            self.assertEqual(gap["status"], "partial")
            self.assertIsNone(gap["reported"]["totals"]["total_tokens"])


if __name__ == "__main__":
    unittest.main()
