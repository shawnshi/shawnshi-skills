from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertEqual(
            account["required_action_fields"],
            [
                "action",
                "action_disposition",
                "external_interaction",
                "resource_commitment",
                "owner",
                "due_date",
                "dependency",
                "completion_criteria",
                "adjust_or_stop_trigger",
                "crm_candidate",
            ],
        )
        self.assertEqual(
            set(account["required_no_go_fields"]),
            {
                "recommendation",
                "investment_intensity",
                "recommendation_reason",
                "minimum_stop_condition",
            },
        )
        self.assertTrue(
            {"meeting_time", "meeting_target", "meeting_participants", "meeting_agenda", "meeting_materials"}
            <= set(account["forbidden_followup_fields"])
        )

    def test_recommendation_template_selector_is_total_and_fail_closed(self):
        account = self.variant_contract["variants"]["account_planning"]
        mapping = account["template_by_recommendation"]
        self.assertEqual(set(mapping), {"default", "no_go"})
        default_pair = {
            "visit_strategy": "assets/account-strategy-report-template.md",
            "comprehensive_report": "assets/comprehensive-report-template.md",
        }
        no_go_pair = {
            "visit_strategy": "assets/account-no-go-strategy-template.md",
            "comprehensive_report": "assets/account-no-go-comprehensive-template.md",
        }
        for recommendation in ("win", "conditional_win", "monitor"):
            with self.subTest(recommendation=recommendation):
                self.assertEqual(
                    VALIDATOR.recommendation_template_pair(
                        "strategic_account",
                        "account_planning",
                        recommendation,
                        profiles=self.config["profiles"],
                    ),
                    default_pair,
                )
        self.assertEqual(
            VALIDATOR.recommendation_template_pair(
                "strategic_account",
                "account_planning",
                "no_go",
                profiles=self.config["profiles"],
            ),
            no_go_pair,
        )
        for invalid in ("", "maybe", "NO_GO"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    VALIDATOR.recommendation_template_pair(
                        "strategic_account",
                        "account_planning",
                        invalid,
                        profiles=self.config["profiles"],
                    )

        for mode, variant in (
            ("standard_visit", "account_planning"),
            ("strategic_account", "scheduled_visit"),
        ):
            with self.subTest(mode=mode, variant=variant):
                with self.assertRaises(ValueError):
                    VALIDATOR.recommendation_template_pair(
                        mode,
                        variant,
                        "no_go",
                        profiles=self.config["profiles"],
                    )

        malformed = copy.deepcopy(self.config["profiles"])
        malformed["strategic_account"]["strategy_variants"]["variants"]["account_planning"][
            "template_by_recommendation"
        ]["fallback"] = default_pair
        with self.assertRaises(ValueError):
            VALIDATOR.recommendation_template_pair(
                "strategic_account",
                "account_planning",
                "monitor",
                profiles=malformed,
            )

        malformed_unselected = copy.deepcopy(self.config["profiles"])
        malformed_unselected["strategic_account"]["strategy_variants"]["variants"][
            "account_planning"
        ]["template_by_recommendation"]["no_go"]["extra"] = "assets/unused.md"
        with self.assertRaises(ValueError):
            VALIDATOR.recommendation_template_pair(
                "strategic_account",
                "account_planning",
                "monitor",
                profiles=malformed_unselected,
            )

    def test_no_go_template_route_requires_specialized_closed_structure(self):
        account = self.variant_contract["variants"]["account_planning"]
        strategy_body = (
            SKILL_ROOT / "assets" / "account-no-go-strategy-template.md"
        ).read_text(encoding="utf-8")
        total_body = (
            SKILL_ROOT / "assets" / "account-no-go-comprehensive-template.md"
        ).read_text(encoding="utf-8")
        strategy = VALIDATOR.Document(
            Path("/tmp/no-go-strategy.md"),
            "",
            {"strategy_variant": "account_planning", "module_status": "completed"},
            strategy_body,
        )
        total = VALIDATOR.Document(
            Path("/tmp/no-go-total.md"),
            "",
            {"business_mode": "strategic_account"},
            total_body,
        )
        issues: list[object] = []
        VALIDATOR.validate_recommendation_template_route(
            total,
            strategy,
            account,
            self.config["profiles"],
            issues,
        )
        self.assertFalse(issues, issues)

        extra_total = VALIDATOR.Document(
            total.path,
            "",
            total.frontmatter,
            total.body + "\n## 异常审核队列\n\n不得进入专用结构。\n",
        )
        extra_strategy = VALIDATOR.Document(
            strategy.path,
            "",
            strategy.frontmatter,
            strategy.body + "\n## 依据导航与缺口\n\n不得进入专用结构。\n",
        )
        for mutated_total, mutated_strategy in (
            (extra_total, strategy),
            (total, extra_strategy),
        ):
            with self.subTest(target=mutated_total.path.name + mutated_strategy.path.name):
                mutated_issues: list[object] = []
                VALIDATOR.validate_recommendation_template_route(
                    mutated_total,
                    mutated_strategy,
                    account,
                    self.config["profiles"],
                    mutated_issues,
                )
                self.assertIn(
                    "no_go_template_route_mismatch",
                    {issue.code for issue in mutated_issues},
                )

        invalid_strategy = VALIDATOR.Document(
            strategy.path,
            "",
            strategy.frontmatter,
            strategy.body.replace("- 建议：no_go", "- 建议：maybe", 1),
        )
        invalid_issues: list[object] = []
        VALIDATOR.validate_recommendation_template_route(
            total,
            invalid_strategy,
            account,
            self.config["profiles"],
            invalid_issues,
        )
        self.assertIn(
            "recommendation_template_route_invalid",
            {issue.code for issue in invalid_issues},
        )

        duplicated_strategy = VALIDATOR.Document(
            strategy.path,
            "",
            strategy.frontmatter,
            strategy.body.replace("- 建议：no_go", "- 建议：no_go\n- 建议：monitor", 1),
        )
        duplicated_issues: list[object] = []
        VALIDATOR.validate_recommendation_template_route(
            total,
            duplicated_strategy,
            account,
            self.config["profiles"],
            duplicated_issues,
        )
        self.assertIn(
            "recommendation_template_route_invalid",
            {issue.code for issue in duplicated_issues},
        )

        scaffold = VALIDATOR.Document(
            strategy.path,
            "",
            {"strategy_variant": "account_planning", "module_status": "pending"},
            (SKILL_ROOT / "assets" / "account-strategy-report-template.md").read_text(
                encoding="utf-8"
            ),
        )
        scaffold_issues: list[object] = []
        VALIDATOR.validate_recommendation_template_route(
            total,
            scaffold,
            account,
            self.config["profiles"],
            scaffold_issues,
        )
        self.assertFalse(scaffold_issues, scaffold_issues)

    def test_four_modes_have_exact_delivery_and_audit_contracts(self):
        expected = {
            "briefing": "briefing_delivery",
            "standard_visit": "visit_strategy",
            "strategic_account": "visit_strategy",
            "letter": "customer_letter_external",
        }
        for mode, formal_artifact in expected.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    VALIDATOR.delivery_contract_for_mode(
                        mode,
                        profiles=self.config["profiles"],
                    ),
                    {
                        "formal_artifact": formal_artifact,
                        "audit_artifact": "comprehensive_report",
                    },
                )

        malformed = copy.deepcopy(self.config["profiles"])
        malformed["standard_visit"]["delivery_contract"]["formal_artifact"] = (
            "comprehensive_report"
        )
        with self.assertRaises(ValueError):
            VALIDATOR.delivery_contract_for_mode(
                "standard_visit",
                profiles=malformed,
            )

    def test_ready_delivery_contract_requires_current_approved_selected_formal_artifact(self):
        total = VALIDATOR.Document(
            Path("/tmp/total.md"),
            "",
            {"business_mode": "standard_visit", "ready_for_use": "true"},
            """\
| 模块 | selected_in_run | run_action |
|---|---|---|
| 交流策略 | true | updated |
""",
        )
        strategy = VALIDATOR.Document(
            Path("/tmp/strategy.md"),
            "",
            {
                "artifact_type": "visit_strategy",
                "module_status": "completed",
                "freshness_status": "current",
                "review_status": "approved",
            },
            "",
        )
        issues: list[object] = []
        VALIDATOR.validate_workspace_delivery_contract(
            {"comprehensive_report": total, "visit_strategy": strategy},
            total,
            self.config["profiles"]["standard_visit"],
            issues,
            strict=False,
        )
        self.assertFalse(issues, issues)

        unapproved = VALIDATOR.Document(
            strategy.path,
            "",
            {**strategy.frontmatter, "review_status": "pending"},
            "",
        )
        unapproved_issues: list[object] = []
        VALIDATOR.validate_workspace_delivery_contract(
            {"comprehensive_report": total, "visit_strategy": unapproved},
            total,
            self.config["profiles"]["standard_visit"],
            unapproved_issues,
            strict=False,
        )
        self.assertIn(
            "formal_delivery_not_ready",
            {issue.code for issue in unapproved_issues},
        )

        unselected_total = VALIDATOR.Document(
            total.path,
            "",
            total.frontmatter,
            total.body.replace("| 交流策略 | true | updated |", "| 交流策略 | false | not_called |"),
        )
        unselected_issues: list[object] = []
        VALIDATOR.validate_workspace_delivery_contract(
            {"comprehensive_report": unselected_total, "visit_strategy": strategy},
            unselected_total,
            self.config["profiles"]["standard_visit"],
            unselected_issues,
            strict=False,
        )
        self.assertIn(
            "formal_delivery_unselected",
            {issue.code for issue in unselected_issues},
        )

    def test_formal_strategy_rejects_audit_headings(self):
        clean = VALIDATOR.Document(
            Path("/tmp/formal-strategy.md"),
            "",
            {"artifact_type": "visit_strategy"},
            "## 目标与最小推进动作\n\n业务正文。\n",
        )
        issues: list[object] = []
        VALIDATOR.validate_strategy_delivery_separation(clean, issues)
        self.assertFalse(issues, issues)
        for heading in sorted(VALIDATOR.STRATEGY_AUDIT_HEADINGS):
            with self.subTest(heading=heading):
                mutated = VALIDATOR.Document(
                    clean.path,
                    "",
                    clean.frontmatter,
                    clean.body + f"\n### {heading}\n\n审计正文。\n",
                )
                mutated_issues: list[object] = []
                VALIDATOR.validate_strategy_delivery_separation(mutated, mutated_issues)
                self.assertIn(
                    "strategy_audit_heading_forbidden",
                    {issue.code for issue in mutated_issues},
                )

    def test_mode_transition_and_letter_recipient_rules_are_fail_closed(self):
        contract = (SKILL_ROOT / "references" / "business-modes.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("不得静默跨模式生成会前速览", contract)
        self.assertIn("用户明确确认", contract)
        self.assertIn("重签intake", contract)
        self.assertIn("预检必须阻塞且只问一个对象确认问题", contract)
        self.assertIn("不检索、不初始化、不生成任何业务文件", contract)
        self.assertIn("只有收件对象已锁定", contract)

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
            "| 周期 | action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 调整/停止触发 | CRM/PIMS候选 |",
            template,
        )
        no_go_template = (
            SKILL_ROOT / "assets" / "account-no-go-strategy-template.md"
        ).read_text(encoding="utf-8")
        no_go_reference = (
            SKILL_ROOT / "references" / "subskill-visit-strategy.md"
        ).read_text(encoding="utf-8")
        self.assertIn("- 建议：no_go", no_go_template)
        for mapping in (
            "stop→停止主动投入",
            "archive→归档当前机会",
            "observe→被动观察证据变化",
            "recheck→内部复核机会资格",
        ):
            self.assertIn(mapping, no_go_reference)
        self.assertIn("| none | none |", no_go_template)
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
        self.assertIn(
            "template_by_recommendation",
            self.schema["$defs"]["strategy_variant"]["properties"],
        )
        account_schema = self.schema["$defs"]["strategy_variants"]["properties"]["variants"][
            "properties"
        ]["account_planning"]
        self.assertIn(
            {"required": ["template_by_recommendation"]},
            account_schema["allOf"],
        )
        self.assertIn("delivery_contract", self.schema["$defs"]["profile"]["required"])
        self.assertEqual(
            self.schema["$defs"]["delivery_contract"]["properties"]["audit_artifact"],
            {"const": "comprehensive_report"},
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
        with mock.patch.object(
            VALIDATOR,
            "load_business_profiles",
            return_value=self.config["profiles"],
        ):
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
        with mock.patch.object(
            VALIDATOR,
            "load_business_profiles",
            return_value=self.config["profiles"],
        ):
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
