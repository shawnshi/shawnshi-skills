from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.common import (
    SCRIPTS,
    SKILL_ROOT,
    bind_intake_payload,
    load_json,
    load_module,
    run_python,
    runtime_tx as tx,
    write_intake,
)
from tests.fixture_builder import build_pending_strategy_workspace


INITIALIZER = load_module("strategy_variant_migration_initializer", SCRIPTS / "init_workspace.py")
RESEARCH_RUNTIME_NAMES = {
    "evidence-manifest.json",
    "run-metrics.json",
    "search-plan.json",
    "source-cache.json",
}


def candidate_set(field: str, candidate_id: str, value: object) -> dict[str, object]:
    return {
        "field": field,
        "candidates": [
            {
                "candidate_id": candidate_id,
                "value": value,
                "status": "asserted",
                "source_ref": "test:user-turn:1",
            }
        ],
    }


def scheduled_strategic_intake(path: Path) -> Path:
    payload = {
        "schema": "discovery-call-intake/v2",
        "request_id": "test-strategy-scheduled-transition",
        "business_mode": "strategic_account",
        "candidate_sets": [
            candidate_set("customer_name", "customer-1", "示例医院"),
            candidate_set("organization_scope", "scope-1", "示例医院"),
            candidate_set("meeting_status", "status-1", "confirmed"),
            candidate_set(
                "meeting_time",
                "time-1",
                {
                    "start": "2026-09-02T14:00:00+08:00",
                    "end": "2026-09-02T15:00:00+08:00",
                    "timezone": "Asia/Shanghai",
                },
            ),
            candidate_set("target_role", "role-1", "信息中心主任"),
            candidate_set("visit_objective", "objective-1", "确认年度建设重点"),
            candidate_set("minimum_next_step", "step-1", "安排专题交流"),
        ],
        "confirmations": [],
    }
    return bind_intake_payload(path, payload)


class StrategyVariantMigrationTests(unittest.TestCase):
    def test_account_planning_workspace_can_be_audited_for_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake = write_intake(root / "intakes", "示例医院", "strategic_account")
            initialized = run_python(
                "init_workspace.py",
                [
                    "示例医院",
                    "--output-root",
                    str(root),
                    "--task-timezone",
                    "Asia/Shanghai",
                    "--runtime-owner",
                    "测试负责人",
                    "--business-mode",
                    "strategic_account",
                    "--intake-input",
                    str(intake),
                    "--json",
                ],
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
            workspace = Path(json.loads(initialized.stdout)["workspace"])
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            audited = INITIALIZER.audit_existing_workspace(workspace, total)
            strategy = next(
                data for data in audited.values() if data.get("artifact_type") == "visit_strategy"
            )
            self.assertEqual(strategy["strategy_variant"], "account_planning")
            self.assertEqual(strategy["strategic_question"], "未来90天是否值得持续投入")
            self.assertEqual(strategy["planning_horizon"], "90天")
            self.assertNotIn("target_contact_level", strategy)
            self.assertNotIn("visit_objective", strategy)
            strategy_text = next(workspace.glob("*交流策略与议题设计.md")).read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "| 周期 | action | action_disposition | external_interaction | resource_commitment | owner |",
                strategy_text,
            )

    def test_comprehensive_template_is_account_and_visit_neutral(self):
        template = (SKILL_ROOT / "assets" / "comprehensive-report-template.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## 4.2 执行与下一步", template)
        self.assertIn(
            "| action | action_disposition | external_interaction | resource_commitment | owner | due_date |",
            template,
        )
        self.assertIn("继续/调整/no-go条件", template)
        no_go_template = (
            SKILL_ROOT / "assets" / "account-no-go-comprehensive-template.md"
        ).read_text(encoding="utf-8")
        self.assertIn("- 建议：no_go", no_go_template)
        self.assertIn("| {{与策略30天action逐字一致}}", no_go_template)
        self.assertIn("| none | none |", no_go_template)
        self.assertNotIn("## 4.2 拜访执行与下一步", template)
        self.assertNotIn("| 时间 | 议题/动作 |", template)
        self.assertNotIn("材料/演示", template)

    def test_strategy_branch_round_trip_rebuilds_carrier_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = build_pending_strategy_workspace(root)
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            context_id = tx.parse_frontmatter(total.read_text(encoding="utf-8"))["context_id"]
            account_intake = write_intake(
                root / "account-intake", "示例医院", "strategic_account"
            )
            common = [
                "示例医院",
                "--output-root",
                str(root),
                "--context-id",
                context_id,
                "--resume",
                "--business-mode",
                "strategic_account",
                "--runtime-owner",
                "测试负责人",
                "--json",
            ]
            to_account = run_python(
                "init_workspace.py",
                [*common[:-1], "--intake-input", str(account_intake), "--json"],
                timeout=60,
            )
            self.assertEqual(to_account.returncode, 0, to_account.stderr or to_account.stdout)
            account_result = json.loads(to_account.stdout)
            self.assertEqual(account_result["previous_strategy_variant"], "scheduled_visit")
            self.assertEqual(account_result["strategy_variant"], "account_planning")
            self.assertEqual(
                set(Path(name).name for name in account_result["invalidated_runtime_files"]),
                RESEARCH_RUNTIME_NAMES,
            )

            strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
            account = tx.parse_frontmatter(strategy_path.read_text(encoding="utf-8"))
            self.assertEqual(account["strategy_variant"], "account_planning")
            self.assertEqual(account["review_status"], "not_started")
            self.assertEqual(account["ready_for_use"], "false")
            self.assertNotIn("target_contact_level", account)
            self.assertNotIn("visit_objective", account)
            account_text = strategy_path.read_text(encoding="utf-8")
            self.assertIn(
                "| 周期 | action | action_disposition | external_interaction | resource_commitment | owner |",
                account_text,
            )
            total_text = total.read_text(encoding="utf-8")
            self.assertIn(
                "| action | action_disposition | external_interaction | resource_commitment | owner |",
                total_text,
            )
            manifest = load_json(workspace / tx.MANIFEST_REL)
            self.assertEqual(
                manifest["artifacts"]["visit_strategy"]["strategy_variant"],
                "account_planning",
            )
            self.assertTrue(RESEARCH_RUNTIME_NAMES.isdisjoint(manifest["runtime_files"]))
            for name in RESEARCH_RUNTIME_NAMES:
                self.assertFalse((workspace / "runtime" / name).exists())

            scheduled_intake = scheduled_strategic_intake(root / "scheduled-intake.json")
            to_scheduled = run_python(
                "init_workspace.py",
                [*common[:-1], "--intake-input", str(scheduled_intake), "--json"],
                timeout=60,
            )
            self.assertEqual(
                to_scheduled.returncode,
                0,
                to_scheduled.stderr or to_scheduled.stdout,
            )
            scheduled_result = json.loads(to_scheduled.stdout)
            self.assertEqual(scheduled_result["previous_strategy_variant"], "account_planning")
            self.assertEqual(scheduled_result["strategy_variant"], "scheduled_visit")
            scheduled = tx.parse_frontmatter(strategy_path.read_text(encoding="utf-8"))
            self.assertEqual(scheduled["strategy_variant"], "scheduled_visit")
            self.assertEqual(scheduled["review_status"], "not_started")
            self.assertEqual(scheduled["ready_for_use"], "false")
            self.assertNotIn("strategic_question", scheduled)
            self.assertNotIn("planning_horizon", scheduled)
            manifest = load_json(workspace / tx.MANIFEST_REL)
            self.assertEqual(
                manifest["artifacts"]["visit_strategy"]["strategy_variant"],
                "scheduled_visit",
            )
            validated = run_python(
                "validate_outputs.py",
                [str(workspace), "--profile", "scaffold", "--json"],
                timeout=60,
            )
            self.assertEqual(validated.returncode, 0, validated.stderr or validated.stdout)


if __name__ == "__main__":
    unittest.main()
