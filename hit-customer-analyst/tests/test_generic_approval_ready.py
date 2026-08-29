from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.common import run_python, runtime_tx as tx
from tests.fixture_builder import build_pending_strategy_workspace, record_action_assertion


class GenericApprovalAndReadyTests(unittest.TestCase):
    def govern(self, workspace: Path, *args: str) -> dict:
        result = run_python(
            "validate_outputs.py", [str(workspace), *args, "--json"]
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], 0, payload)
        return payload

    def test_generic_reviews_then_ready_and_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "output")
            self.govern(workspace)

            record_action_assertion(workspace, event_id="approve-institution", actor_id="reviewer-institution", operation="approve_artifact:institution", artifact_type="institution_research")
            institution_result = self.govern(
                workspace,
                "--approve-artifact",
                "institution",
                "--reviewer",
                "周洁（机构事实审核岗）",
                "--actor-id",
                "reviewer-institution",
                "--action-event-id",
                "approve-institution",
            )
            self.assertEqual(institution_result["operation"], "approve_institution")

            record_action_assertion(workspace, event_id="approve-leader", actor_id="reviewer-leader", operation="approve_artifact:leader", artifact_type="leader_research")
            leader_result = self.govern(
                workspace,
                "--approve-artifact",
                "leader",
                "--reviewer",
                "孙宁（人物事实审核岗）",
                "--actor-id",
                "reviewer-leader",
                "--action-event-id",
                "approve-leader",
            )
            self.assertEqual(leader_result["operation"], "approve_leader")
            leader = next(workspace.glob("*人物研究报告.md"))
            leader_meta = tx.parse_frontmatter(leader.read_text(encoding="utf-8"))
            self.assertEqual(leader_meta["review_status"], "approved")
            self.assertEqual(
                leader_meta["reviewed_content_version"], leader_meta["content_version"]
            )
            self.assertRegex(leader_meta["reviewed_body_sha256"], r"^[0-9a-f]{64}$")

            record_action_assertion(workspace, event_id="approve-strategy", actor_id="reviewer-strategy", operation="approve_artifact:strategy", artifact_type="visit_strategy")
            strategy_result = self.govern(
                workspace,
                "--approve-artifact",
                "strategy",
                "--reviewer",
                "钱琳（拜访策略审核岗）",
                "--actor-id",
                "reviewer-strategy",
                "--action-event-id",
                "approve-strategy",
            )
            self.assertEqual(strategy_result["operation"], "approve_strategy")
            strategy = next(workspace.glob("*交流策略与议题设计.md"))
            strategy_meta = tx.parse_frontmatter(strategy.read_text(encoding="utf-8"))
            self.assertEqual(strategy_meta["review_status"], "approved")
            self.assertEqual(
                strategy_meta["reviewed_content_version"], strategy_meta["content_version"]
            )
            self.assertRegex(strategy_meta["reviewed_body_sha256"], r"^[0-9a-f]{64}$")

            record_action_assertion(workspace, event_id="ready-standard", actor_id="ready-standard", operation="mark_ready:standard_visit", artifact_type="comprehensive_report")
            ready_result = self.govern(
                workspace,
                "--mark-ready",
                "--reviewer",
                "陈洁（交付就绪审核岗）",
                "--actor-id",
                "ready-standard",
                "--action-event-id",
                "ready-standard",
            )
            self.assertEqual(ready_result["operation"], "mark_ready")
            total = next(workspace.glob("*客户研究与拜访准备报告.md"))
            total_meta = tx.parse_frontmatter(total.read_text(encoding="utf-8"))
            self.assertEqual(total_meta["ready_for_use"], "true")
            self.assertEqual(
                total_meta["readiness_content_version"], total_meta["content_version"]
            )
            self.assertRegex(total_meta["readiness_body_sha256"], r"^[0-9a-f]{64}$")
            manifest = json.loads(
                (workspace / "runtime" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["ready_for_use"])
            strict = self.govern(workspace, "--strict")
            self.assertEqual(strict["errors"], 0)

    def test_strategic_account_release_path_is_repeatable_three_times(self):
        """Exercise the account-planning branch through its real release gates."""
        for repetition in range(1, 4):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                self.govern(workspace)

                record_action_assertion(
                    workspace,
                    event_id="approve-institution",
                    actor_id="reviewer-institution",
                    operation="approve_artifact:institution",
                    artifact_type="institution_research",
                )
                self.govern(
                    workspace,
                    "--approve-artifact",
                    "institution",
                    "--reviewer",
                    "周洁（机构事实审核岗）",
                    "--actor-id",
                    "reviewer-institution",
                    "--action-event-id",
                    "approve-institution",
                )

                record_action_assertion(
                    workspace,
                    event_id="approve-leader",
                    actor_id="reviewer-leader",
                    operation="approve_artifact:leader",
                    artifact_type="leader_research",
                )
                self.govern(
                    workspace,
                    "--approve-artifact",
                    "leader",
                    "--reviewer",
                    "孙宁（人物事实审核岗）",
                    "--actor-id",
                    "reviewer-leader",
                    "--action-event-id",
                    "approve-leader",
                )

                record_action_assertion(
                    workspace,
                    event_id="approve-strategy",
                    actor_id="reviewer-strategy",
                    operation="approve_artifact:strategy",
                    artifact_type="visit_strategy",
                )
                self.govern(
                    workspace,
                    "--approve-artifact",
                    "strategy",
                    "--reviewer",
                    "钱琳（拜访策略审核岗）",
                    "--actor-id",
                    "reviewer-strategy",
                    "--action-event-id",
                    "approve-strategy",
                )

                record_action_assertion(
                    workspace,
                    event_id="ready-strategic",
                    actor_id="ready-strategic",
                    operation="mark_ready:strategic_account",
                    artifact_type="comprehensive_report",
                )
                ready_result = self.govern(
                    workspace,
                    "--mark-ready",
                    "--reviewer",
                    "刘宁（战略账户责任岗）",
                    "--actor-id",
                    "ready-strategic",
                    "--action-event-id",
                    "ready-strategic",
                )
                self.assertEqual(ready_result["operation"], "mark_ready")

                strategy = next(workspace.glob("*交流策略与议题设计.md"))
                strategy_text = strategy.read_text(encoding="utf-8")
                strategy_meta = tx.parse_frontmatter(strategy_text)
                self.assertEqual(strategy_meta["strategy_variant"], "account_planning")
                self.assertIn("## 30/60/90天账户动作", strategy_text)
                self.assertNotIn("## 议程", strategy_text)
                self.assertNotIn("## 材料计划", strategy_text)

                total = next(workspace.glob("*客户研究与拜访准备报告.md"))
                total_text = total.read_text(encoding="utf-8")
                total_meta = tx.parse_frontmatter(total_text)
                self.assertEqual(total_meta["ready_for_use"], "true")
                self.assertNotIn("拜访执行与下一步", total_text)
                self.assertEqual(self.govern(workspace, "--strict")["errors"], 0)

    def test_role_level_visit_modes_do_not_require_leader_artifact(self):
        """A role-level target must complete without inventing a named person."""
        ready_context = {
            "standard_visit": (
                "ready-standard",
                "陈洁（交付就绪审核岗）",
                "mark_ready:standard_visit",
            ),
            "strategic_account": (
                "ready-strategic",
                "刘宁（战略账户责任岗）",
                "mark_ready:strategic_account",
            ),
        }
        for business_mode, (actor_id, reviewer, operation) in ready_context.items():
            with self.subTest(business_mode=business_mode), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode=business_mode,
                    include_leader=False,
                )
                self.assertEqual(list(workspace.glob("*人物研究报告.md")), [])
                self.govern(workspace)

                record_action_assertion(
                    workspace,
                    event_id=f"approve-institution-{business_mode}",
                    actor_id="reviewer-institution",
                    operation="approve_artifact:institution",
                    artifact_type="institution_research",
                )
                self.govern(
                    workspace,
                    "--approve-artifact",
                    "institution",
                    "--reviewer",
                    "周洁（机构事实审核岗）",
                    "--actor-id",
                    "reviewer-institution",
                    "--action-event-id",
                    f"approve-institution-{business_mode}",
                )

                record_action_assertion(
                    workspace,
                    event_id=f"approve-strategy-{business_mode}",
                    actor_id="reviewer-strategy",
                    operation="approve_artifact:strategy",
                    artifact_type="visit_strategy",
                )
                self.govern(
                    workspace,
                    "--approve-artifact",
                    "strategy",
                    "--reviewer",
                    "钱琳（拜访策略审核岗）",
                    "--actor-id",
                    "reviewer-strategy",
                    "--action-event-id",
                    f"approve-strategy-{business_mode}",
                )

                record_action_assertion(
                    workspace,
                    event_id=f"ready-{business_mode}",
                    actor_id=actor_id,
                    operation=operation,
                    artifact_type="comprehensive_report",
                )
                ready_result = self.govern(
                    workspace,
                    "--mark-ready",
                    "--reviewer",
                    reviewer,
                    "--actor-id",
                    actor_id,
                    "--action-event-id",
                    f"ready-{business_mode}",
                )
                self.assertEqual(ready_result["operation"], "mark_ready")
                self.assertEqual(self.govern(workspace, "--strict")["errors"], 0)


if __name__ == "__main__":
    unittest.main()
