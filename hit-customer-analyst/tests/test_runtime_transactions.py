from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tests.common import load_json, run_python, runtime_tx as tx
from tests.fixture_builder import build_pending_strategy_workspace


def _body(text: str) -> str:
    lines = text.splitlines()
    end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    return "\n".join(lines[end + 1 :]).strip()


class RuntimeTransactionTests(unittest.TestCase):
    def initialize(self, root: Path) -> dict:
        workspace = build_pending_strategy_workspace(root)
        total = tx.parse_frontmatter(
            next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
        )
        return {"workspace": str(workspace), "context_id": total["context_id"]}

    def resume_args(self, root: Path, context_id: str, *extra: str) -> list[str]:
        intake = next(root.glob("intake-standard_visit-*.json"))
        return [
            "示例医院",
            "--output-root",
            str(root),
            "--context-id",
            context_id,
            "--resume",
            "--business-mode",
            "standard_visit",
            "--intake-input",
            str(intake),
            "--runtime-owner",
            "测试负责人",
            "--lock-timeout",
            "10",
            *extra,
            "--json",
        ]

    def test_concurrent_resumes_both_succeed_without_lost_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            before = load_json(workspace / "runtime" / "manifest.json")
            args = self.resume_args(root, initial["context_id"])
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(run_python, "init_workspace.py", args) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]
            for result in results:
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payloads = [json.loads(result.stdout) for result in results]
            self.assertEqual(len({payload["latest_run_id"] for payload in payloads}), 2)
            after = load_json(workspace / "runtime" / "manifest.json")
            self.assertEqual(after["transaction_sequence"], before["transaction_sequence"] + 2)
            self.assertEqual(before["task_timezone"], "Asia/Shanghai")
            self.assertEqual(after["task_timezone"], before["task_timezone"])
            total = next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
            for payload in payloads:
                self.assertGreaterEqual(total.count(payload["latest_run_id"]), 1)

    def test_unfinished_journal_requires_and_accepts_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            crashed = run_python(
                "init_workspace.py",
                self.resume_args(root, initial["context_id"]),
                env={"DISCOVERY_CALL_TX_SIGKILL_AFTER": "1"},
            )
            self.assertNotEqual(crashed.returncode, 0)
            self.assertTrue((workspace / tx.JOURNAL_NAME).is_file())
            blocked = run_python(
                "init_workspace.py", self.resume_args(root, initial["context_id"])
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("未完成事务", blocked.stderr)
            recovered = run_python(
                "init_workspace.py",
                self.resume_args(
                    root,
                    initial["context_id"],
                    "--recover",
                    "--recovery-strategy",
                    "auto",
                ),
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr or recovered.stdout)
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
            self.assertEqual(
                load_json(workspace / "runtime" / "manifest.json")["task_timezone"],
                "Asia/Shanghai",
            )
            validation = run_python(
                "validate_outputs.py", [str(workspace), "--profile", "scaffold", "--json"]
            )
            self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)

    def test_commit_run_manifest_cas_rejects_stale_second_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root / "live")
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = load_json(manifest_path)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
            strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
            total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
            strategy_text = strategy_path.read_text(encoding="utf-8")
            strategy = tx.parse_frontmatter(strategy_text)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            run_id = f"dcr-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}"
            payload = {
                "schema": "discovery-call-candidate-run/v1",
                "context_id": total["context_id"],
                "expected_manifest_revision": manifest["transaction_sequence"],
                "expected_manifest_sha256": digest,
                "run": {
                    "run_id": run_id,
                    "updated_at": now.isoformat().replace("+00:00", "Z"),
                    "evidence_cutoff_date": total["evidence_cutoff_date"],
                    "runtime_owner": "CAS测试负责人",
                    "workflow_stage": "review",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "objective": "验证candidate CAS",
                },
                "artifacts": [
                    {"artifact_type": "institution_research", "action": "reused", "key_claim_ids": "CLM-I-001"},
                    {"artifact_type": "leader_research", "action": "reused", "key_claim_ids": "CLM-L-001"},
                    {
                        "artifact_type": "visit_strategy",
                        "action": "updated",
                        "module_status": "completed",
                        "freshness_status": "current",
                        "connector_status": "not_applicable",
                        "body": _body(strategy_text) + "\n\nCAS候选。",
                        "metadata": {
                            "target_contact_level": strategy["target_contact_level"],
                            "visit_objective": strategy["visit_objective"],
                            "minimum_next_step": strategy["minimum_next_step"],
                        },
                        "key_claim_ids": "CLM-I-001, CLM-L-001",
                        "summary_sync_status": "synced",
                        "downstream_invalidation": "none",
                        "gaps_blockers": "无",
                    },
                ],
            }
            payload_path = root / "candidate-payload.json"
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            built = run_python(
                "build_candidate.py",
                [str(workspace), "--payload", str(payload_path), "--output-root", str(root / "candidate"), "--json"],
            )
            self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
            args = json.loads(built.stdout)["next_commit"]["argv"][2:]
            first = run_python("commit_run.py", args)
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            second = run_python("commit_run.py", args)
            self.assertEqual(second.returncode, 2)
            self.assertIn("CAS", second.stderr)

    def test_runtime_transaction_rolls_back_all_files_on_postflight_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first = workspace / "first.txt"
            second = workspace / "second.txt"
            first.write_text("before", encoding="utf-8")

            def fail(_workspace: Path) -> None:
                raise RuntimeError("postflight failed")

            with tx.output_root_lock(workspace.parent, timeout=2):
                with tx.workspace_lock(workspace, timeout=2):
                    with self.assertRaises(RuntimeError):
                        tx.transactional_commit(
                            workspace,
                            {first: "after", second: "created"},
                            operation="test_rollback",
                            postflight=fail,
                        )
            self.assertEqual(first.read_text(encoding="utf-8"), "before")
            self.assertFalse(second.exists())
            self.assertFalse((workspace / tx.JOURNAL_NAME).exists())

    def test_workspace_lock_rejects_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            target = root / "unrelated.txt"
            target.write_text("must remain unchanged", encoding="utf-8")
            (workspace / tx.WORKSPACE_LOCK_NAME).symlink_to(target)

            with self.assertRaises(tx.TxError):
                with tx.workspace_lock(workspace, timeout=0.1):
                    self.fail("symlink lock must never be acquired")
            self.assertEqual(target.read_text(encoding="utf-8"), "must remain unchanged")


if __name__ == "__main__":
    unittest.main()
