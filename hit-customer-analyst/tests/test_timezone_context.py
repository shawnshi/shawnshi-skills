from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.common import SCRIPTS, load_json, load_module, run_python, runtime_tx as tx, write_intake
from tests.fixture_builder import build_pending_strategy_workspace


initializer = load_module("discovery_call_timezone_initializer", SCRIPTS / "init_workspace.py")
validator = load_module("discovery_call_timezone_validator", SCRIPTS / "validate_outputs.py")


class TimezoneContextTests(unittest.TestCase):
    @staticmethod
    def write_manifest(root: Path, task_timezone: object = ...):
        payload: dict[str, object] = {
            "schema": tx.RUNTIME_SCHEMA,
            "transaction_sequence": 1,
        }
        if task_timezone is not ...:
            payload["task_timezone"] = task_timezone
        tx.atomic_write_json(root / tx.MANIFEST_REL, payload)

    @staticmethod
    def governance_codes(
        root: Path,
        cutoff: str,
        instant: datetime,
    ) -> set[str]:
        total = validator.Document(
            root / "示例医院客户研究与拜访准备报告.md",
            "",
            {
                "artifact_type": "comprehensive_report",
                "business_mode": "",
                "route": "research_only",
                "workflow_stage": "planning",
                "ready_for_use": "false",
                "freshness_status": "current",
                "evidence_cutoff_date": cutoff,
            },
            "",
        )
        issues: list[object] = []
        validator.validate_operating_governance(
            {"comprehensive_report": total},
            issues,
            False,
            instant,
        )
        return {issue.code for issue in issues}

    def test_frozen_asia_shanghai_crosses_utc_day_consistently(self):
        frozen = datetime(2026, 8, 26, 16, 5, tzinfo=timezone.utc)
        self.assertEqual(
            initializer.local_date_for_timezone("Asia/Shanghai", instant=frozen),
            "2026-08-27",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_manifest(root, "Asia/Shanghai")
            today, future_limit, name = validator.evidence_calendar(root, instant=frozen)
            self.assertEqual(today.isoformat(), "2026-08-27")
            self.assertEqual(future_limit, today)
            self.assertEqual(name, "Asia/Shanghai")
            self.assertNotIn(
                "evidence_cutoff_in_future",
                self.governance_codes(root, "2026-08-27", frozen),
            )

    def test_frozen_negative_offset_uses_previous_local_date(self):
        frozen = datetime(2026, 8, 27, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(
            initializer.local_date_for_timezone("America/Los_Angeles", instant=frozen),
            "2026-08-26",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_manifest(root, "America/Los_Angeles")
            self.assertNotIn(
                "evidence_cutoff_in_future",
                self.governance_codes(root, "2026-08-26", frozen),
            )
            self.assertIn(
                "evidence_cutoff_in_future",
                self.governance_codes(root, "2026-08-27", frozen),
            )

    def test_zoneinfo_dst_transition_is_used(self):
        before_local_midnight = datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)
        after_local_midnight = datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc)
        after_dst_jump = datetime(2026, 3, 8, 10, 30, tzinfo=timezone.utc)
        self.assertEqual(
            tx.task_date_at(before_local_midnight, "America/Los_Angeles").isoformat(),
            "2026-03-07",
        )
        self.assertEqual(
            tx.task_date_at(after_local_midnight, "America/Los_Angeles").isoformat(),
            "2026-03-08",
        )
        self.assertEqual(
            tx.task_date_at(after_dst_jump, "America/Los_Angeles").isoformat(),
            "2026-03-08",
        )

    def test_legacy_manifest_without_timezone_gets_bounded_date_only_compatibility(self):
        frozen = datetime(2026, 8, 26, 22, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_manifest(root)
            self.assertNotIn(
                "evidence_cutoff_in_future",
                self.governance_codes(root, "2026-08-27", frozen),
            )
            self.assertIn(
                "evidence_cutoff_in_future",
                self.governance_codes(root, "2026-08-28", frozen),
            )

    def test_invalid_persisted_timezone_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_manifest(root, "Not/A-Timezone")
            with self.assertRaises(tx.TxError):
                tx.load_manifest(root)

    def test_resume_inherits_timezone_and_rejects_change_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root)
            total = tx.parse_frontmatter(
                next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
            )
            intake = write_intake(root / "intakes", "示例医院", "standard_visit")
            manifest_path = workspace / tx.MANIFEST_REL
            before_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            common_resume = [
                "示例医院",
                "--output-root",
                str(root),
                "--context-id",
                total["context_id"],
                "--resume",
                "--business-mode",
                "standard_visit",
                "--intake-input",
                str(intake),
                "--runtime-owner",
                "测试负责人",
                "--json",
            ]
            conflict = run_python(
                "init_workspace.py",
                [*common_resume[:-1], "--task-timezone", "America/Los_Angeles", "--json"],
            )
            self.assertEqual(conflict.returncode, 2)
            self.assertIn("任务时区建立后不得", conflict.stderr)
            self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), before_hash)
            resumed = run_python("init_workspace.py", common_resume)
            self.assertEqual(resumed.returncode, 0, resumed.stderr or resumed.stdout)
            self.assertEqual(load_json(manifest_path)["task_timezone"], "Asia/Shanghai")

    def test_explicit_date_legacy_context_can_establish_timezone_on_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root)
            total = tx.parse_frontmatter(
                next(workspace.glob("*客户研究与拜访准备报告.md")).read_text(encoding="utf-8")
            )
            intake = write_intake(root / "intakes", "示例医院", "standard_visit")
            manifest_path = workspace / tx.MANIFEST_REL
            manifest = load_json(manifest_path)
            manifest.pop("task_timezone", None)
            tx.atomic_write_json(manifest_path, manifest)
            self.assertNotIn("task_timezone", load_json(manifest_path))
            resumed = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(root),
                    "--context-id",
                    total["context_id"],
                    "--resume",
                    "--business-mode",
                    "standard_visit",
                    "--intake-input",
                    str(intake),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--json",
                ],
            )
            self.assertEqual(resumed.returncode, 0, resumed.stderr or resumed.stdout)
            self.assertEqual(load_json(manifest_path)["task_timezone"], "Asia/Shanghai")

    def test_explicit_date_without_timezone_rejects_more_than_adjacent_utc_date(self):
        frozen = datetime(2026, 8, 26, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(
            initializer.validate_cutoff_not_future(
                "2026-08-27",
                None,
                instant=frozen,
            ),
            "2026-08-27",
        )
        with self.assertRaises(initializer.InitError):
            initializer.validate_cutoff_not_future(
                (frozen.date() + timedelta(days=2)).isoformat(),
                None,
                instant=frozen,
            )


if __name__ == "__main__":
    unittest.main()
