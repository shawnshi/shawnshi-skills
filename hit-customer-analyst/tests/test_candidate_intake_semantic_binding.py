from __future__ import annotations

import unittest
from pathlib import Path

from tests.common import SCRIPTS, load_module


BUILDER = load_module("candidate_intake_semantic_binding", SCRIPTS / "build_candidate.py")


class _Document:
    def __init__(self, frontmatter: dict[str, str]):
        self.frontmatter = frontmatter
        self.path = Path("artifact.md")


def intake(**values: str) -> dict:
    return {
        "selected_values": {
            key: {"values": [value]}
            for key, value in values.items()
        }
    }


class CandidateIntakeSemanticBindingTests(unittest.TestCase):
    def test_standard_visit_rejects_objective_drift_before_candidate_write(self):
        verified = intake(
            target_role="信息中心主任",
            visit_objective="核实年度重点",
            minimum_next_step="确认技术交流",
        )
        live = {
            "visit_strategy": _Document(
                {
                    "strategy_variant": "scheduled_visit",
                    "target_contact_level": "信息中心主任",
                    "visit_objective": "推进采购立项",
                    "minimum_next_step": "确认技术交流",
                }
            )
        }
        with self.assertRaisesRegex(BUILDER.CandidateError, "visit_objective"):
            BUILDER._assert_intake_semantic_binding(
                verified_intake=verified,
                business_mode="standard_visit",
                records={"visit_strategy": {"action": "reused"}},
                live_documents=live,
            )

    def test_account_plan_binds_variant_question_horizon_and_next_step(self):
        verified = intake(
            strategy_variant="account_planning",
            strategic_question="未来90天是否值得投入",
            planning_horizon="90天",
            minimum_next_step="完成机会资格复核",
        )
        live = {
            "visit_strategy": _Document(
                {
                    "strategy_variant": "account_planning",
                    "strategic_question": "未来90天是否值得投入",
                    "planning_horizon": "90天",
                    "minimum_next_step": "完成机会资格复核",
                }
            )
        }
        BUILDER._assert_intake_semantic_binding(
            verified_intake=verified,
            business_mode="strategic_account",
            records={"visit_strategy": {"action": "reused"}},
            live_documents=live,
        )
        live["visit_strategy"].frontmatter["planning_horizon"] = "本财年"
        with self.assertRaisesRegex(BUILDER.CandidateError, "planning_horizon"):
            BUILDER._assert_intake_semantic_binding(
                verified_intake=verified,
                business_mode="strategic_account",
                records={"visit_strategy": {"action": "reused"}},
                live_documents=live,
            )

    def test_letter_recipient_and_action_cannot_drift(self):
        values = {
            "letter_scenario": "拜访后正式跟进",
            "recipient_role": "信息中心主任",
            "letter_purpose": "确认后续安排",
            "expected_action": "确认交流时间",
            "signer": "战略咨询部",
            "delivery_channel": "正式邮件",
        }
        verified = intake(**values)
        live = {"customer_letter_internal": _Document(dict(values))}
        BUILDER._assert_intake_semantic_binding(
            verified_intake=verified,
            business_mode="letter",
            records={"customer_letter_internal": {"action": "reused"}},
            live_documents=live,
        )
        live["customer_letter_internal"].frontmatter["recipient_role"] = "院长"
        with self.assertRaisesRegex(BUILDER.CandidateError, "recipient_role"):
            BUILDER._assert_intake_semantic_binding(
                verified_intake=verified,
                business_mode="letter",
                records={"customer_letter_internal": {"action": "reused"}},
                live_documents=live,
            )


if __name__ == "__main__":
    unittest.main()
