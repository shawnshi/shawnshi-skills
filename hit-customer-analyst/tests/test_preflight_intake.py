from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import SKILL_ROOT, SCRIPTS, load_module, run_python


preflight = load_module(
    "discovery_call_preflight_intake",
    SCRIPTS / "preflight_intake.py",
)
NOW = datetime(2026, 8, 27, 1, 0, 0, tzinfo=timezone.utc)


def candidate(candidate_id: str, value, source_ref: str, status: str = "asserted") -> dict:
    return {
        "candidate_id": candidate_id,
        "value": value,
        "status": status,
        "source_ref": source_ref,
    }


def candidate_set(field: str, *values: dict) -> dict:
    return {"field": field, "candidates": list(values)}


def base_visit_intake() -> dict:
    return {
        "schema": "discovery-call-intake/v1",
        "request_id": "req-standard-001",
        "business_mode": "standard_visit",
        "candidate_sets": [
            candidate_set(
                "customer_name",
                candidate("customer-a", "澳门协和医院", "用户字段：客户"),
            ),
            candidate_set(
                "target_person",
                candidate("person-a", "孙国强", "用户字段：拜访对象"),
            ),
            candidate_set(
                "visit_objective",
                candidate("objective-a", "确认年度数字化建设重点", "用户字段：拜访目标"),
            ),
            candidate_set(
                "minimum_next_step",
                candidate("step-a", "安排下一次专题交流", "用户字段：最小下一步"),
            ),
        ],
        "confirmations": [],
    }


def conflicted_visit_intake() -> dict:
    payload = base_visit_intake()
    payload["candidate_sets"].extend(
        [
            candidate_set(
                "target_role",
                candidate("role-a", "院长", "拜访对象字段A"),
                candidate("role-b", "副院长", "会议邀请字段B"),
            ),
            candidate_set(
                "meeting_time",
                candidate(
                    "time-a",
                    {
                        "start": "2026-09-02T14:00:00+08:00",
                        "end": "2026-09-02T15:00:00+08:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "拜访时间字段A",
                ),
                candidate(
                    "time-b",
                    {
                        "start": "2026-09-03T09:30:00+08:00",
                        "end": "2026-09-03T10:30:00+08:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "行程表字段B",
                ),
            ),
        ]
    )
    return payload


class IntakePreflightBehaviorTests(unittest.TestCase):
    def test_conflicting_role_and_time_block_without_workspace_or_search(self):
        payload = conflicted_visit_intake()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake_path = root / "intake.json"
            intake_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            before = {path.relative_to(root) for path in root.rglob("*")}
            result = run_python("preflight_intake.py", [str(intake_path)])
            after = {path.relative_to(root) for path in root.rglob("*")}

        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "blocked")
        self.assertFalse(output["safe_to_initialize_or_search"])
        self.assertEqual(
            {item["field"] for item in output["blocking_conflicts"]},
            {"target_role", "meeting_time"},
        )
        self.assertEqual([item["field"] for item in output["questions"]], ["target_role", "meeting_time"])
        self.assertNotIn("queries", output)
        self.assertNotIn("expires_at", output)
        self.assertEqual(before, after, "blocked预检不得创建任何工作目录或运行文件")

    def test_ready_receipt_has_hash_selected_values_and_expiry(self):
        payload = conflicted_visit_intake()
        # 认证宿主核验用户回合后重建intake，只保留已确认候选；模型不得
        # 在原冲突intake中自报confirmed_by=user来选择有利口径。
        for candidate_set_value in payload["candidate_sets"]:
            if candidate_set_value["field"] == "target_role":
                candidate_set_value["candidates"] = [candidate_set_value["candidates"][1]]
            if candidate_set_value["field"] == "meeting_time":
                candidate_set_value["candidates"] = [candidate_set_value["candidates"][1]]
        result = preflight.evaluate_intake(payload, now=NOW, ttl_seconds=900)

        expected_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["safe_to_initialize_or_search"])
        self.assertEqual(result["input_sha256"], expected_hash)
        self.assertEqual(result["expires_at"], "2026-08-27T01:15:00Z")
        self.assertEqual(result["selected_values"]["target_role"]["values"], ["副院长"])
        self.assertEqual(result["selected_values"]["meeting_time"]["candidate_ids"], ["time-b"])
        self.assertEqual(
            result["selected_values"]["organization_scope"]["selection_basis"],
            "default_from_customer_name",
        )
        self.assertFalse(result["blocking_conflicts"])
        self.assertFalse(result["questions"])

    def test_equivalent_values_and_timezones_do_not_create_false_conflict(self):
        payload = base_visit_intake()
        payload["candidate_sets"].extend(
            [
                candidate_set(
                    "target_role",
                    candidate("role-a", "副院长", "字段A"),
                    candidate("role-b", "  副院长  ", "字段B"),
                ),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-a",
                        {
                            "start": "2026-09-02T14:00:00+08:00",
                            "end": "2026-09-02T15:00:00+08:00",
                        },
                        "字段A",
                    ),
                    candidate(
                        "time-b",
                        {
                            "start": "2026-09-02T06:00:00Z",
                            "end": "2026-09-02T07:00:00Z",
                        },
                        "字段B",
                    ),
                ),
            ]
        )
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(set(result["selected_values"]["target_role"]["candidate_ids"]), {"role-a", "role-b"})
        self.assertEqual(set(result["selected_values"]["meeting_time"]["candidate_ids"]), {"time-a", "time-b"})

    def test_evaluation_does_not_attempt_network_access(self):
        payload = base_visit_intake()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network access")):
            result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "ready")

    def test_model_cannot_self_confirm_conflict(self):
        payload = conflicted_visit_intake()
        payload["confirmations"] = [
            {
                "field": "target_role",
                "selected_candidate_ids": ["role-b"],
                "allow_multiple": False,
                "confirmed_by": "assistant",
                "confirmed_at": "2026-08-27T08:55:00+08:00",
                "confirmation_ref": "模型判断副院长更可信",
            }
        ]
        with self.assertRaises(preflight.PreflightError):
            preflight.evaluate_intake(payload, now=NOW)

    def test_self_reported_user_confirmation_is_also_rejected(self):
        payload = conflicted_visit_intake()
        payload["confirmations"] = [
            {
                "field": "target_role",
                "selected_candidate_ids": ["role-b"],
                "allow_multiple": False,
                "confirmed_by": "user",
                "confirmed_at": "2026-08-27T08:55:00+08:00",
                "confirmation_ref": "fabricated:user-turn:999",
            }
        ]
        with self.assertRaisesRegex(preflight.PreflightError, "可信宿主"):
            preflight.evaluate_intake(payload, now=NOW)

    def test_strategic_variant_is_derived_from_confirmed_meeting_facts(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-strategy-meeting",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("target_role", candidate("role-a", "信息中心主任", "用户字段")),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-a",
                        {"start": "2026-09-02T14:00:00+08:00", "end": "2026-09-02T15:00:00+08:00"},
                        "会议邀请",
                    ),
                ),
                candidate_set("visit_objective", candidate("goal-a", "确认年度建设重点", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "安排专题交流", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        variant = result["selected_values"]["strategy_variant"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(variant["values"], ["scheduled_visit"])
        self.assertEqual(variant["selection_basis"], "derived_from_exact_meeting_time")
        self.assertIn("time-a", variant["candidate_ids"])

    def test_confirmed_meeting_with_unknown_time_still_selects_scheduled_visit(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-confirmed-time-unknown",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("meeting_status", candidate("status-a", "confirmed", "用户原话：会议已确认")),
                candidate_set(
                    "meeting_time",
                    candidate("time-unknown", None, "用户原话：具体时间待定", "explicit_unknown"),
                ),
                candidate_set("target_role", candidate("role-a", "信息中心主任", "用户字段")),
                candidate_set("visit_objective", candidate("goal-a", "确认年度建设重点", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "安排专题交流", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        variant = result["selected_values"]["strategy_variant"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(variant["values"], ["scheduled_visit"])
        self.assertEqual(variant["selection_basis"], "derived_from_confirmed_meeting_status")
        self.assertIn("status-a", variant["candidate_ids"])
        self.assertIn("time-unknown", variant["candidate_ids"])

    def test_tentative_meeting_stays_account_planning_even_with_proposed_time(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-tentative-meeting",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("meeting_status", candidate("status-a", "tentative", "用户原话：暂定")),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-a",
                        {"start": "2026-09-02T14:00:00+08:00", "end": "2026-09-02T15:00:00+08:00"},
                        "用户原话：拟定时间",
                    ),
                ),
                candidate_set("target_role", candidate("role-a", "信息中心主任", "用户字段")),
                candidate_set("visit_objective", candidate("goal-a", "了解年度建设重点", "用户字段")),
                candidate_set("strategic_question", candidate("question-a", "未来90天是否继续投入", "用户字段")),
                candidate_set("planning_horizon", candidate("horizon-a", "90天", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "确认会议是否成立", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        variant = result["selected_values"]["strategy_variant"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(variant["values"], ["account_planning"])
        self.assertEqual(variant["selection_basis"], "derived_from_tentative_meeting_status")

    def test_none_and_unknown_without_exact_time_select_account_planning(self):
        for meeting_status in ("none", "unknown"):
            with self.subTest(meeting_status=meeting_status):
                payload = {
                    "schema": "discovery-call-intake/v1",
                    "request_id": f"req-{meeting_status}-meeting",
                    "business_mode": "strategic_account",
                    "candidate_sets": [
                        candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                        candidate_set("meeting_status", candidate("status-a", meeting_status, "用户字段")),
                        candidate_set("strategic_question", candidate("question-a", "未来90天是否继续投入", "用户字段")),
                        candidate_set("planning_horizon", candidate("horizon-a", "90天", "用户字段")),
                        candidate_set("minimum_next_step", candidate("step-a", "完成机会资格复核", "用户字段")),
                    ],
                    "confirmations": [],
                }
                result = preflight.evaluate_intake(payload, now=NOW)
                self.assertEqual(result["status"], "ready")
                variant = result["selected_values"]["strategy_variant"]
                self.assertEqual(variant["values"], ["account_planning"])
                self.assertEqual(variant["selection_basis"], "derived_from_nonmeeting_status")

    def test_none_or_unknown_with_exact_time_blocks_as_cross_field_conflict(self):
        for meeting_status in ("none", "unknown"):
            with self.subTest(meeting_status=meeting_status):
                payload = {
                    "schema": "discovery-call-intake/v1",
                    "request_id": f"req-{meeting_status}-time-conflict",
                    "business_mode": "strategic_account",
                    "candidate_sets": [
                        candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                        candidate_set("meeting_status", candidate("status-a", meeting_status, "用户字段")),
                        candidate_set(
                            "meeting_time",
                            candidate(
                                "time-a",
                                {"start": "2026-09-02T14:00:00+08:00", "end": "2026-09-02T15:00:00+08:00"},
                                "会议邀请",
                            ),
                        ),
                        candidate_set("strategic_question", candidate("question-a", "未来90天是否继续投入", "用户字段")),
                        candidate_set("planning_horizon", candidate("horizon-a", "90天", "用户字段")),
                        candidate_set("minimum_next_step", candidate("step-a", "完成机会资格复核", "用户字段")),
                    ],
                    "confirmations": [],
                }
                result = preflight.evaluate_intake(payload, now=NOW)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(
                    "meeting_status_time_conflict",
                    {item["code"] for item in result["blocking_conflicts"]},
                )

    def test_meeting_status_must_use_asserted_enum(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-invalid-meeting-status",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set(
                    "meeting_status",
                    candidate("status-a", None, "用户原话：不知道", "explicit_unknown"),
                ),
            ],
            "confirmations": [],
        }
        with self.assertRaisesRegex(preflight.PreflightError, "meeting_status"):
            preflight.evaluate_intake(payload, now=NOW)

    def test_strategic_variant_defaults_to_account_without_meeting(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-strategy-account",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("strategic_question", candidate("question-a", "未来90天是否继续投入", "用户字段")),
                candidate_set("planning_horizon", candidate("horizon-a", "90天", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "完成机会资格复核", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        variant = result["selected_values"]["strategy_variant"]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(variant["values"], ["account_planning"])
        self.assertEqual(variant["selection_basis"], "default_without_confirmed_meeting")

    def test_explicit_strategy_variant_conflicting_with_meeting_facts_blocks(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-strategy-conflict",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("strategy_variant", candidate("variant-a", "account_planning", "模型派生字段")),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-a",
                        {"start": "2026-09-01T08:00:00Z", "end": "2026-09-01T09:00:00Z"},
                        "会议邀请",
                    ),
                ),
                candidate_set("target_role", candidate("role-a", "信息中心主任", "用户字段")),
                candidate_set("visit_objective", candidate("goal-a", "确认年度建设重点", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "安排专题交流", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "strategy_variant_fact_conflict",
            {item["code"] for item in result["blocking_conflicts"]},
        )

    def test_target_and_objective_without_meeting_do_not_imply_scheduled_visit(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-strategy-no-meeting",
            "business_mode": "strategic_account",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("target_role", candidate("role-a", "信息中心主任", "用户字段")),
                candidate_set("visit_objective", candidate("goal-a", "了解年度建设重点", "用户字段")),
                candidate_set("strategic_question", candidate("question-a", "未来90天是否继续投入", "用户字段")),
                candidate_set("planning_horizon", candidate("horizon-a", "90天", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "完成机会资格复核", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "ready")
        variant = result["selected_values"]["strategy_variant"]
        self.assertEqual(variant["values"], ["account_planning"])
        self.assertEqual(variant["selection_basis"], "default_without_confirmed_meeting")

    def test_letter_requires_all_configured_business_fields(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-letter",
            "business_mode": "letter",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("recipient_role", candidate("recipient-a", "信息中心主任", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            {"letter_scenario", "letter_purpose", "expected_action", "signer", "delivery_channel"},
            {item["field"] for item in result["missing_requirements"]},
        )

    def test_missing_target_blocks_and_questions_never_exceed_three(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "business_mode": "briefing",
            "candidate_sets": [
                candidate_set(
                    "customer_name",
                    candidate("customer-a", "甲医院", "字段A"),
                    candidate("customer-b", "乙医院", "字段B"),
                ),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-a",
                        {"start": "2026-09-01T08:00:00Z", "end": "2026-09-01T09:00:00Z"},
                        "字段A",
                    ),
                    candidate(
                        "time-b",
                        {"start": "2026-09-02T08:00:00Z", "end": "2026-09-02T09:00:00Z"},
                        "字段B",
                    ),
                ),
                candidate_set(
                    "visit_objective",
                    candidate("goal-a", "讨论科研", "字段A"),
                    candidate("goal-b", "讨论采购", "字段B"),
                ),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertLessEqual(len(result["questions"]), 3)
        self.assertGreaterEqual(result["unasked_blocker_count"], 1)
        self.assertIn("target_identity_or_level", {item["field"] for item in result["missing_requirements"]})

    def test_explicit_unknown_is_preserved_without_guessing(self):
        payload = base_visit_intake()
        payload["candidate_sets"].append(
            candidate_set(
                "meeting_time",
                candidate("time-unknown", None, "用户原话：时间待确认", "explicit_unknown"),
            )
        )
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["selected_values"]["meeting_time"]["values"], [None])
        self.assertEqual(result["selected_values"]["meeting_time"]["selection_basis"], "single_value")


class IntakePreflightContractTests(unittest.TestCase):
    def test_schema_is_valid_json_and_matches_runtime_contract(self):
        schema_path = SKILL_ROOT / "schemas" / "intake-preflight.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema"]["const"], preflight.INPUT_SCHEMA)
        self.assertEqual(
            set(schema["properties"]["business_mode"]["enum"]),
            preflight.BUSINESS_MODES,
        )
        self.assertTrue(preflight.SUPPORTED_FIELDS <= set(schema["$defs"]["field"]["enum"]))
        self.assertEqual(schema["properties"]["confirmations"]["maxItems"], 0)

        config = json.loads((SKILL_ROOT / "config" / "business-modes.json").read_text(encoding="utf-8"))
        policy = config["profiles"]["strategic_account"]["strategy_variants"]["meeting_status_policy"]
        self.assertEqual(set(policy["allowed_values"]), preflight.MEETING_STATUSES)
        self.assertEqual(policy["variant_by_status"], preflight.MEETING_STATUS_VARIANTS)
        self.assertEqual(policy["exact_time_without_status"], "scheduled_visit")
        self.assertEqual(set(policy["exact_time_conflicts_with_status"]), {"none", "unknown"})
        self.assertIs(policy["target_and_objective_imply_meeting"], False)


if __name__ == "__main__":
    unittest.main()
