import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from periodic_topology import PERIODIC_HEADING_PATTERNS, validate_periodic_topology


ALLOWED_PERIOD_TYPES = {"daily", "weekly", "monthly", "quarterly", "annual"}
REQUIRED_HANDOFF_FIELDS = {
    "period_type",
    "audit_title",
    "audit_body_markdown",
    "next_tactics",
    "followup_flags",
    "requires_mentat_diary",
}

PLACEHOLDER_PATTERNS = [
    r"\[(?:YYYY|日期|星期|事件|主线|一句话|承诺|证据|说明|状态|起始日期|结束日期|月份|年份|高优先级|中优先级|低优先级|Root Cause|Tactic)[^\]\n]*\]",
    r"(?<!\\)\{(?=[^{}\n]*[\u4e00-\u9fff])[^{}\n]{1,160}\}",
    r"(?im)^\s*(?:TODO|TBD|待填写|待补充)\s*[:：]?",
]

STYLE_TERMS = [
    "这是法庭",
    "法庭模式",
    "冷酷判词",
    "自欺欺人",
    "今日打脸",
    "毫不留情",
    "人格缺陷",
    "内分泌死锁",
    "生理破产",
]

ENERGY_HEADING = re.compile(
    r"(?im)^#{1,6}\s+(?:能量管理（描述性生理背景）|"
    r"能量管理\s*\(Biological-Cognitive Correlation\))\s*$"
)
NEXT_HEADING = re.compile(r"(?m)^#{1,6}\s+")
ENERGY_REQUIRED_FIELDS = (
    "数据范围与来源",
    "组件覆盖与新鲜度",
    "采集审计",
    "睡眠观察",
    "HRV 与静息心率观察",
    "Body Battery 与压力观察",
    "执行带宽",
    "睡眠负债",
    "摩擦解构",
    "交叉归因",
    "干预指令",
    "数据缺口与不可判断事项",
)

ACQUISITION_FIELD_ENUMS = {
    "sync_eligible": ("true", "false"),
    "sync_attempted": ("started", "waited_existing", "direct", "not_attempted"),
    "task_status": (
        "success",
        "failed",
        "timeout",
        "invalid",
        "start_failed",
        "interrupted_or_terminated",
        "not_checked",
    ),
    "local_reread": ("accepted", "rejected", "not_run"),
    "local_status": ("complete", "partial", "no_data", "read_error", "not_run"),
    "live_fallback": ("used", "not_used"),
}
ACQUISITION_AUDIT_CONTRACT = "; ".join(
    f"{field}=<{'|'.join(values)}>"
    for field, values in ACQUISITION_FIELD_ENUMS.items()
) + "; reason=<稳定原因码>"


def _enum_pattern(field: str) -> re.Pattern[str]:
    alternatives = "|".join(
        re.escape(value) for value in ACQUISITION_FIELD_ENUMS[field]
    )
    return re.compile(rf"\b{field}=(?:{alternatives})\b", re.IGNORECASE)


ACQUISITION_AUDIT_PATTERNS = {
    field: (
        re.compile(r"\btask_status=[a-z0-9_]+\b", re.IGNORECASE)
        if field == "task_status"
        else _enum_pattern(field)
    )
    for field in ACQUISITION_FIELD_ENUMS
}
ACQUISITION_AUDIT_PATTERNS["reason"] = re.compile(
    r"\breason=[a-z0-9_]+\b", re.IGNORECASE
)
ACQUISITION_VALUE = re.compile(
    r"\b(sync_eligible|sync_attempted|task_status|local_reread|local_status|live_fallback|reason)=([a-z0-9_]+)\b",
    re.IGNORECASE,
)
ALLOWED_TASK_STATUSES = set(ACQUISITION_FIELD_ENUMS["task_status"])
FAILED_TASK_STATUSES = ALLOWED_TASK_STATUSES - {"success", "not_checked"}
TASK_REASON_BINDINGS = {
    "success": {"sync_verified_local_reread_required"},
    "timeout": {"task_wait_timeout"},
    "start_failed": {"task_start_failed"},
    "interrupted_or_terminated": {"interrupted_or_terminated"},
}


def acquisition_semantic_errors(value: str) -> list[str]:
    fields = {key.casefold(): item.casefold() for key, item in ACQUISITION_VALUE.findall(value)}
    if len(fields) < len(ACQUISITION_AUDIT_PATTERNS):
        return []
    errors = []
    eligible = fields["sync_eligible"] == "true"
    attempted = fields["sync_attempted"]
    task_status = fields["task_status"]
    reread = fields["local_reread"]
    local_status = fields["local_status"]
    live = fields["live_fallback"]
    reason = fields["reason"]
    if attempted in {"started", "waited_existing", "direct"} and not eligible:
        errors.append("attempted sync requires eligibility")
    if not eligible and attempted != "not_attempted":
        errors.append("ineligible sync cannot be attempted")
    if task_status not in ALLOWED_TASK_STATUSES:
        errors.append("task status must be terminal or not_checked")
    if attempted == "not_attempted" and task_status not in {"not_checked", "invalid", "start_failed"}:
        errors.append("unattempted sync has an incompatible task status")
    if attempted != "not_attempted" and task_status == "not_checked":
        errors.append("attempted sync requires a task terminal status")
    if task_status == "success" and reread == "not_run":
        errors.append("successful sync requires a local reread")
    if task_status in FAILED_TASK_STATUSES and live == "used":
        errors.append("failed sync cannot use live fallback in the same acquisition")
    if live == "used" and reread != "rejected":
        errors.append("live fallback requires an explicit no-data local reread rejection")
    if live == "used" and local_status != "no_data":
        errors.append("live fallback requires structured local_status=no_data")
    if live == "used" and (attempted != "not_attempted" or task_status != "not_checked"):
        errors.append("live fallback requires an unattempted sync branch")
    if live == "used" and eligible:
        errors.append("live fallback requires sync_eligible=false")
    if reason in {"not_evaluated", "unknown", "none"}:
        errors.append("reason must be a stable evaluated code")
    if task_status in TASK_REASON_BINDINGS and reason not in TASK_REASON_BINDINGS[task_status]:
        errors.append("reason does not match task terminal status")
    if reread == "not_run" and local_status != "not_run":
        errors.append("local status must be not_run when reread did not run")
    if reread == "accepted" and local_status not in {"complete", "partial"}:
        errors.append("accepted local reread must be complete or partial")
    if reread == "rejected" and local_status not in {"no_data", "read_error"}:
        errors.append("rejected local reread must be no_data or read_error")
    return errors

COMPOSITE_SCORE_PATTERNS = [
    re.compile(
        r"(?im)^\s*(?:[-*]\s*)?(?:\*\*)?"
        r"(?:能量总分|能量分|准备度总分|准备度分|恢复力总分|恢复力分|执行带宽分)"
        r"(?:\*\*)?\s*[:：=]\s*(?:\d+(?:\.\d+)?|[红黄绿])"
    ),
    re.compile(r"(?im)^\s*(?:[-*]\s*)?readiness(?:_index)?(?:\.score| score)?\s*[:=]\s*\d"),
]
DATA_UNAVAILABLE_SENTINEL = re.compile(r"(?i)\[DATA_UNAVAILABLE\]")
EXECUTION_SCORING_VALUE = re.compile(
    r"(?i)(?:\b(?:score|value|level|color)\b\s*[:=：]\s*(?!none\b|null\b|not_scored\b)\S+|"
    r"(?:评分|分数|等级|颜色)\s*[:=：]\s*(?:\d|红|黄|绿)|\d+(?:\.\d+)?\s*/\s*100)"
)
SLEEP_DEBT_NULL = re.compile(r"(?i)\bsleep_debt_h\s*=\s*`?null`?\b")
SLEEP_DEBT_NUMERIC = re.compile(
    r"(?i)\bsleep_debt_h\s*=\s*`?(-?\d+(?:\.\d+)?)`?\b"
)
MISSING_AS_ZERO = re.compile(
    r"(?im)^(?=[^\n]*(?:无数据|无有效观测|缺失|未提供))"
    r"[^\n]*(?:睡眠|HRV|心率|压力|Body Battery|身体电量)[^\n]*"
    r"[:：=]\s*0(?:\D|$)"
)
PYTHON_NONE = re.compile(r"\bNone\b")
HEALTH_CONTEXT = re.compile(
    r"(?i)(?:Garmin|睡眠|HRV|心率|压力|Body Battery|身体电量|恢复|健康|生理)"
)
HEALTH_FIELD_PREFIX = re.compile(
    r"(?i)^\s*(?:[-*]\s*)?(?:sleep|睡眠|HRV|心率|压力|stress|Body Battery|身体电量|恢复|健康|生理)"
    r"(?:[^:：\n]{0,24})?[:：]"
)
GENERIC_DATA_FIELD_NONE = re.compile(
    r"(?i)^\s*(?:[-*]\s*)?(?:value|status|duration|score|amount|metric|reading)\s*[:：=]\s*None\b"
)
HEALTH_CAUSAL_CONNECTOR = re.compile(
    r"(?i)(?:因此|因而|所以|据此|由此|基于(?:上述|该|这些)?(?:健康|生理|睡眠|HRV|心率|压力|Body Battery|身体电量)?(?:观测|数据|指标)?|because|therefore|based\s+on)"
)
UNRELATED_DOMAIN = re.compile(
    r"(?i)(?:项目|负责人|行情|股票|交易|代码|脚本|调试|Python|API|接口|市场|会议组织者)"
)
ALLOWED_NO_DATA_FALLBACK = re.compile(
    r"(?i)(?:只有|仅在|仅当|if|when)[^，,。；;\n]{0,16}(?:no_data|无数据)"
    r"[^，,。；;\n]{0,20}(?:允许|可|才|may|allow)[^，,。；;\n]{0,12}"
    r"(?:(?:云端|实时|cloud|live)[^，,。；;\n]{0,12}(?:回退|查询|fallback)"
    r"|(?:回退|查询|fallback)[^，,。；;\n]{0,12}(?:云端|实时|cloud|live))"
)
CLAUSE_SPLIT = re.compile(r"(?:\r?\n|[，,。；;]|但(?:是)?|然而|不过|随后)")
PARTIAL_STATUS = re.compile(r"(?i)\bpartial\b")
CLOUD_FALLBACK_ACTION = re.compile(
    r"(?i)(?:(?:云端|实时|cloud|live)[^，,。；;\n]{0,12}(?:回退|查询|fallback)"
    r"|(?:回退|查询|fallback)[^，,。；;\n]{0,12}(?:云端|实时|cloud|live))"
)
FALLBACK_NEGATION = re.compile(
    r"(?i)(?:(?:未|没有|并未|不会|不再|不予|禁止|不得|无需|无须|不需要)"
    r"[^，,。；;\n]{0,20}(?:(?:云端|实时|cloud|live)"
    r"[^，,。；;\n]{0,12}(?:回退|查询|fallback)"
    r"|(?:回退|查询|fallback)[^，,。；;\n]{0,12}(?:云端|实时|cloud|live))"
    r"|(?:云端|实时|cloud|live)[^，,。；;\n]{0,8}"
    r"(?:未|没有|并未|不会|不再|不予|禁止|不得|无需|无须|不需要)"
    r"[^，,。；;\n]{0,12}(?:回退|查询|fallback)"
    r"|(?:not|never|without)[^，,。；;\n]{0,16}"
    r"(?:(?:cloud|live)[^，,。；;\n]{0,12}(?:fallback|query)"
    r"|(?:fallback|query)[^，,。；;\n]{0,12}(?:cloud|live)))"
)
FORCED_HEALTH_DECISION = re.compile(
    r"(?i)(?:必须|应当|需要)[^，,。；;\n]{0,16}"
    r"(?:取消会议|停止工作|停止训练|修改闹钟|禁止决策|推迟重要决策)"
)
NON_FORCING_DECISION = re.compile(
    r"(?:不需要|无需|无须|不必|没有必要)[^，,。；;\n]{0,16}"
    r"(?:取消会议|停止工作|停止训练|修改闹钟|禁止决策|推迟重要决策)"
)
HEALTH_CAUSALITY = re.compile(
    r"(?im)^[^\n]*(?:HRV|睡眠|压力|Body Battery|身体电量|心率)[^\n]{0,40}"
    r"(?:证明|说明|导致|造成|表明)[^\n]{0,40}"
    r"(?:疾病|感染|炎症|免疫|认知能力|工作表现|职业表现)"
)
SHARED_UPSTREAM_OVERCLAIM = re.compile(
    r"(?is)(?=.*Body Battery)(?=.*睡眠评分)(?=.*(?:独立证据|双重证据|相互印证|叠加))"
)

HANDOFF_HEADING = re.compile(r"(?im)^#{1,6}\s+Handoff Payload\s*$")
HANDOFF_JSON_BLOCK = re.compile(
    r"\A[ \t]*(?:\r?\n)+[ \t]*```json[ \t]*\r?\n"
    r"(?P<payload>.*?)\r?\n```[ \t]*(?=\r?\n|\Z)",
    re.DOTALL,
)


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_placeholders(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in PLACEHOLDER_PATTERNS:
        hits.extend(str(match) for match in re.findall(pattern, text))
    return hits


def extract_energy_section(text: str) -> tuple[str | None, list[str]]:
    headings = list(ENERGY_HEADING.finditer(text))
    if not headings:
        return None, []
    if len(headings) > 1:
        return None, ["multiple energy-management sections found"]

    start = headings[0].end()
    next_heading = NEXT_HEADING.search(text, start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end], []


def extract_energy_field_values(section: str) -> dict[str, list[str]]:
    """Extract bundled-template energy fields without accepting prose mentions."""
    values: dict[str, list[str]] = {}
    for field in ENERGY_REQUIRED_FIELDS:
        pattern = re.compile(
            rf"(?im)^\s*[-*]\s*(?:\*\*)?{re.escape(field)}\s*"
            rf"(?:[:：](?:\*\*)?|(?:\*\*)?\s*[:：])\s*(?P<value>[^\n]*)$"
        )
        matches = [match.group("value").strip() for match in pattern.finditer(section)]
        if matches:
            values[field] = matches
    return values


def is_contentless_energy_value(value: str) -> bool:
    normalized = value.strip().strip("` ")
    normalized = normalized.rstrip("。.;；").strip().casefold()
    return normalized in {"", "[data_unavailable]", "data_unavailable", "not_scored"}


def semantic_clauses(text: str) -> list[str]:
    """Split prose into local assertion units for negation-aware checks."""
    return [clause.strip() for clause in CLAUSE_SPLIT.split(text) if clause.strip()]


def has_partial_cloud_fallback(text: str) -> bool:
    clauses = semantic_clauses(text)
    partial_indexes = [
        index for index, clause in enumerate(clauses) if PARTIAL_STATUS.search(clause)
    ]
    if not partial_indexes:
        return False

    for index, clause in enumerate(clauses):
        candidate = FALLBACK_NEGATION.sub("", clause)
        if ALLOWED_NO_DATA_FALLBACK.search(candidate) or UNRELATED_DOMAIN.search(candidate):
            continue
        if not CLOUD_FALLBACK_ACTION.search(candidate):
            continue
        if any(abs(index - partial_index) <= 2 for partial_index in partial_indexes):
            return True
    return False


def has_forced_health_decision(text: str, energy_section: str | None) -> bool:
    """Limit schedule blockers to health-scoped, affirmative action claims."""
    if energy_section:
        for clause in semantic_clauses(energy_section):
            candidate = NON_FORCING_DECISION.sub("", clause)
            if FORCED_HEALTH_DECISION.search(candidate):
                return True

    clauses = semantic_clauses(text)
    for clause in clauses:
        candidate = NON_FORCING_DECISION.sub("", clause)
        unrelated_subject = re.search(
            r"(?i)(?:项目负责人|会议组织者|行情|股票|交易|代码|脚本|调试|Python|API|接口|市场)",
            candidate,
        )
        if (
            FORCED_HEALTH_DECISION.search(candidate)
            and HEALTH_CONTEXT.search(candidate)
            and not unrelated_subject
        ):
            return True

    for index, clause in enumerate(clauses):
        candidate = NON_FORCING_DECISION.sub("", clause)
        if not FORCED_HEALTH_DECISION.search(candidate):
            continue
        if re.search(
            r"(?i)(?:项目负责人|会议组织者|行情|股票|交易|代码|脚本|调试|Python|API|接口|市场)",
            candidate,
        ):
            continue
        prior_window = " ".join(clauses[max(0, index - 2) : index])
        if HEALTH_CONTEXT.search(prior_window) and (
            HEALTH_CAUSAL_CONNECTOR.search(candidate) or index > 0
        ):
            return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        candidate = NON_FORCING_DECISION.sub("", line)
        if not FORCED_HEALTH_DECISION.search(candidate):
            continue
        if UNRELATED_DOMAIN.search(candidate):
            continue
        prior = lines[index - 1] if index > 0 else ""
        if HEALTH_CONTEXT.search(prior) and HEALTH_CAUSAL_CONNECTOR.search(candidate):
            return True
    return False


def has_health_scoped_none(text: str, energy_section: str | None) -> bool:
    if energy_section is not None and PYTHON_NONE.search(energy_section):
        return True

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if PYTHON_NONE.search(line) and (
            HEALTH_CONTEXT.search(line) or HEALTH_FIELD_PREFIX.search(line)
        ) and not UNRELATED_DOMAIN.search(line):
            return True
        prior = lines[index - 1] if index > 0 else ""
        if (
            GENERIC_DATA_FIELD_NONE.search(line)
            and HEALTH_CONTEXT.search(prior)
            and not UNRELATED_DOMAIN.search(line)
            and not UNRELATED_DOMAIN.search(prior)
        ):
            return True
    return False


def validate_energy_contract(
    text: str,
    enforce_template_fields: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    section, section_errors = extract_energy_section(text)
    errors.extend(section_errors)
    if section is None and enforce_template_fields and not section_errors:
        errors.append("energy-management section missing")
    if section is not None:
        field_values = extract_energy_field_values(section)
        missing_fields = [
            field for field in ENERGY_REQUIRED_FIELDS if field not in field_values
        ]
        if missing_fields:
            message = "energy-management section missing fields: " + ", ".join(
                missing_fields
            )
            if enforce_template_fields:
                errors.append(message)
            else:
                warnings.append(message)

        duplicate_fields = [
            field for field, values in field_values.items() if len(values) > 1
        ]
        if duplicate_fields:
            message = "energy-management section has duplicate fields: " + ", ".join(
                duplicate_fields
            )
            if enforce_template_fields:
                errors.append(message)
            else:
                warnings.append(message)

        contentless_fields = [
            field
            for field, values in field_values.items()
            if any(is_contentless_energy_value(value) for value in values)
        ]
        if contentless_fields:
            message = "energy-management fields require explanatory content: " + ", ".join(
                contentless_fields
            )
            if enforce_template_fields:
                errors.append(message)
            else:
                warnings.append(message)

        execution_values = field_values.get("执行带宽", [])
        sleep_debt_values = field_values.get("睡眠负债", [])
        acquisition_values = field_values.get("采集审计", [])
        if acquisition_values:
            acquisition_value = acquisition_values[0]
            missing_audit_keys = [
                key
                for key, pattern in ACQUISITION_AUDIT_PATTERNS.items()
                if not pattern.search(acquisition_value)
            ]
            if missing_audit_keys:
                errors.append(
                    "acquisition audit missing or invalid keys: "
                    + ", ".join(missing_audit_keys)
                )
            else:
                for semantic_error in acquisition_semantic_errors(acquisition_value):
                    errors.append("acquisition audit state conflict: " + semantic_error)
        sentinel_fields = [
            field
            for field, values in (
                ("执行带宽", execution_values),
                ("睡眠负债", sleep_debt_values),
            )
            if any(DATA_UNAVAILABLE_SENTINEL.search(value) for value in values)
        ]
        if sentinel_fields:
            errors.append(
                "energy-management fields must not expose DATA_UNAVAILABLE: "
                + ", ".join(sentinel_fields)
            )
        if enforce_template_fields and execution_values and any(
            "not_scored" not in value.casefold() for value in execution_values
        ):
            errors.append(
                "execution bandwidth must retain not_scored and explain the inference boundary"
            )
        if any(EXECUTION_SCORING_VALUE.search(value) for value in execution_values):
            errors.append(
                "execution bandwidth must not contain score, value, level, or color outputs"
            )

        for value in sleep_debt_values:
            if SLEEP_DEBT_NULL.search(value):
                required_null_tokens = (
                    "sleep_debt_status=not_provided_by_source",
                    "method=none",
                    "baseline_h=null",
                    "window_days=null",
                )
                normalized = re.sub(r"[`\s]", "", value.casefold())
                missing = [
                    token for token in required_null_tokens if token not in normalized
                ]
                if missing:
                    errors.append(
                        "null sleep debt requires complete unavailable-state fields: "
                        + ", ".join(missing)
                    )

            numeric_match = SLEEP_DEBT_NUMERIC.search(value)
            if numeric_match:
                normalized = re.sub(r"[`\s]", "", value.casefold())
                missing = []
                if "sleep_debt_status=provided_by_source" not in normalized:
                    missing.append("sleep_debt_status=provided_by_source")
                if not re.search(r"(?i)\bmethod\s*=\s*(?!none\b|null\b)\S+", value):
                    missing.append("method=<source method>")
                if not re.search(r"(?i)\bbaseline_h\s*=\s*(?!none\b|null\b)-?\d", value):
                    missing.append("baseline_h=<number>")
                if not re.search(r"(?i)\bwindow_days\s*=\s*[1-9]\d*", value):
                    missing.append("window_days=<positive integer>")
                if float(numeric_match.group(1)) < 0:
                    missing.append("sleep_debt_h>=0")
                if missing:
                    errors.append(
                        "numeric sleep debt requires source method, baseline, and window: "
                        + ", ".join(missing)
                    )
        if "观测日期" not in section and "无有效观测" not in section:
            warnings.append(
                "energy-management section does not expose per-KPI observation dates or an explicit no-observation state"
            )

    for pattern in COMPOSITE_SCORE_PATTERNS:
        if pattern.search(text):
            errors.append(
                "self-generated composite energy/readiness/recovery/execution score is prohibited"
            )
            break

    if has_health_scoped_none(text, section):
        errors.append("Python None must not appear in user-facing audit text")
    if MISSING_AS_ZERO.search(text):
        errors.append("missing health observations must remain null, not physiological value 0")
    if has_partial_cloud_fallback(text):
        errors.append("partial local Garmin data must not trigger cloud fallback")
    if has_forced_health_decision(text, section):
        errors.append("health observations must not force training, schedule, or decision changes")

    sleep_debt_not_provided = re.search(
        r"(?i)sleep_debt_status\s*[:=]\s*not_provided_by_source",
        text,
    )
    sleep_debt_value = re.search(
        r"(?i)sleep_debt_h\s*[:=]\s*(?P<value>null|-?\d+(?:\.\d+)?)",
        text,
    )
    if (
        sleep_debt_not_provided
        and sleep_debt_value
        and sleep_debt_value.group("value").lower() != "null"
    ) or re.search(
        r"(?im)^[^\n]*(?:来源未提供|not_provided_by_source)[^\n]*"
        r"(?:睡眠负债|sleep debt)[^，,。；;\n]{0,12}\d",
        text,
    ):
        errors.append(
            "sleep debt value must stay null when the source status is not_provided_by_source"
        )

    if HEALTH_CAUSALITY.search(text):
        warnings.append(
            "review health causality or medical/cognitive/occupational overreach"
        )
    if SHARED_UPSTREAM_OVERCLAIM.search(text):
        warnings.append(
            "Body Battery and sleep score share upstream signals and must not be treated as independent evidence"
        )

    return errors, warnings


def extract_handoff_payload(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    headings = list(HANDOFF_HEADING.finditer(text))
    if not headings:
        return None, errors
    if len(headings) > 1:
        return None, ["multiple Handoff Payload sections found"]

    tail = text[headings[0].end() :]
    block = HANDOFF_JSON_BLOCK.match(tail)
    if not block:
        return None, [
            "Handoff Payload must be followed by one fenced JSON object"
        ]

    try:
        payload = json.loads(block.group("payload"))
    except json.JSONDecodeError as exc:
        return None, [
            f"Handoff Payload is not valid JSON at line {exc.lineno}, column {exc.colno}"
        ]

    if not isinstance(payload, dict):
        return None, ["Handoff Payload must be a JSON object"]
    return payload, errors


def validate_handoff_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_HANDOFF_FIELDS - payload.keys())
    if missing:
        errors.append("Handoff Payload missing fields: " + ", ".join(missing))

    period_type = payload.get("period_type")
    if period_type not in ALLOWED_PERIOD_TYPES:
        errors.append(
            "period_type must be one of: " + ", ".join(sorted(ALLOWED_PERIOD_TYPES))
        )

    for field in ("audit_title", "audit_body_markdown"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} must be a non-empty string")

    next_tactics = payload.get("next_tactics")
    if (
        not isinstance(next_tactics, list)
        or not next_tactics
        or any(not isinstance(item, str) or not item.strip() for item in next_tactics)
    ):
        errors.append("next_tactics must be a non-empty array of non-empty strings")

    followup_flags = payload.get("followup_flags")
    if not isinstance(followup_flags, list) or any(
        not isinstance(item, str) or not item.strip() for item in followup_flags
    ):
        errors.append("followup_flags must be an array of non-empty strings")

    if not isinstance(payload.get("requires_mentat_diary"), bool):
        errors.append("requires_mentat_diary must be a boolean")

    return errors


def validate(
    text: str,
    strict_human_mode: bool = False,
    enforce_template_fields: bool = False,
    period_type: str | None = None,
    period_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return deterministic errors and non-blocking editorial warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    if not text.strip():
        return ["audit body is empty"], warnings

    errors.extend(validate_periodic_topology(text, period_type, period_id))
    placeholders = find_placeholders(text)
    if placeholders:
        preview = ", ".join(placeholders[:8])
        message = f"possible unresolved template markers: {preview}"
        if enforce_template_fields:
            errors.append(message)
        else:
            warnings.append(
                message
                + "; free-form evidence may contain literal examples, so this is non-blocking"
            )

    payload, handoff_errors = extract_handoff_payload(text)
    errors.extend(handoff_errors)
    if payload is not None:
        errors.extend(validate_handoff_payload(payload))
        if payload.get("requires_mentat_diary") is True:
            warnings.append(
                "requires_mentat_diary=true still requires separate explicit user authorization"
            )

    energy_errors, energy_warnings = validate_energy_contract(
        text,
        enforce_template_fields,
    )
    errors.extend(energy_errors)
    warnings.extend(energy_warnings)

    for term in STYLE_TERMS:
        if term in text:
            warnings.append(f"review potentially shaming or diagnostic language: '{term}'")

    if not re.search(r"证据|来源|材料|evidence|source", text, re.IGNORECASE):
        warnings.append("no explicit evidence or source marker found")

    if strict_human_mode:
        warnings.append(
            "--strict-human-mode is retained for compatibility but does not turn style heuristics into blockers"
        )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate personal-cognitive-auditor output. Deterministic template, "
            "handoff-schema, and health-safety contract failures block delivery."
        )
    )
    parser.add_argument("audit_path", help="Path to the generated audit Markdown")
    parser.add_argument(
        "--strict-human-mode",
        action="store_true",
        help="Emit an additional style-review warning; never blocks delivery",
    )
    parser.add_argument(
        "--enforce-template-fields",
        action="store_true",
        help="Treat bundled-template markers as blocking for a template-derived draft",
    )
    parser.add_argument(
        "--period-type",
        choices=tuple(PERIODIC_HEADING_PATTERNS),
        help="Validate the strict topology for one periodic autosave payload",
    )
    parser.add_argument(
        "--period-id",
        help="Exact YYYY-Www, YYYY-MM, or YYYY-QN identifier bound to the payload",
    )
    args = parser.parse_args()
    if (args.period_type is None) != (args.period_id is None):
        parser.error("--period-type and --period-id must be provided together")

    path = Path(args.audit_path)
    if not path.is_file():
        print(f"[FAIL] file not found: {path}")
        return 1

    try:
        text = load_text(path)
    except (OSError, UnicodeError) as exc:
        print(f"[FAIL] unable to read UTF-8 audit: {exc}")
        return 1

    errors, warnings = validate(
        text,
        args.strict_human_mode,
        args.enforce_template_fields,
        args.period_type,
        args.period_id,
    )
    for warning in warnings:
        print(f"[WARN] {warning}")

    if errors:
        print("[FAIL] audit gate blocked by deterministic errors")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"[PASS] audit gate passed with {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
