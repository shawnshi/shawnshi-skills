from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.common import CONFIG, SCRIPTS, SKILL_ROOT, load_module, runtime_tx as tx


SCHEMA_PATH = SKILL_ROOT / "schemas" / "business-modes.schema.json"
VALIDATOR = load_module("strategy_variant_contract_validator", SCRIPTS / "validate_outputs.py")


def headings(text: str) -> set[str]:
    return {
        match.group(1).strip()
        for match in re.finditer(r"^##\s+(?:\d+\.\s+)?(.+?)\s*$", text, re.MULTILINE)
    }


class StrategyVariantAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.profile = cls.config["profiles"]["strategic_account"]
        cls.variant_contract = cls.profile["strategy_variants"]

    def test_strategic_account_common_fields_do_not_force_a_meeting(self):
        common = set(self.profile["required_business_fields"])
        self.assertEqual(
            common,
            {"customer_name", "organization_scope", "strategy_variant", "minimum_next_step"},
        )
        self.assertTrue(
            {"target_contact_level", "visit_objective", "strategic_question", "planning_horizon"}
            .isdisjoint(common)
        )
        self.assertNotIn(
            "target_identity_or_role_resolved",
            self.profile["planning_gate"]["required"],
        )

    def test_both_strategy_variants_have_distinct_machine_contracts(self):
        contract = self.variant_contract
        self.assertEqual(contract["default"], "account_planning")
        variants = contract["variants"]
        self.assertEqual(set(variants), {"scheduled_visit", "account_planning"})

        scheduled = variants["scheduled_visit"]
        account = variants["account_planning"]
        self.assertEqual(
            set(scheduled["required_business_fields"]),
            {"target_contact_level", "visit_objective"},
        )
        self.assertEqual(
            set(account["required_business_fields"]),
            {"strategic_question", "planning_horizon"},
        )
        self.assertEqual(
            scheduled["planning_gate"],
            ["target_identity_or_role_resolved"],
        )
        self.assertEqual(
            account["planning_gate"],
            ["strategic_question_resolved", "planning_horizon_resolved"],
        )
        self.assertIn("30/60/90天账户动作", account["required_sections"])
        self.assertIn("时间化议程与参会分工", account["forbidden_sections"])
        self.assertEqual(
            set(scheduled["forbidden_business_fields"]),
            {"strategic_question", "planning_horizon"},
        )
        self.assertTrue(
            {"target_contact_level", "visit_objective", "meeting_time", "participants"}
            <= set(account["forbidden_business_fields"])
        )
        self.assertTrue(
            {"会议", "议程", "参会", "材料计划"}
            <= set(account["forbidden_heading_terms"])
        )
        self.assertTrue(
            {"会议对象", "会议时间", "客户参会人", "展示材料"}
            <= set(account["forbidden_body_labels"])
        )

    def test_variant_templates_exist_and_persist_the_variant(self):
        for variant_name, contract in self.variant_contract["variants"].items():
            with self.subTest(variant=variant_name):
                template_path = SKILL_ROOT / contract["template"]
                self.assertTrue(template_path.is_file(), template_path)
                metadata = tx.parse_frontmatter(template_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["artifact_type"], "visit_strategy")
                self.assertEqual(metadata["strategy_variant"], variant_name)
                for field in contract["required_business_fields"]:
                    self.assertIn(field, metadata)
                self.assertIn("minimum_next_step", metadata)

    def test_account_template_has_account_actions_without_meeting_sections(self):
        account = self.variant_contract["variants"]["account_planning"]
        template = (SKILL_ROOT / account["template"]).read_text(encoding="utf-8")
        actual_headings = headings(template)
        self.assertTrue(set(account["required_sections"]) <= actual_headings)
        self.assertTrue(set(account["forbidden_sections"]).isdisjoint(actual_headings))

        self.assertIn(
            "| 周期 | action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |",
            template,
        )
        for horizon in ("30天", "60天", "90天"):
            rows = [line for line in template.splitlines() if line.startswith(f"| {horizon} |")]
            self.assertEqual(len(rows), 1, horizon)

        metadata = tx.parse_frontmatter(template)
        self.assertNotIn("target_contact_level", metadata)
        self.assertNotIn("visit_objective", metadata)

    def test_business_mode_schema_defines_strategy_variant_contract(self):
        profile_schema = self.schema["$defs"]["profile"]
        self.assertEqual(
            profile_schema["properties"]["strategy_variants"],
            {"$ref": "#/$defs/strategy_variants"},
        )
        variant_schema = self.schema["$defs"]["strategy_variants"]
        self.assertEqual(
            set(variant_schema["properties"]["variants"]["required"]),
            {"scheduled_visit", "account_planning"},
        )
        self.assertEqual(
            set(self.schema["$defs"]["strategy_variant"]["required"]),
            {
                "template",
                "required_business_fields",
                "planning_gate",
                "required_sections",
                "forbidden_sections",
                "forbidden_business_fields",
                "forbidden_heading_terms",
                "forbidden_body_labels",
            },
        )

    def test_direct_forged_account_meeting_fields_and_headings_are_rejected(self):
        strategy = VALIDATOR.Document(
            Path("/tmp/示例医院交流策略与议题设计.md"),
            "",
            {
                "strategy_variant": "account_planning",
                "strategic_question": "未来90天是否值得持续投入",
                "planning_horizon": "90天",
                "minimum_next_step": "验证项目窗口",
                "target_contact_level": "分管副院长（未确认）",
                "meeting_time": "2026-09-15 14:00（未确认）",
                "module_status": "completed",
                "freshness_status": "current",
                "evidence_cutoff_date": "2026-08-27",
            },
            """## 战略问题与最小推进动作
未来90天是否值得持续投入；最小推进动作：验证项目窗口。
## 已排会议安排
会议时间、对象与参会人均无证据。
## 材料计划
现场演示产品。
""",
        )
        total = VALIDATOR.Document(
            Path("/tmp/示例医院客户研究与拜访准备报告.md"),
            "",
            {
                "business_mode": "strategic_account",
                "route": "strategy",
                "depth": "deep",
                "ready_for_use": "false",
                "module_status": "completed",
                "freshness_status": "current",
                "evidence_cutoff_date": "2026-08-27",
                "runtime_owner": "测试负责人",
            },
            "",
        )
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": strategy},
            issues,
            strict=False,
        )
        codes = {issue.code for issue in issues}
        self.assertIn("strategy_variant_field_forbidden", codes)
        self.assertIn("strategy_variant_heading_forbidden", codes)

        structured_strategy = VALIDATOR.Document(
            strategy.path,
            "",
            {
                "strategy_variant": "account_planning",
                "strategic_question": "未来90天是否值得持续投入",
                "planning_horizon": "90天",
                "minimum_next_step": "验证项目窗口",
                "module_status": "completed",
                "freshness_status": "current",
                "evidence_cutoff_date": "2026-08-27",
            },
            """## 验证计划
- 会议对象：张主任（无输入或证据）
- 会议时间：2026-09-15 14:00（无输入或证据）
| 客户参会人 | 张主任、李处长 |
| 展示材料 | V3产品演示 |
""",
        )
        structured_issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": structured_strategy},
            structured_issues,
            strict=False,
        )
        structured_codes = {issue.code for issue in structured_issues}
        self.assertIn("strategy_variant_body_label_forbidden", structured_codes)
        self.assertNotIn("strategy_variant_heading_forbidden", structured_codes)


if __name__ == "__main__":
    unittest.main()
