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


if __name__ == "__main__":
    unittest.main()
