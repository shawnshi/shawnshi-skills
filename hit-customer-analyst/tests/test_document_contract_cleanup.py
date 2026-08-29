from __future__ import annotations

import unittest

from tests.common import SKILL_ROOT


class DocumentContractCleanupTests(unittest.TestCase):
    def test_research_subskills_use_safe_name_for_paths_and_canonical_name_for_titles(self):
        path_contracts = {
            "subskill-institution-research.md": "机构研究报告.md",
            "subskill-leader-research.md": "人物研究报告.md",
            "subskill-internal-retrieval.md": "内部信息检索报告.md",
        }
        for filename, suffix in path_contracts.items():
            with self.subTest(reference=filename):
                reference = (SKILL_ROOT / "references" / filename).read_text(encoding="utf-8")
                self.assertIn(f"{{{{safe_name}}}}{suffix}", reference)
                self.assertNotIn(f"{{{{客户中文规范名称}}}}{suffix}", reference)

        for filename in (
            "institution-research-report-template.md",
            "leader-research-report-template.md",
            "internal-retrieval-report-template.md",
        ):
            with self.subTest(template=filename):
                template = (SKILL_ROOT / "assets" / filename).read_text(encoding="utf-8")
                self.assertIn("# {{客户中文规范名称}}", template)

    def test_strategy_templates_leave_package_readiness_to_comprehensive_report(self):
        strategy_templates = (
            "visit-strategy-report-template.md",
            "account-strategy-report-template.md",
            "account-no-go-strategy-template.md",
        )
        for filename in strategy_templates:
            with self.subTest(template=filename):
                text = (SKILL_ROOT / "assets" / filename).read_text(encoding="utf-8")
                frontmatter = text.split("---", 2)[1]
                self.assertNotIn("ready_for_use:", frontmatter)

        contract = (
            SKILL_ROOT / "references" / "subskill-visit-strategy.md"
        ).read_text(encoding="utf-8")
        self.assertIn("该字段只属于包级`comprehensive_report`", contract)
        self.assertIn("综合报告的包级`ready_for_use`", contract)

    def test_governance_has_one_forward_gate_and_an_artifact_mode_role_matrix(self):
        governance = (
            SKILL_ROOT / "references" / "governance-raci.md"
        ).read_text(encoding="utf-8")
        self.assertIn("[发布前向评估证据门禁](forward-evaluation.md)", governance)
        self.assertIn("共至少12个正链slot", governance)
        self.assertIn("共至少6个负链slot", governance)
        self.assertIn("总slot不少于18", governance)
        self.assertNotIn("各完成至少一次端到端演练", governance)
        self.assertIn("| 操作 | artifact | business_mode | 允许角色 |", governance)
        self.assertIn("briefing（仅公开机构事实的低风险速览）", governance)
        self.assertIn("`evidence_reviewer`或`account_owner`", governance)
        for row in (
            "| 通用成果审核 | visit_strategy | standard_visit / strategic_account | `commercial_reviewer` |",
            "| 包级mark-ready | comprehensive_report | standard_visit | `commercial_reviewer` |",
            "| 包级mark-ready | comprehensive_report | strategic_account | `account_owner` |",
            "| 包级mark-ready | comprehensive_report | letter | `external_approver` |",
        ):
            self.assertIn(row, governance)


if __name__ == "__main__":
    unittest.main()
