from __future__ import annotations

import json
import os
import signal
import tempfile
import unittest
from pathlib import Path

from tests.common import run_python
from tests.common import runtime_tx as tx


class RecoveryIntegrityTests(unittest.TestCase):
    def run_init(self, root: Path, *extra: str, env=None):
        result = run_python("init_workspace.py", [
            "恢复完整性合成医院", "--output-root", str(root),
            "--modules", "institution", "--json", *extra,
        ], env=env)
        print("INIT", list(extra), "exit", result.returncode, flush=True)
        print(result.stdout, result.stderr, flush=True)
        return result

    def initialize(self, root: Path, zone: str | None = "UTC") -> Path:
        calendar = ["--task-timezone", zone] if zone else ["--evidence-cutoff-date", tx.utc_now()[:10]]
        result = self.run_init(root, *calendar)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        workspace = Path(json.loads(result.stdout)["workspace"])
        tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
        return workspace

    def total(self, workspace: Path) -> Path:
        return next(workspace.glob("*客户研究与拜访准备报告.md"))

    def snapshot(self, workspace: Path):
        # Exclude process-lock bookkeeping, but include the formal manifest and WAL.
        return {p.relative_to(workspace).as_posix(): p.read_bytes()
                for p in workspace.rglob("*")
                if p.is_file() and p.suffix in {".md", ".json"}}

    def crash_resume(self, root: Path, workspace: Path):
        crashed = self.run_init(root, "--resume", env={"DISCOVERY_CALL_TX_SIGKILL_AFTER": "1"})
        self.assertEqual(crashed.returncode, signal.SIGTERM if os.name == "nt" else -signal.SIGKILL)
        self.assertTrue(tx.unfinished_transaction(workspace))
        # The total is updated before the manifest: a legitimate intermediate state.
        with self.assertRaises(tx.CASMismatch):
            tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))

    def test_no_wal_recover_rejects_timezone_add_delete_change_without_writes(self):
        for change in ("change", "add", "delete"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = self.initialize(root, None if change == "add" else "UTC")
                total = self.total(workspace)
                original = total.read_bytes()
                if change == "add":
                    altered = original.replace(b"---", b'---\ntask_timezone: "UTC"', 1)
                elif change == "delete":
                    altered = b"".join(line for line in original.splitlines(keepends=True)
                                       if not line.startswith(b"task_timezone:"))
                else:
                    altered = original.replace(b'task_timezone: "UTC"', b'task_timezone: "Asia/Shanghai"')
                self.assertNotEqual(altered, original)
                total.write_bytes(altered)
                self.assertFalse(tx.unfinished_transaction(workspace))
                with self.assertRaises(tx.CASMismatch):
                    tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
                before = self.snapshot(workspace)
                result = self.run_init(root, "--resume", "--recover")
                self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                self.assertIn("清单成果被绕过事务修改", result.stderr)
                self.assertEqual(self.snapshot(workspace), before)

    def test_no_wal_recover_preserves_calendar_and_absence(self):
        for zone in ("UTC", None):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = self.initialize(root, zone)
                revision, _ = tx.manifest_state(workspace)
                result = self.run_init(root, "--resume", "--recover")
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertEqual(json.loads(result.stdout)["recovery"], "no_transaction_reconcile")
                self.assertEqual(tx.manifest_state(workspace)[0], revision + 1)
                tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
                self.assertEqual(tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8")).get("task_timezone"), zone)

    def test_legal_wal_recovers_before_integrity_check(self):
        for strategy in ("auto", "roll-forward"):
            with self.subTest(strategy=strategy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = self.initialize(root)
                self.crash_resume(root, workspace)
                before = self.snapshot(workspace)
                blocked = self.run_init(root, "--resume")
                self.assertEqual(blocked.returncode, 2)
                self.assertIn("未完成事务", blocked.stderr)
                self.assertEqual(self.snapshot(workspace), before)
                result = self.run_init(root, "--resume", "--recover", "--recovery-strategy", strategy)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertEqual(json.loads(result.stdout)["recovery"], "rolled_back" if strategy == "auto" else "rolled_forward")
                self.assertFalse(tx.unfinished_transaction(workspace))
                tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
                self.assertEqual(tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8"))["task_timezone"], "UTC")

    def test_bad_wal_recovery_rejects_third_party_hash_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = self.initialize(root)
            self.crash_resume(root, workspace)
            total = self.total(workspace)
            total.write_bytes(total.read_bytes() + b"\nThird-party modification\n")
            before = self.snapshot(workspace)
            result = self.run_init(root, "--resume", "--recover")
            self.assertEqual(result.returncode, 2)
            self.assertIn("恢复目标存在第三方修改", result.stderr)
            self.assertTrue(tx.unfinished_transaction(workspace))
            self.assertEqual(self.snapshot(workspace), before)

    def test_legacy_no_manifest_recovery_keeps_migration_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = self.initialize(root, None)
            (workspace / tx.MANIFEST_REL).unlink()
            result = self.run_init(root, "--resume", "--recover")
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            tx.verify_manifest_artifacts(workspace, tx.load_manifest(workspace))
            self.assertNotIn("task_timezone", tx.parse_frontmatter(self.total(workspace).read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
