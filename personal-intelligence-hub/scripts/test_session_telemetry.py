import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hub_utils import atomic_dump_json
from run_contract import (
    RunContractError,
    _reserve_execution_budget,
    create_run,
    load_manifest,
    record_execution_telemetry,
)
from session_telemetry import summarize_sessions  # pyright: ignore[reportMissingImports]


class SessionTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.skill = self.root / "SKILL.md"
        self.skill.write_text("skill", encoding="utf-8")
        skill_sha = hashlib.sha256(b"skill").hexdigest()
        (self.root / "resource-manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "skill": self.root.name,
                    "skill_md": "SKILL.md",
                    "skill_md_sha256": skill_sha,
                    "top_level_file_hashes": [],
                    "declared_local_dependencies": [],
                    "missing_declared_dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        self.now = datetime(2026, 8, 31, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.manifest_path, self.manifest = create_run(
            runtime_dir=self.root / "runtime",
            skill_path=self.skill,
            report_date="2026-08-31",
            timezone_name="Asia/Shanghai",
            now=self.now,
            run_id="telemetry-run",
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_summarizes_usage_without_copying_message_content(self):
        session = self.root / "session.jsonl"
        records = [
            {
                "timestamp": "2026-08-31T01:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "private body must not be copied",
                    "usage": {
                        "input": 10,
                        "output": 5,
                        "reasoning": 3,
                        "cacheRead": 2,
                        "cacheWrite": 1,
                        "totalTokens": 21,
                        "cost": {"total": 0.25},
                    },
                },
            },
            {
                "timestamp": "2026-08-31T01:00:05Z",
                "message": {
                    "role": "toolResult",
                    "content": "secret-looking output",
                    "isError": True,
                },
            },
        ]
        session.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

        summary = summarize_sessions([session])

        self.assertEqual(summary["usage"]["total_tokens"], 21)
        self.assertEqual(summary["usage"]["budget_tokens"], 18)
        self.assertEqual(summary["usage"]["cost_usd"], 0.25)
        self.assertEqual(summary["usage"]["tool_errors"], 1)
        self.assertEqual(summary["duration_seconds"], 5.0)
        serialized = json.dumps(summary)
        self.assertNotIn("private body", serialized)
        self.assertNotIn("secret-looking", serialized)

    def test_failed_execution_telemetry_is_hash_bound_and_immutable(self):
        run_dir = Path(self.manifest["run_dir"])
        artifact = run_dir / "execution_telemetry_semantic_invocation-1.json"
        usage = {
            "input_tokens": 10,
            "output_tokens": 5,
            "reasoning_tokens": 3,
            "cache_read_tokens": 2,
            "cache_write_tokens": 1,
            "total_tokens": 21,
            "cost_usd": 0.25,
            "assistant_messages": 1,
            "tool_results": 1,
            "tool_errors": 1,
        }
        payload = {
            "contract_version": "pih-execution-telemetry/1.0",
            "run_id": self.manifest["run_id"],
            "stage": "semantic_review",
            "invocation_id": "invocation-1",
            "status": "failed",
            "usage": usage,
            "duration_seconds": 5.0,
            "sources": [{"path": "failed.jsonl", "sha256": "3" * 64}],
        }
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        manifest = load_manifest(self.manifest_path)
        _reserve_execution_budget(
            manifest,
            [{
                "stage": "semantic_review",
                "invocation_id": "invocation-1",
                "tokens": 100,
                "cost_usd": 1.0,
            }],
            request_sha256="4" * 64,
            current=self.now,
        )
        atomic_dump_json(self.manifest_path, manifest)

        record_execution_telemetry(
            self.manifest_path,
            artifact,
            now=self.now,
        )
        manifest = load_manifest(self.manifest_path)
        registered = manifest["telemetry"]["executions"]
        record = registered["semantic_review:invocation-1"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["usage"]["total_tokens"], 21)
        self.assertEqual(record["usage"]["budget_tokens"], 18)
        self.assertEqual(record["artifact_sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
        self.assertEqual(
            manifest["telemetry"]["summary"]["budget_status"],
            "within_budget",
        )
        self.assertEqual(
            manifest["telemetry"]["summary"]["failed_invocations"],
            1,
        )

        record_execution_telemetry(
            self.manifest_path,
            artifact,
            now=self.now,
        )
        payload["usage"]["total_tokens"] = 22
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(RunContractError, "immutable"):
            record_execution_telemetry(
                self.manifest_path,
                artifact,
                now=self.now,
            )

        payload["invocation_id"] = "invocation-2"
        payload["usage"]["total_tokens"] = 260000
        payload["usage"]["cost_usd"] = 3.5
        payload["sources"] = [{"path": "overrun.jsonl", "sha256": "5" * 64}]
        manifest = load_manifest(self.manifest_path)
        _reserve_execution_budget(
            manifest,
            [{
                "stage": "semantic_review",
                "invocation_id": "invocation-2",
                "tokens": 100,
                "cost_usd": 0.1,
            }],
            request_sha256="6" * 64,
            current=self.now,
        )
        atomic_dump_json(self.manifest_path, manifest)
        second = run_dir / "execution_telemetry_semantic_invocation-2.json"
        second.write_text(json.dumps(payload), encoding="utf-8")
        record_execution_telemetry(self.manifest_path, second, now=self.now)
        summary = load_manifest(self.manifest_path)["telemetry"]["summary"]
        self.assertEqual(summary["budget_status"], "exceeded")
        self.assertEqual(summary["exceeded_dimensions"], ["tokens", "cost_usd"])
        self.assertEqual(summary["invocation_count"], 2)


if __name__ == "__main__":
    unittest.main()
