from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_PATH = Path(__file__).with_name("engine.py")
SKILL_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_PATH = SKILL_ROOT / "generate_final_report.py"
VALIDATOR_PATH = SKILL_ROOT / "scripts" / "validate_agent_audit.py"
SPEC = importlib.util.spec_from_file_location("collaboration_audit_engine", ENGINE_PATH)
assert SPEC and SPEC.loader
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

VALIDATOR_SPEC = importlib.util.spec_from_file_location("collaboration_audit_validator", VALIDATOR_PATH)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(validator)


class LoadRecordsTests(unittest.TestCase):
    def test_partial_input_is_reported_instead_of_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "events.jsonl").write_text(
                '{"event_type":"tool_call","root_task_id":"r1"}\n{not-json}\n',
                encoding="utf-8",
            )
            (root / "broken.json").write_text("{not-json}", encoding="utf-8")

            records, coverage = engine.load_records(root)

        self.assertEqual(len(records), 1)
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["skipped_file_count"], 1)
        self.assertEqual(coverage["skipped_record_count"], 1)
        self.assertEqual(len(coverage["issues"]), 2)

    def test_strict_cli_returns_two_for_partial_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "events.jsonl"
            source.write_text(
                '{"event_type":"tool_call","root_task_id":"r1"}\n{not-json}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ENGINE_PATH), "--input", str(source), "--strict"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report["coverage"]["status"], "partial")

    def test_top_level_report_entrypoint_uses_explicit_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "events.json"
            source.write_text(
                json.dumps([{"event_type": "tool_call", "root_task_id": "r1", "status": "ok"}]),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(WRAPPER_PATH), "--input", str(source)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema_version"], 2)


class AggregateTests(unittest.TestCase):
    def test_missing_duration_is_excluded_and_p95_uses_nearest_rank(self) -> None:
        records = [
            {"component": "runner", "status": "ok", "duration_sec": value}
            for value in range(1, 22)
        ]
        records.append({"component": "runner", "status": "ok"})

        report = engine.aggregate(records)
        component = report["components"][0]

        self.assertEqual(component["count"], 22)
        self.assertEqual(component["duration_observation_count"], 21)
        self.assertEqual(component["duration_p95_sec"], 20.0)
        self.assertEqual(component["duration_mean_sec"], 11.0)

    def test_operational_metrics_are_reproducible_from_event_fields(self) -> None:
        records = [
            {
                "timestamp": "2026-07-19T00:00:00Z",
                "event_type": "wait_agent",
                "root_task_id": "r1",
                "actor_id": "root",
                "component": "collaboration",
                "status": "timeout",
                "state_version": "s1",
                "duration_ms": 1000,
                "local_work_available": True,
            },
            {
                "timestamp": "2026-07-19T00:00:01Z",
                "event_type": "wait_agent",
                "root_task_id": "r1",
                "actor_id": "root",
                "component": "collaboration",
                "status": "timeout",
                "state_version": "s1",
                "duration_ms": 1000,
                "local_work_available": True,
            },
            {
                "timestamp": "2026-07-19T00:00:02Z",
                "event_type": "wait_agent",
                "root_task_id": "r1",
                "actor_id": "root",
                "component": "collaboration",
                "status": "completed",
                "state_version": "s2",
                "duration_ms": 100,
            },
            {
                "event_type": "skill_load",
                "root_task_id": "r1",
                "actor_id": "root",
                "context_epoch": "c1",
                "skill_name": "audit",
                "skill_sha256": "abc",
            },
            {
                "event_type": "skill_load",
                "root_task_id": "r1",
                "actor_id": "root",
                "context_epoch": "c1",
                "skill_name": "audit",
                "skill_sha256": "abc",
            },
            {
                "event_type": "skill_load",
                "root_task_id": "r1",
                "actor_id": "root",
                "context_epoch": "c2",
                "skill_name": "audit",
                "skill_sha256": "abc",
            },
            {
                "event_type": "retry",
                "root_task_id": "r1",
                "component": "connector",
                "operation": "read",
                "error_category": "transport",
                "error_signature": "connector_eof",
                "hypothesis_delta": "fresh connection",
            },
            {
                "event_type": "retry",
                "root_task_id": "r1",
                "component": "connector",
                "operation": "read",
                "error_category": "transport",
            },
            {
                "event_type": "retry",
                "root_task_id": "r1",
                "component": "connector",
                "operation": "write",
                "error_category": "transport",
                "error_signature": "connector_eof",
                "hypothesis_delta": "query remote status",
                "side_effect_state": "unknown",
                "fallback": "status_query",
            },
            {
                "event_type": "tool_call",
                "root_task_id": "r1",
                "actor_id": "root",
                "actor_type": "root",
                "component": "runner",
                "input_tokens": 90,
                "output_tokens": 10,
            },
            {
                "event_type": "tool_call",
                "root_task_id": "r1",
                "actor_id": "child-1",
                "actor_type": "subagent",
                "parent_actor_id": "root",
                "component": "runner",
                "input_tokens": 40,
                "output_tokens": 10,
            },
            {
                "event_type": "subagent_spawn",
                "root_task_id": "r1",
                "actor_id": "root",
                "actor_type": "root",
                "fork_turns": "none",
                "evidence_pointers": [{"path": "events.jsonl", "lines": "1-20"}],
                "max_turns": 3,
                "halt_condition": "evidence classified",
                "output_schema": "collaboration_subagent_v1",
            },
            {
                "event_type": "approval_request",
                "root_task_id": "r1",
                "task_mode": "read_only",
            },
            {
                "event_type": "write_commit",
                "root_task_id": "r1",
                "action": "publish",
                "target": "remote-a",
                "write_scope_sha256": "scope-a",
            },
            {
                "event_type": "write_commit",
                "root_task_id": "r1",
                "action": "persist",
                "target": "store-a",
                "authorization_id": "auth-1",
                "write_scope_sha256": "scope-b",
                "authorization_scope_sha256": "scope-b",
            },
            {"event_type": "context_compacted", "root_task_id": "r1"},
        ]

        report = engine.aggregate(records)
        metrics = report["operational_metrics"]

        self.assertEqual(metrics["wait"]["wait_call_count"], 3)
        self.assertEqual(metrics["wait"]["redundant_wait_count"], 1)
        self.assertEqual(metrics["wait"]["max_same_state_timeout_streak"], 2)
        self.assertEqual(metrics["wait"]["wait_with_local_work_count"], 2)
        self.assertEqual(metrics["skill_load"]["duplicate_load_count"], 1)
        self.assertAlmostEqual(metrics["skill_load"]["duplicate_load_rate"], 1 / 3, places=4)
        self.assertEqual(metrics["retry"]["blind_retry_count"], 1)
        self.assertAlmostEqual(metrics["retry"]["blind_retry_rate"], 1 / 3, places=4)
        self.assertEqual(metrics["retry"]["ambiguous_write_retry_count"], 1)
        self.assertAlmostEqual(metrics["subagent"]["child_token_share"], 1 / 3, places=4)
        self.assertTrue(math.isclose(metrics["subagent"]["child_to_root_token_ratio"], 0.5))
        self.assertEqual(metrics["subagent"]["full_history_fork_count"], 0)
        self.assertEqual(metrics["subagent"]["structured_packet_rate"], 1.0)
        self.assertEqual(metrics["authorization"]["unmatched_write_count"], 1)
        self.assertEqual(metrics["authorization"]["readonly_approval_rounds"], 1)
        self.assertEqual(metrics["context"]["compactions_per_10_root_tasks"], 10.0)

    def test_generated_report_passes_schema_two_validator(self) -> None:
        report = engine.aggregate([{"event_type": "tool_call", "root_task_id": "r1"}])
        self.assertEqual(validator.validate_report_payload(report), [])

        del report["operational_metrics"]["retry"]
        errors = validator.validate_report_payload(report)
        self.assertIn("operational_metrics.retry is missing", errors)


if __name__ == "__main__":
    unittest.main()
