#!/usr/bin/env python3
"""Deterministic, side-effect-free intake disambiguation for discovery-call.

The script deliberately does not create a customer workspace, build a search
plan, access the network, or select between conflicting user-provided values.
It turns structured candidate occurrences into either:

* a short-lived ``ready`` receipt containing the exact selected values; or
* a ``blocked`` result containing only the questions that must be answered
  before initialization or research begins.

Exit codes:

* 0: ready
* 2: invalid intake contract
* 3: clarification required
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


INPUT_SCHEMA = "discovery-call-intake/v1"
RESULT_SCHEMA = "discovery-call-intake-gate/v1"
BUSINESS_MODES = {"briefing", "standard_visit", "strategic_account", "letter"}
FIELD_LABELS = {
    "customer_name": "客户主体",
    "organization_scope": "机构/院区范围",
    "target_person": "拜访对象姓名",
    "target_role": "拜访对象职务",
    "target_contact_level": "拜访对象层级",
    "meeting_status": "会议状态",
    "meeting_time": "会议时间",
    "project_id": "项目范围",
    "recipient_identity": "收件对象",
    "recipient_role": "收件对象职务",
    "visit_objective": "拜访目标",
    "minimum_next_step": "最小推进动作",
    "strategic_question": "账户战略问题",
    "planning_horizon": "账户经营周期",
    "strategy_variant": "策略成果变体",
    "letter_scenario": "信件场景",
    "letter_purpose": "发信目的",
    "expected_action": "期望对方动作",
    "signer": "签署人",
    "delivery_channel": "发送渠道",
}
SUPPORTED_FIELDS = set(FIELD_LABELS)
VISIT_MODES = {"briefing", "standard_visit"}
MEETING_STATUSES = {"confirmed", "tentative", "none", "unknown"}
MEETING_STATUS_VARIANTS = {
    "confirmed": "scheduled_visit",
    "tentative": "account_planning",
    "none": "account_planning",
    "unknown": "account_planning",
}
DEFAULT_TTL_SECONDS = 1800
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 3600
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")


class PreflightError(RuntimeError):
    """Raised when the structured intake contract is invalid."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        raise PreflightError("时间必须包含时区。")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PreflightError(f"{label}必须是带时区ISO 8601时间。")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreflightError(f"{label}必须是带时区ISO 8601时间。") from exc
    if parsed.tzinfo is None:
        raise PreflightError(f"{label}必须包含时区。")
    return parsed.astimezone(timezone.utc)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def resolved_text(value: Any) -> bool:
    text = normalize_text(value)
    return bool(
        text
        and len(text) <= 500
        and not PLACEHOLDER_RE.search(text)
        and text.casefold() not in {
            "待确认",
            "未确认",
            "待核实",
            "未核实",
            "待指定",
            "待补充",
            "unknown",
            "none",
            "n/a",
            "na",
        }
        and not any(ord(char) < 32 or ord(char) == 127 for char in text)
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PreflightError(f"{label}含未知字段：{', '.join(unknown)}。")


def _canonical_time_range(value: Any, label: str) -> tuple[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise PreflightError(f"{label}的meeting_time.value必须是start/end时间段对象。")
    _validate_exact_keys(value, {"start", "end", "timezone"}, f"{label}.value")
    if set(value) < {"start", "end"}:
        raise PreflightError(f"{label}.value必须包含start和end。")
    start = parse_timestamp(value.get("start"), f"{label}.value.start")
    end = parse_timestamp(value.get("end"), f"{label}.value.end")
    if end <= start:
        raise PreflightError(f"{label}.value.end必须晚于start。")
    if end - start > timedelta(hours=24):
        raise PreflightError(f"{label}.value时间跨度不得超过24小时。")
    timezone_name = normalize_text(value.get("timezone"))
    normalized = {
        "start": isoformat(start),
        "end": isoformat(end),
    }
    if timezone_name:
        normalized["timezone"] = timezone_name
    comparison = canonical_json({"start": isoformat(start), "end": isoformat(end)})
    return comparison, normalized


def _candidate_key(field: str, candidate: Mapping[str, Any], label: str) -> tuple[str, Any]:
    status = candidate["status"]
    value = candidate["value"]
    if field == "meeting_status":
        if status != "asserted":
            raise PreflightError(
                f"{label}的meeting_status必须用asserted和"
                "confirmed/tentative/none/unknown之一表达。"
            )
        normalized_status = normalize_text(value).casefold()
        if normalized_status not in MEETING_STATUSES:
            raise PreflightError(
                f"{label}.value必须是confirmed/tentative/none/unknown之一。"
            )
        return normalized_status, normalized_status
    if status == "explicit_unknown":
        if value is not None:
            raise PreflightError(f"{label}.value在explicit_unknown时必须为null。")
        return "__explicit_unknown__", None
    if field == "meeting_time":
        return _canonical_time_range(value, label)
    if not isinstance(value, str) or not resolved_text(value):
        raise PreflightError(f"{label}.value必须是非占位文本。")
    normalized = normalize_text(value)
    return normalized.casefold(), normalized


def validate_intake(payload: Any, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PreflightError("intake根节点必须是JSON对象。")
    _validate_exact_keys(
        payload,
        {"schema", "request_id", "business_mode", "candidate_sets", "confirmations"},
        "intake",
    )
    if payload.get("schema") != INPUT_SCHEMA:
        raise PreflightError(f"schema必须为{INPUT_SCHEMA}。")
    business_mode = payload.get("business_mode")
    if business_mode not in BUSINESS_MODES:
        raise PreflightError("business_mode必须是briefing/standard_visit/strategic_account/letter。")
    request_id = payload.get("request_id", "")
    if request_id and (not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id)):
        raise PreflightError("request_id只能包含3—128位字母、数字、点、下划线或连字符。")
    candidate_sets = payload.get("candidate_sets")
    if not isinstance(candidate_sets, list) or not candidate_sets:
        raise PreflightError("candidate_sets必须是非空数组。")
    confirmations = payload.get("confirmations", [])
    if not isinstance(confirmations, list):
        raise PreflightError("confirmations必须是数组。")
    if confirmations:
        raise PreflightError(
            "intake内嵌confirmations不具备可信宿主身份，不能消解冲突；"
            "请由认证宿主核验用户回合后重建只保留已确认候选的新intake。"
        )

    fields: dict[str, dict[str, Any]] = {}
    all_candidate_ids: set[str] = set()
    for set_index, candidate_set in enumerate(candidate_sets):
        label = f"candidate_sets[{set_index}]"
        if not isinstance(candidate_set, dict):
            raise PreflightError(f"{label}必须是对象。")
        _validate_exact_keys(candidate_set, {"field", "candidates"}, label)
        field = candidate_set.get("field")
        if field not in SUPPORTED_FIELDS:
            raise PreflightError(f"{label}.field不受支持：{field!r}。")
        if field in fields:
            raise PreflightError(f"field重复：{field}。")
        candidates = candidate_set.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PreflightError(f"{label}.candidates必须是非空数组。")
        normalized_candidates: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(candidates):
            candidate_label = f"{label}.candidates[{candidate_index}]"
            if not isinstance(candidate, dict):
                raise PreflightError(f"{candidate_label}必须是对象。")
            _validate_exact_keys(
                candidate,
                {"candidate_id", "value", "status", "source_ref"},
                candidate_label,
            )
            missing = sorted({"candidate_id", "value", "status", "source_ref"} - set(candidate))
            if missing:
                raise PreflightError(f"{candidate_label}缺少：{', '.join(missing)}。")
            candidate_id = candidate["candidate_id"]
            if not isinstance(candidate_id, str) or not REQUEST_ID_RE.fullmatch(candidate_id):
                raise PreflightError(f"{candidate_label}.candidate_id格式无效。")
            if candidate_id in all_candidate_ids:
                raise PreflightError(f"candidate_id重复：{candidate_id}。")
            all_candidate_ids.add(candidate_id)
            if candidate["status"] not in {"asserted", "explicit_unknown"}:
                raise PreflightError(f"{candidate_label}.status只能是asserted或explicit_unknown。")
            source_ref = candidate["source_ref"]
            if not isinstance(source_ref, str) or not resolved_text(source_ref):
                raise PreflightError(f"{candidate_label}.source_ref必须是可定位的非占位文本。")
            comparison_key, normalized_value = _candidate_key(field, candidate, candidate_label)
            normalized_candidates.append(
                {
                    "candidate_id": candidate_id,
                    "value": normalized_value,
                    "status": candidate["status"],
                    "source_ref": normalize_text(source_ref),
                    "comparison_key": comparison_key,
                }
            )
        fields[field] = {"candidates": normalized_candidates}

    return {
        "schema": INPUT_SCHEMA,
        "request_id": request_id,
        "business_mode": business_mode,
        "fields": fields,
        "confirmations": {},
    }


def _group_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        grouped.setdefault(str(candidate["comparison_key"]), []).append(candidate)
    return [
        sorted(group, key=lambda item: str(item["candidate_id"]))
        for _, group in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _selected_entry(
    candidates: Sequence[Mapping[str, Any]],
    *,
    basis: str,
    confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda item: str(item["candidate_id"]))
    value_groups = _group_candidates(ordered)
    entry: dict[str, Any] = {
        "values": [group[0]["value"] for group in value_groups],
        "candidate_ids": [candidate["candidate_id"] for candidate in ordered],
        "source_refs": sorted({str(candidate["source_ref"]) for candidate in ordered}),
        "selection_basis": basis,
    }
    if confirmation:
        entry["confirmation_ref"] = confirmation["confirmation_ref"]
        entry["confirmed_at"] = confirmation["confirmed_at"]
    return entry


def _display_value(candidate: Mapping[str, Any]) -> str:
    if candidate["status"] == "explicit_unknown":
        return "暂不清楚"
    value = candidate["value"]
    if isinstance(value, dict) and {"start", "end"} <= set(value):
        return f"{value['start']}—{value['end']}"
    return str(value)


def _conflict_question(field: str, groups: Sequence[Sequence[Mapping[str, Any]]]) -> str:
    choices: list[str] = []
    for index, group in enumerate(groups, 1):
        representative = group[0]
        refs = "、".join(sorted({str(item["source_ref"]) for item in group}))
        choices.append(f"{index}. {_display_value(representative)}（{refs}）")
    return f"请确认{FIELD_LABELS[field]}采用哪一项：" + "；".join(choices) + "。"


def evaluate_intake(
    payload: Any,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise PreflightError(f"ttl_seconds必须在{MIN_TTL_SECONDS}—{MAX_TTL_SECONDS}之间。")
    current = (now or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    validated = validate_intake(payload, now=current)
    selected_values: dict[str, dict[str, Any]] = {}
    blocking_conflicts: list[dict[str, Any]] = []
    question_pairs: list[tuple[str, str]] = []

    for field in FIELD_LABELS:
        record = validated["fields"].get(field)
        if not record:
            continue
        candidates = record["candidates"]
        groups = _group_candidates(candidates)
        confirmation = validated["confirmations"].get(field)
        if confirmation:
            selected_ids = set(confirmation["selected_candidate_ids"])
            chosen = [candidate for candidate in candidates if candidate["candidate_id"] in selected_ids]
            selected_values[field] = _selected_entry(
                chosen,
                basis="user_confirmation",
                confirmation=confirmation,
            )
            continue
        if len(groups) == 1:
            selected_values[field] = _selected_entry(groups[0], basis="single_value")
            continue
        blocking_conflicts.append(
            {
                "field": field,
                "field_label": FIELD_LABELS[field],
                "code": "conflicting_candidates",
                "candidate_groups": [
                    {
                        "candidate_ids": [item["candidate_id"] for item in group],
                        "values": [item["value"] for item in group],
                        "source_refs": sorted({str(item["source_ref"]) for item in group}),
                    }
                    for group in groups
                ],
            }
        )
        question_pairs.append((field, _conflict_question(field, groups)))

    if "organization_scope" not in selected_values and "customer_name" in selected_values:
        customer = selected_values["customer_name"]
        selected_values["organization_scope"] = {
            "values": list(customer["values"]),
            "candidate_ids": list(customer["candidate_ids"]),
            "source_refs": list(customer["source_refs"]),
            "selection_basis": "default_from_customer_name",
        }

    missing_requirements: list[dict[str, Any]] = []
    if "customer_name" not in selected_values:
        missing_requirements.append(
            {
                "field": "customer_name",
                "code": "required_value_missing",
                "message": "客户主体尚未形成唯一值。",
            }
        )
        if not any(field == "customer_name" for field, _ in question_pairs):
            question_pairs.append(("customer_name", "请确认本次研究对应的客户规范名称。"))

    mode = validated["business_mode"]
    strategy_variant = ""
    if mode == "strategic_account":
        status_record = selected_values.get("meeting_status", {})
        status_values = status_record.get("values", []) if isinstance(status_record, dict) else []
        meeting_status = (
            str(status_values[0])
            if len(status_values) == 1 and status_values[0] in MEETING_STATUSES
            else ""
        )
        meeting_record = selected_values.get("meeting_time", {})
        meeting_values = meeting_record.get("values", []) if isinstance(meeting_record, dict) else []
        exact_meeting_time = bool(
            len(meeting_values) == 1
            and isinstance(meeting_values[0], dict)
            and {"start", "end"} <= set(meeting_values[0])
        )
        status_time_conflict = meeting_status in {"none", "unknown"} and exact_meeting_time
        if status_time_conflict:
            blocking_conflicts.append(
                {
                    "field": "meeting_status",
                    "field_label": FIELD_LABELS["meeting_status"],
                    "code": "meeting_status_time_conflict",
                    "candidate_groups": [
                        {
                            "candidate_ids": list(status_record.get("candidate_ids", [])),
                            "values": [meeting_status],
                            "source_refs": list(status_record.get("source_refs", [])),
                        },
                        {
                            "candidate_ids": list(meeting_record.get("candidate_ids", [])),
                            "values": list(meeting_values),
                            "source_refs": list(meeting_record.get("source_refs", [])),
                        },
                    ],
                }
            )
            question_pairs.append(
                (
                    "meeting_status",
                    "会议状态为无会议或未知，但同时存在确切时间；请确认会议是否已确定，认证宿主核验后重建intake。",
                )
            )

        # meeting_status is authoritative when supplied.  A confirmed meeting
        # selects visit preparation even when its exact time is still unknown;
        # tentative stays in account planning until confirmation.  For legacy
        # inputs without meeting_status, an exact time range remains the only
        # meeting fact that can select scheduled_visit.  Target/objective alone
        # never establish that a meeting exists.
        if meeting_status:
            derived_variant = MEETING_STATUS_VARIANTS[meeting_status]
        else:
            derived_variant = "scheduled_visit" if exact_meeting_time else "account_planning"
        variant_record = selected_values.get("strategy_variant")
        if variant_record:
            variant_values = variant_record.get("values", [])
            if len(variant_values) == 1 and variant_values[0] in {"scheduled_visit", "account_planning"}:
                strategy_variant = str(variant_values[0])
                if strategy_variant != derived_variant:
                    blocking_conflicts.append(
                        {
                            "field": "strategy_variant",
                            "field_label": FIELD_LABELS["strategy_variant"],
                            "code": "strategy_variant_fact_conflict",
                            "candidate_groups": [
                                {
                                    "candidate_ids": list(variant_record.get("candidate_ids", [])),
                                    "values": [strategy_variant],
                                    "source_refs": list(variant_record.get("source_refs", [])),
                                },
                                {
                                    "candidate_ids": [],
                                    "values": [derived_variant],
                                    "source_refs": (
                                        ["结构化会议状态或确切会议时间"]
                                        if derived_variant == "scheduled_visit"
                                        else ["未发现已确认会议事实"]
                                    ),
                                },
                            ],
                        }
                    )
                    question_pairs.append(
                        (
                            "strategy_variant",
                            "策略分支与已确认会议事实冲突；请确认是否确有需要执行准备的明确拜访，并据此更新intake。",
                        )
                    )
            else:
                missing_requirements.append(
                    {"field": "strategy_variant", "code": "invalid_strategy_variant", "message": "策略成果变体未形成唯一有效值。"}
                )
                question_pairs.append(("strategy_variant", "请补充明确会议事实；系统将据此选择拜访准备或账户规划。"))
        else:
            strategy_variant = derived_variant
            if meeting_status:
                evidence_fields = ("meeting_status", "meeting_time")
            elif exact_meeting_time:
                evidence_fields = ("meeting_time",)
            else:
                evidence_fields = ()
            candidate_ids = sorted(
                {
                    str(candidate_id)
                    for field in evidence_fields
                    for candidate_id in selected_values.get(field, {}).get("candidate_ids", [])
                }
            )
            source_refs = sorted(
                {
                    str(source_ref)
                    for field in evidence_fields
                    for source_ref in selected_values.get(field, {}).get("source_refs", [])
                }
            )
            selected_values["strategy_variant"] = {
                "values": [strategy_variant],
                "candidate_ids": candidate_ids,
                "source_refs": source_refs,
                "selection_basis": (
                    "derived_from_confirmed_meeting_status"
                    if meeting_status == "confirmed"
                    else "derived_from_tentative_meeting_status"
                    if meeting_status == "tentative"
                    else "derived_from_nonmeeting_status"
                    if meeting_status in {"none", "unknown"}
                    else "derived_from_exact_meeting_time"
                    if exact_meeting_time
                    else "default_without_confirmed_meeting"
                ),
            }
    visit_contract = mode in VISIT_MODES or (mode == "strategic_account" and strategy_variant == "scheduled_visit")
    if visit_contract and not any(
        field in selected_values for field in ("target_person", "target_role", "target_contact_level")
    ):
        missing_requirements.append(
            {
                "field": "target_identity_or_level",
                "code": "required_any_missing",
                "message": "拜访对象姓名、职务或层级至少需要一项唯一值。",
            }
        )
        question_pairs.append(("target_identity_or_level", "请确认拜访对象的姓名、职务或至少所属层级。"))
    if visit_contract:
        for field, question in (
            ("visit_objective", "请确认本次拜访希望达成的主要目标。"),
            ("minimum_next_step", "请确认本次拜访希望形成的最小下一步。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))
    if mode == "strategic_account" and strategy_variant == "account_planning":
        for field, question in (
            ("strategic_question", "请确认本轮账户经营需要回答的战略问题。"),
            ("planning_horizon", "请确认账户规划周期，例如90天或本财年。"),
            ("minimum_next_step", "请确认本周期的最小推进动作。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))
    if mode == "letter":
        for field, question in (
            ("recipient_role", "请确认收件对象的明确角色或正式称谓。"),
            ("letter_scenario", "请确认本封信的业务场景。"),
            ("letter_purpose", "请确认本封信要达成的目的。"),
            ("expected_action", "请确认希望对方采取的动作。"),
            ("signer", "请确认签署人或稳定签署角色。"),
            ("delivery_channel", "请确认拟使用的发送渠道。"),
        ):
            if field not in selected_values:
                missing_requirements.append(
                    {"field": field, "code": "required_value_missing", "message": f"{FIELD_LABELS[field]}尚未形成唯一值。"}
                )
                question_pairs.append((field, question))

    # Keep only the first question for each blocking field and enforce the
    # interaction contract of no more than three short questions per turn.
    deduplicated_questions: list[dict[str, str]] = []
    seen_question_fields: set[str] = set()
    for field, question in question_pairs:
        if field in seen_question_fields:
            continue
        seen_question_fields.add(field)
        deduplicated_questions.append({"field": field, "question": question})
    questions = deduplicated_questions[:3]

    digest = input_sha256(payload)
    blocked = bool(blocking_conflicts or missing_requirements)
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "gate_id": "dcg-" + digest[:16],
        "request_id": validated["request_id"],
        "business_mode": mode,
        "status": "blocked" if blocked else "ready",
        "safe_to_initialize_or_search": not blocked,
        "input_sha256": digest,
        "evaluated_at": isoformat(current),
        "selected_values": selected_values,
        "blocking_conflicts": blocking_conflicts,
        "missing_requirements": missing_requirements,
        "questions": questions,
        "unasked_blocker_count": max(0, len(deduplicated_questions) - len(questions)),
    }
    if not blocked:
        result["expires_at"] = isoformat(current + timedelta(seconds=ttl_seconds))
    return result


def load_payload(path_text: str) -> Any:
    if path_text == "-":
        try:
            return json.load(sys.stdin)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PreflightError(f"stdin不是有效UTF-8 JSON：{exc}") from exc
    supplied = Path(path_text).expanduser()
    if supplied.is_symlink():
        raise PreflightError("intake文件不得为符号链接。")
    path = supplied.resolve()
    if not path.is_file():
        raise PreflightError(f"intake文件不存在或不是普通文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"intake文件不是有效UTF-8 JSON：{exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在创建客户工作区或检索前，对结构化候选值执行无副作用消歧。"
    )
    parser.add_argument("intake", help="结构化intake JSON文件；用-从stdin读取")
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help=f"ready回执有效期，{MIN_TTL_SECONDS}—{MAX_TTL_SECONDS}秒（默认{DEFAULT_TTL_SECONDS}）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = evaluate_intake(load_payload(args.intake), ttl_seconds=args.ttl_seconds)
    except (PreflightError, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
