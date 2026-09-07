from __future__ import annotations

import hashlib
import json
import os
import signal
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.common import load_json, run_python, runtime_tx as tx


class RuntimeTransactionTests(unittest.TestCase):
    def initialize(self, root: Path) -> dict:
        result = run_python(
            "init_workspace.py",
            [
                "并发测试医院",
                "--output-root",
                str(root),
                "--task-timezone",
                "Asia/Shanghai",
                "--runtime-owner",
                "测试负责人",
                "--route",
                "research_only",
                "--modules",
                "institution",
                "--json",
            ],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def resume_args(self, root: Path, context_id: str, *extra: str) -> list[str]:
        return [
            "并发测试医院",
            "--output-root",
            str(root),
            "--context-id",
            context_id,
            "--resume",
            "--route",
            "research_only",
            "--modules",
            "institution",
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
            self.assertEqual(
                crashed.returncode, signal.SIGTERM if os.name == "nt" else -signal.SIGKILL,
                crashed.stderr or crashed.stdout,
            )
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
            validation = run_python("validate_outputs.py", [str(workspace), "--json"])
            self.assertEqual(validation.returncode, 0, validation.stderr or validation.stdout)

    def test_commit_run_manifest_cas_rejects_stale_second_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = self.initialize(root)
            workspace = Path(initial["workspace"])
            manifest_path = workspace / "runtime" / "manifest.json"
            manifest = load_json(manifest_path)
            digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            candidate = root / "candidate"
            candidate.mkdir()
            for source in workspace.glob("*.md"):
                (candidate / source.name).write_bytes(source.read_bytes())
            args = [
                str(workspace),
                "--candidate-workspace",
                str(candidate),
                "--expected-manifest-revision",
                str(manifest["transaction_sequence"]),
                "--expected-manifest-sha256",
                digest,
                "--json",
            ]
            first = run_python("commit_run.py", args)
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            second = run_python("commit_run.py", args)
            self.assertEqual(second.returncode, 2)
            self.assertIn("CAS", second.stderr)

    def test_runtime_transaction_rolls_back_all_files_on_postflight_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first = workspace / "first.md"
            second = workspace / "second.md"
            first.write_text("before", encoding="utf-8")

            callbacks: list[Path] = []

            def fail(_workspace: Path) -> None:
                callbacks.append(_workspace)
                self.assertEqual(first.read_text(encoding="utf-8"), "after")
                self.assertEqual(second.read_text(encoding="utf-8"), "created")
                raise RuntimeError("postflight failed")

            with tx.output_root_lock(workspace.parent, timeout=2):
                with tx.workspace_lock(workspace, timeout=2):
                    with self.assertRaisesRegex(RuntimeError, "^postflight failed$"):
                        tx.transactional_commit(
                            workspace,
                            {first: "after", second: "created"},
                            operation="test_rollback",
                            postflight=fail,
                        )
            self.assertEqual(callbacks, [workspace])
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
