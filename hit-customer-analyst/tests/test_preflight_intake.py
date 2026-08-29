from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.common import SKILL_ROOT, SCRIPTS, bind_intake_payload, load_module, run_python


preflight = load_module(
    "discovery_call_preflight_intake",
    SCRIPTS / "preflight_intake.py",
)
NOW = datetime(2026, 8, 27, 1, 0, 0, tzinfo=timezone.utc)


def candidate(
    candidate_id: str,
    value,
    source_ref: str,
    status: str = "asserted",
    *,
    mention_ids: list[str] | None = None,
) -> dict:
    result = {
        "candidate_id": candidate_id,
        "value": value,
        "status": status,
        "source_ref": source_ref,
    }
    if mention_ids is not None:
        result["mention_ids"] = mention_ids
    return result


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
                "organization_scope",
                candidate("scope-a", "澳门协和医院主院区", "客户范围字段A"),
                candidate("scope-b", "澳门协和医院分院区", "客户范围字段B"),
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


def signed_mention(
    raw_text: str,
    surface: str,
    slot: str,
    normalized_value,
    *,
    occurrence: int = 1,
    candidate_field: str | None = None,
    assertion_status: str = "asserted",
) -> dict:
    start = -1
    offset = 0
    for _ in range(occurrence):
        start = raw_text.index(surface, offset)
        offset = start + len(surface)
    result = {
        "mention_id": f"mention-{slot}-{occurrence}-{start}",
        "semantic_slot": slot,
        "source_event_id": "test-user-event-001",
        "char_start": start,
        "char_end": start + len(surface),
        "surface_sha256": hashlib.sha256(surface.encode("utf-8")).hexdigest(),
        "normalized_value": normalized_value,
        "assertion_status": assertion_status,
        "source_ref": f"test:user-turn:1#chars={start}-{start + len(surface)}",
    }
    if candidate_field is not None:
        result["candidate_field"] = candidate_field
    return result


def signed_base_visit_mentions(raw_text: str) -> list[dict]:
    return [
        signed_mention(
            raw_text,
            "澳门协和医院",
            "organization",
            "澳门协和医院",
            candidate_field="customer_name",
        ),
        signed_mention(
            raw_text,
            "孙国强",
            "person",
            "孙国强",
            candidate_field="target_person",
        ),
        signed_mention(
            raw_text,
            "确认年度数字化建设重点",
            "visit_objective",
            "确认年度数字化建设重点",
            candidate_field="visit_objective",
        ),
        signed_mention(
            raw_text,
            "安排下一次专题交流",
            "minimum_next_step",
            "安排下一次专题交流",
            candidate_field="minimum_next_step",
        ),
    ]


def omitted_macao_intake() -> tuple[dict, str, list[dict]]:
    raw_text = (
        "客户：北京协和医院\n"
        "拜访对象：孙国强副院长\n"
        "拜访时间：2026-09-10T10:00:00+08:00\n"
        "背景：已与澳门协和医院孙国强副院长约定2026-09-12T14:00:00+08:00交流\n"
        "目标：了解科研信息化、医学人工智能和临床数据应用重点，争取确定专题需求交流。\n"
    )
    payload = {
        "schema": "discovery-call-intake/v2",
        "request_id": "p0-bj-macao-001",
        "business_mode": "standard_visit",
        "candidate_sets": [
            candidate_set("customer_name", candidate("customer-bj", "北京协和医院", "用户字段：客户")),
            candidate_set("organization_scope", candidate("scope-bj", "北京协和医院", "用户字段：客户")),
            candidate_set("target_person", candidate("person-sun", "孙国强", "用户字段：拜访对象")),
            candidate_set("target_role", candidate("role-vp", "副院长", "用户字段：拜访对象")),
            candidate_set("meeting_status", candidate("status-confirmed", "confirmed", "用户给出确切时间")),
            candidate_set(
                "meeting_time",
                candidate(
                    "time-bj",
                    {
                        "start": "2026-09-10T10:00:00+08:00",
                        "end": "2026-09-10T11:00:00+08:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "用户字段：拜访时间",
                ),
            ),
            candidate_set("visit_objective", candidate("objective-1", "了解科研信息化重点", "用户字段：目标")),
            candidate_set("minimum_next_step", candidate("step-1", "确定专题需求交流", "用户字段：目标")),
        ],
        "confirmations": [],
    }
    mentions = [
        signed_mention(raw_text, "北京协和医院", "organization", "北京协和医院"),
        signed_mention(raw_text, "澳门协和医院", "organization", "澳门协和医院"),
        signed_mention(raw_text, "孙国强", "person", "孙国强", occurrence=1),
        signed_mention(raw_text, "孙国强", "person", "孙国强", occurrence=2),
        signed_mention(raw_text, "副院长", "role", "副院长", occurrence=1),
        signed_mention(raw_text, "副院长", "role", "副院长", occurrence=2),
        signed_mention(
            raw_text,
            "2026-09-10T10:00:00+08:00",
            "meeting_time",
            {"start": "2026-09-10T10:00:00+08:00", "timezone": "Asia/Shanghai"},
        ),
        signed_mention(
            raw_text,
            "2026-09-12T14:00:00+08:00",
            "meeting_time",
            {"start": "2026-09-12T14:00:00+08:00", "timezone": "Asia/Shanghai"},
        ),
    ]
    return payload, raw_text, mentions


class IntakePreflightBehaviorTests(unittest.TestCase):
    def test_N68_signed_raw_second_organization_and_time_cannot_be_omitted(self):
        observed: list[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]] = []
        for repetition in range(3):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                payload, raw_text, mentions = omitted_macao_intake()
                intake_path = bind_intake_payload(
                    root / "intake.json",
                    payload,
                    raw_text=raw_text,
                    mentions=mentions,
                )
                before = {
                    str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                result = run_python("preflight_intake.py", [str(intake_path)])
                self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
                output = json.loads(result.stdout)
                self.assertEqual(output["status"], "blocked")
                self.assertFalse(output["safe_to_initialize_or_search"])
                self.assertNotIn("expires_at", output)
                self.assertNotIn("queries", output)
                uncovered = {
                    (item["semantic_slot"], str(item["normalized_value"]))
                    for conflict in output["blocking_conflicts"]
                    if conflict.get("code") == "raw_mentions_unrepresented"
                    for item in conflict.get("mentions", [])
                }
                self.assertTrue(any(slot == "organization" and "澳门协和医院" in value for slot, value in uncovered))
                self.assertTrue(any(slot == "meeting_time" and "2026-09-12" in value for slot, value in uncovered))
                observed.append(
                    (
                        output["status"],
                        tuple(sorted(str(item.get("code", "")) for item in output["blocking_conflicts"])),
                        tuple(sorted(uncovered)),
                    )
                )

                output_root = root / "output"
                initialized = run_python(
                    "init_workspace.py",
                    [
                        "北京协和医院",
                        "--output-root", str(output_root),
                        "--task-timezone", "Asia/Shanghai",
                        "--runtime-owner", "测试负责人",
                        "--business-mode", "standard_visit",
                        "--intake-input", str(intake_path),
                        "--json",
                    ],
                )
                self.assertEqual(initialized.returncode, 2)
                self.assertIn("intake_preflight_blocked", initialized.stderr)
                self.assertFalse(output_root.exists())

                planned = run_python(
                    "research_plan.py",
                    [
                        "plan",
                        "--workspace", str(root / "candidate"),
                        "--source-workspace", str(root / "source"),
                        "--business-mode", "standard_visit",
                        "--context-id", "dcx-20260827-Abcd1234",
                        "--run-id", "dcr-20260827T040000-Ab12",
                        "--customer-name", "北京协和医院",
                        "--customer-id", "customer.beijing",
                        "--organization-scope", "北京协和医院",
                        "--intake-input", str(intake_path),
                    ],
                )
                self.assertEqual(planned.returncode, 2)
                self.assertIn("intake_preflight_blocked", planned.stderr)
                self.assertFalse((root / "candidate").exists())
                self.assertFalse((root / "source").exists())
                after = {
                    str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
        self.assertEqual(len(observed), 3)
        self.assertEqual(observed, [observed[0]] * 3)

    def test_N69_signed_meeting_cancellation_cannot_be_omitted(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "会议状态：已确认，会议时间：2026-09-10T10:00:00+08:00\n"
            "补充：该会议已取消，请不要按已确认拜访准备。\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        payload = base_visit_intake()
        payload["candidate_sets"].extend(
            [
                candidate_set(
                    "meeting_status",
                    candidate("status-confirmed", "confirmed", "用户字段：会议状态"),
                ),
                candidate_set(
                    "meeting_time",
                    candidate(
                        "time-confirmed",
                        {
                            "start": "2026-09-10T10:00:00+08:00",
                            "end": "2026-09-10T11:00:00+08:00",
                            "timezone": "Asia/Shanghai",
                        },
                        "用户字段：会议时间",
                    ),
                ),
            ]
        )
        mentions = [
            signed_mention(raw_text, "澳门协和医院", "organization", "澳门协和医院"),
            signed_mention(raw_text, "孙国强", "person", "孙国强"),
            signed_mention(raw_text, "已确认", "meeting_status", "confirmed", occurrence=1),
            signed_mention(raw_text, "已取消", "meeting_status", "none"),
            signed_mention(
                raw_text,
                "2026-09-10T10:00:00+08:00",
                "meeting_time",
                {"start": "2026-09-10T10:00:00+08:00", "timezone": "Asia/Shanghai"},
            ),
            signed_mention(raw_text, "确认年度数字化建设重点", "visit_objective", "确认年度数字化建设重点"),
            signed_mention(raw_text, "安排下一次专题交流", "minimum_next_step", "安排下一次专题交流"),
        ]
        mentions[2]["assertion_status"] = "superseded"
        observed: list[tuple[str, tuple[str, ...]]] = []
        for repetition in range(3):
            with self.subTest(repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                intake_path = bind_intake_payload(
                    root / "intake.json",
                    json.loads(json.dumps(payload, ensure_ascii=False)),
                    raw_text=raw_text,
                    mentions=json.loads(json.dumps(mentions, ensure_ascii=False)),
                )
                result = run_python("preflight_intake.py", [str(intake_path)])
                self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
                output = json.loads(result.stdout)
                self.assertFalse(output["safe_to_initialize_or_search"])
                self.assertNotIn("expires_at", output)
                codes = tuple(sorted(str(item.get("code", "")) for item in output["blocking_conflicts"]))
                self.assertIn("raw_mentions_unrepresented", codes)
                self.assertIn("candidate_without_signed_occurrence", codes)
                observed.append((output["status"], codes))
        self.assertEqual(len(observed), 3)
        self.assertEqual(observed, [observed[0]] * 3)

    def test_N70_shorter_entity_or_role_cannot_cover_distinct_signed_occurrences(self):
        cases = (
            (
                "organization",
                "客户可能是北京协和医院或澳门协和医院。\n拜访对象：孙国强\n拜访目标：确认年度数字化建设重点\n最小下一步：安排下一次专题交流\n",
                "协和医院",
                ("北京协和医院", "澳门协和医院"),
            ),
            (
                "role",
                "客户：澳门协和医院\n拜访对象：孙国强，职务可能是院长或副院长。\n拜访目标：确认年度数字化建设重点\n最小下一步：安排下一次专题交流\n",
                "院长",
                ("院长", "副院长"),
            ),
        )
        for repetition in range(3):
            for slot, raw_text, shortened, surfaces in cases:
                with self.subTest(repetition=repetition, slot=slot), tempfile.TemporaryDirectory() as temporary:
                    payload = base_visit_intake()
                    if slot == "organization":
                        payload["candidate_sets"][0]["candidates"][0]["value"] = shortened
                    else:
                        payload["candidate_sets"].append(
                            candidate_set("target_role", candidate("role-short", shortened, "用户字段：对象"))
                        )
                    mentions = [
                        signed_mention(raw_text, "确认年度数字化建设重点", "visit_objective", "确认年度数字化建设重点"),
                        signed_mention(raw_text, "安排下一次专题交流", "minimum_next_step", "安排下一次专题交流"),
                    ]
                    if slot == "organization":
                        mentions.append(signed_mention(raw_text, "孙国强", "person", "孙国强"))
                    else:
                        mentions.extend(
                            [
                                signed_mention(raw_text, "澳门协和医院", "organization", "澳门协和医院"),
                                signed_mention(raw_text, "孙国强", "person", "孙国强"),
                            ]
                        )
                    for occurrence, surface in enumerate(surfaces, 1):
                        mentions.append(
                            signed_mention(
                                raw_text,
                                surface,
                                slot,
                                surface,
                                occurrence=1,
                            )
                        )
                    intake_path = bind_intake_payload(
                        Path(temporary) / "intake.json",
                        payload,
                        raw_text=raw_text,
                        mentions=mentions,
                    )
                    result = run_python("preflight_intake.py", [str(intake_path)])
                    self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
                    output = json.loads(result.stdout)
                    self.assertFalse(output["safe_to_initialize_or_search"])
                    self.assertTrue(
                        any(
                            item.get("code") in {"raw_mentions_unrepresented", "candidate_without_signed_occurrence"}
                            for item in output["blocking_conflicts"]
                        )
                    )

    def test_N71_signed_uncertain_mention_cannot_be_upgraded_to_asserted(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "职务：可能是院长\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        role_mention = signed_mention(
            raw_text,
            "院长",
            "role",
            "院长",
            candidate_field="target_role",
            assertion_status="uncertain",
        )
        payload = base_visit_intake()
        payload["candidate_sets"].append(
            candidate_set(
                "target_role",
                candidate(
                    "role-asserted",
                    "院长",
                    "模型从不确定原话升级",
                    mention_ids=[role_mention["mention_id"]],
                ),
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            intake_path = bind_intake_payload(
                Path(temporary) / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=[*signed_base_visit_mentions(raw_text), role_mention],
            )
            result = run_python("preflight_intake.py", [str(intake_path)])
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertFalse(output["safe_to_initialize_or_search"])
        conflicts = {item["code"]: item for item in output["blocking_conflicts"]}
        self.assertIn("raw_mentions_unrepresented", conflicts)
        self.assertIn("candidate_without_signed_occurrence", conflicts)
        reasons = {
            error["reason"]
            for item in conflicts["candidate_without_signed_occurrence"]["candidates"]
            for error in item["binding_errors"]
        }
        self.assertIn("assertion_status_mismatch", reasons)

    def test_N72_signed_explicit_unknown_cannot_be_upgraded_to_asserted(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "职务：不知道\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        role_mention = signed_mention(
            raw_text,
            "不知道",
            "role",
            None,
            candidate_field="target_role",
            assertion_status="explicit_unknown",
        )
        payload = base_visit_intake()
        payload["candidate_sets"].append(
            candidate_set(
                "target_role",
                candidate(
                    "role-invented",
                    "院长",
                    "模型补造未知职务",
                    mention_ids=[role_mention["mention_id"]],
                ),
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            intake_path = bind_intake_payload(
                Path(temporary) / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=[*signed_base_visit_mentions(raw_text), role_mention],
            )
            result = run_python("preflight_intake.py", [str(intake_path)])
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertFalse(output["safe_to_initialize_or_search"])
        conflicts = {item["code"]: item for item in output["blocking_conflicts"]}
        self.assertIn("raw_mentions_unrepresented", conflicts)
        self.assertIn("candidate_without_signed_occurrence", conflicts)
        reasons = {
            error["reason"]
            for item in conflicts["candidate_without_signed_occurrence"]["candidates"]
            for error in item["binding_errors"]
        }
        self.assertIn("assertion_status_mismatch", reasons)

    def test_N73_one_signed_mention_cannot_bind_multiple_candidate_fields(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "职务：信息中心主任\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        role_mention = signed_mention(
            raw_text,
            "信息中心主任",
            "role",
            "信息中心主任",
            candidate_field="target_role",
        )
        reused_id = role_mention["mention_id"]
        payload = base_visit_intake()
        payload["candidate_sets"].extend(
            [
                candidate_set(
                    "target_role",
                    candidate(
                        "role-director",
                        "信息中心主任",
                        "用户原话：职务",
                        mention_ids=[reused_id],
                    ),
                ),
                candidate_set(
                    "target_contact_level",
                    candidate(
                        "level-director",
                        "信息中心主任",
                        "模型复用同一提及",
                        mention_ids=[reused_id],
                    ),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            intake_path = bind_intake_payload(
                Path(temporary) / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=[*signed_base_visit_mentions(raw_text), role_mention],
            )
            result = run_python("preflight_intake.py", [str(intake_path)])
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertFalse(output["safe_to_initialize_or_search"])
        conflicts = {item["code"]: item for item in output["blocking_conflicts"]}
        self.assertIn("signed_mention_reused", conflicts)
        self.assertEqual(
            {claim["field"] for claim in conflicts["signed_mention_reused"]["mentions"][0]["candidate_claims"]},
            {"target_role", "target_contact_level"},
        )
        self.assertIn("candidate_without_signed_occurrence", conflicts)

    def test_N74_signed_start_only_time_cannot_authorize_model_supplied_end(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "拜访时间：2026-09-10T10:00:00+08:00\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        time_mention = signed_mention(
            raw_text,
            "2026-09-10T10:00:00+08:00",
            "meeting_time",
            {
                "start": "2026-09-10T10:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
            candidate_field="meeting_time",
        )
        payload = base_visit_intake()
        payload["candidate_sets"].append(
            candidate_set(
                "meeting_time",
                candidate(
                    "time-invented-end",
                    {
                        "start": "2026-09-10T10:00:00+08:00",
                        "end": "2026-09-10T11:00:00+08:00",
                        "timezone": "Asia/Shanghai",
                    },
                    "模型补造结束时间",
                    mention_ids=[time_mention["mention_id"]],
                ),
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            intake_path = bind_intake_payload(
                Path(temporary) / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=[*signed_base_visit_mentions(raw_text), time_mention],
            )
            result = run_python("preflight_intake.py", [str(intake_path)])
        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertFalse(output["safe_to_initialize_or_search"])
        conflicts = {item["code"]: item for item in output["blocking_conflicts"]}
        self.assertIn("raw_mentions_unrepresented", conflicts)
        self.assertIn("candidate_without_signed_occurrence", conflicts)
        reasons = {
            error["reason"]
            for item in conflicts["candidate_without_signed_occurrence"]["candidates"]
            for error in item["binding_errors"]
        }
        self.assertIn("normalized_value_mismatch", reasons)

    def test_N75_exact_field_and_mention_id_bindings_remain_ready(self):
        raw_text = (
            "客户：澳门协和医院\n"
            "拜访对象：孙国强\n"
            "拜访目标：确认年度数字化建设重点\n"
            "最小下一步：安排下一次专题交流\n"
        )
        mentions = signed_base_visit_mentions(raw_text)
        payload = base_visit_intake()
        mention_ids_by_field = {
            str(item["candidate_field"]): [str(item["mention_id"])] for item in mentions
        }
        for candidate_set_value in payload["candidate_sets"]:
            field = str(candidate_set_value["field"])
            candidate_set_value["candidates"][0]["mention_ids"] = mention_ids_by_field[field]
        with tempfile.TemporaryDirectory() as temporary:
            intake_path = bind_intake_payload(
                Path(temporary) / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=mentions,
            )
            result = run_python("preflight_intake.py", [str(intake_path)])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ready")
        self.assertTrue(output["safe_to_initialize_or_search"])
        ledger = {item["candidate_field"]: item for item in output["request_mention_ledger"]}
        self.assertEqual(set(ledger), set(mention_ids_by_field))
        self.assertTrue(all(item["candidate_ids"] for item in ledger.values()))

    def test_N67_signed_ledger_omission_and_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload, raw_text, mentions = omitted_macao_intake()
            incomplete = [
                item
                for item in mentions
                if not (
                    item["semantic_slot"] == "organization"
                    and item["normalized_value"] == "澳门协和医院"
                )
            ]
            intake_path = bind_intake_payload(
                root / "intake.json",
                payload,
                raw_text=raw_text,
                mentions=incomplete,
            )
            invalid = run_python("preflight_intake.py", [str(intake_path)])
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("mention ledger遗漏", invalid.stderr)

            payload, raw_text, mentions = omitted_macao_intake()
            intake_path = bind_intake_payload(
                root / "duplicate.json",
                payload,
                raw_text=raw_text,
                mentions=mentions,
            )
            source = intake_path.read_text(encoding="utf-8")
            source = source.replace('"candidate_sets":', '"candidate_sets": [], "candidate_sets":', 1)
            intake_path.write_text(source, encoding="utf-8")
            duplicate = run_python("preflight_intake.py", [str(intake_path)])
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn("重复字段", duplicate.stderr)

            payload, raw_text, mentions = omitted_macao_intake()
            intake_path = bind_intake_payload(
                root / "trust.json",
                payload,
                raw_text=raw_text,
                mentions=mentions,
            )
            missing_trust = run_python(
                "preflight_intake.py",
                [str(intake_path)],
                env={"DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON": ""},
            )
            self.assertEqual(missing_trust.returncode, 2)
            self.assertIn("信任根", missing_trust.stderr)

            binding = json.loads(intake_path.read_text(encoding="utf-8"))["request_binding"]
            receipt_path = intake_path.parent / binding["receipt_file"]
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            current = {
                "request_id": receipt["request_id"],
                "business_mode": receipt["business_mode"],
                "receipt_id": receipt["receipt_id"],
                "request_bundle_id": receipt["request_bundle_id"],
                "request_revision": receipt["request_revision"] + 1,
                "last_user_event_id": receipt["last_user_event_id"],
                "raw_request_sha256": receipt["raw_request_sha256"],
            }
            stale = run_python(
                "preflight_intake.py",
                [str(intake_path)],
                env={"DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON": json.dumps(current)},
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("当前会话头", stale.stderr)

            replacement = "B" if receipt["signature"][0] != "B" else "C"
            receipt["signature"] = replacement + receipt["signature"][1:]
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            tampered = run_python("preflight_intake.py", [str(intake_path)])
            self.assertEqual(tampered.returncode, 2)
            self.assertIn("签名无效", tampered.stderr)

    def test_conflicting_subject_scope_and_time_ask_one_question_without_side_effects(self):
        payload = conflicted_visit_intake()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            intake_path = root / "intake.json"
            bind_intake_payload(intake_path, payload)
            before = {path.relative_to(root) for path in root.rglob("*")}
            result = run_python("preflight_intake.py", [str(intake_path)])
            after = {path.relative_to(root) for path in root.rglob("*")}

        self.assertEqual(result.returncode, 3, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "blocked")
        self.assertFalse(output["safe_to_initialize_or_search"])
        self.assertEqual(
            {item["field"] for item in output["blocking_conflicts"]},
            {"organization_scope", "meeting_time"},
        )
        self.assertEqual(
            output["questions"],
            [
                {
                    "field": "identity_and_date",
                    "question": "请一次性确认唯一客户主体或机构范围，以及唯一会议日期时间；认证宿主核验后重建intake。",
                }
            ],
        )
        self.assertNotIn("queries", output)
        self.assertNotIn("expires_at", output)
        self.assertEqual(before, after, "blocked预检不得创建任何工作目录或运行文件")

    def test_ready_receipt_has_hash_selected_values_and_expiry(self):
        payload = conflicted_visit_intake()
        # 认证宿主核验用户回合后重建intake，只保留已确认候选；模型不得
        # 在原冲突intake中自报confirmed_by=user来选择有利口径。
        for candidate_set_value in payload["candidate_sets"]:
            if candidate_set_value["field"] == "organization_scope":
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
        self.assertEqual(result["selected_values"]["organization_scope"]["values"], ["澳门协和医院分院区"])
        self.assertEqual(result["selected_values"]["meeting_time"]["candidate_ids"], ["time-b"])
        self.assertEqual(
            result["selected_values"]["organization_scope"]["selection_basis"],
            "single_value",
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

    def test_meeting_time_iana_zone_must_match_declared_offset(self):
        payload = base_visit_intake()
        payload["candidate_sets"].append(
            candidate_set(
                "meeting_time",
                candidate(
                    "time-zone-drift",
                    {
                        "start": "2026-09-02T14:00:00+08:00",
                        "end": "2026-09-02T15:00:00+08:00",
                        "timezone": "America/New_York",
                    },
                    "用户字段：拜访时间",
                ),
            )
        )
        with self.assertRaisesRegex(preflight.PreflightError, "timezone与start/end的UTC offset不一致"):
            preflight.evaluate_intake(payload, now=NOW)

    def test_evaluation_does_not_attempt_network_access(self):
        payload = base_visit_intake()
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network access")):
            result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "ready")

    def test_model_cannot_self_confirm_conflict(self):
        payload = conflicted_visit_intake()
        payload["confirmations"] = [
            {
                "field": "organization_scope",
                "selected_candidate_ids": ["scope-b"],
                "allow_multiple": False,
                "confirmed_by": "assistant",
                "confirmed_at": "2026-08-27T08:55:00+08:00",
                "confirmation_ref": "模型判断分院区更可信",
            }
        ]
        with self.assertRaises(preflight.PreflightError):
            preflight.evaluate_intake(payload, now=NOW)

    def test_self_reported_user_confirmation_is_also_rejected(self):
        payload = conflicted_visit_intake()
        payload["confirmations"] = [
            {
                "field": "organization_scope",
                "selected_candidate_ids": ["scope-b"],
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

    def test_letter_without_recipient_asks_only_recipient_question(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-letter-no-recipient",
            "business_mode": "letter",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set("letter_scenario", candidate("scenario-a", "拜访后正式跟进", "用户字段")),
                candidate_set("letter_purpose", candidate("purpose-a", "确认下一次技术交流安排", "用户字段")),
                candidate_set("expected_action", candidate("action-a", "请对方确认九月技术交流时间", "用户字段")),
                candidate_set("signer", candidate("signer-a", "客户负责人", "用户字段")),
                candidate_set("delivery_channel", candidate("channel-a", "正式邮件", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            result["questions"],
            [{"field": "recipient_role", "question": "请确认收件对象的明确角色或正式称谓。"}],
        )

    def test_target_conflict_does_not_add_redundant_missing_target_question(self):
        payload = {
            "schema": "discovery-call-intake/v1",
            "request_id": "req-target-conflict",
            "business_mode": "standard_visit",
            "candidate_sets": [
                candidate_set("customer_name", candidate("customer-a", "甲医院", "用户字段")),
                candidate_set(
                    "target_role",
                    candidate("role-a", "信息中心主任", "字段A"),
                    candidate("role-b", "分管副院长", "字段B"),
                ),
                candidate_set("visit_objective", candidate("goal-a", "确认年度建设重点", "用户字段")),
                candidate_set("minimum_next_step", candidate("step-a", "确认下一次技术交流", "用户字段")),
            ],
            "confirmations": [],
        }
        result = preflight.evaluate_intake(payload, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual([item["field"] for item in result["questions"]], ["target_role"])
        self.assertNotIn(
            "target_identity_or_level",
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
        self.assertIn("mention_ids", schema["$defs"]["candidate"]["required"])

        receipt_schema = json.loads(
            (SKILL_ROOT / "schemas" / "request-binding-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            receipt_schema["properties"]["coverage_policy"]["const"],
            preflight.REQUEST_COVERAGE_POLICY,
        )
        self.assertIn("candidate_field", receipt_schema["$defs"]["mention"]["required"])
        self.assertEqual(
            set(receipt_schema["$defs"]["mention"]["properties"]["candidate_field"]["enum"]),
            preflight.SIGNED_CANDIDATE_FIELDS,
        )

        config = json.loads((SKILL_ROOT / "config" / "business-modes.json").read_text(encoding="utf-8"))
        policy = config["profiles"]["strategic_account"]["strategy_variants"]["meeting_status_policy"]
        self.assertEqual(set(policy["allowed_values"]), preflight.MEETING_STATUSES)
        self.assertEqual(policy["variant_by_status"], preflight.MEETING_STATUS_VARIANTS)
        self.assertEqual(policy["exact_time_without_status"], "scheduled_visit")
        self.assertEqual(set(policy["exact_time_conflicts_with_status"]), {"none", "unknown"})
        self.assertIs(policy["target_and_objective_imply_meeting"], False)


if __name__ == "__main__":
    unittest.main()
