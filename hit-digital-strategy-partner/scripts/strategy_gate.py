import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

try:
    from blackboard import validate_state
except Exception as exc:  # pragma: no cover - only when the local module is broken
    validate_state = None
    BLACKBOARD_IMPORT_ERROR = f"cannot import blackboard validator: {exc}"
else:
    BLACKBOARD_IMPORT_ERROR = ""


SCRIPT_DIR = Path(__file__).resolve().parent
REFERENCE_DIR = SCRIPT_DIR.parent / "references"
MEDICAL_TERMS_PATH = REFERENCE_DIR / "medical_terms.json"
COMPLIANCE_RULES_PATH = REFERENCE_DIR / "compliance_rules.json"

SUPPORTED_MODES = ("brief", "deep-dive", "board-memo", "investment-case")
MATURITY_VALUES = (
    "working_draft",
    "review_ready",
    "decision_ready",
    "approved_for_execution",
    "blocked",
)

# A bracketed phrase is a placeholder only when it carries an explicit fill-in
# marker. Broad prefixes such as ``[金额...]`` are deliberately excluded:
# ``[金额与预算]`` can be a perfectly valid heading.
PLACEHOLDER_PATTERNS = [
    re.compile(
        r"\[[^\]\n]*(?:待填(?:写)?|待补(?:充)?|待确认|待核实|待核验|"
        r"待完善|待替换|待提供|待定|TODO|TBD|TBC|FIXME|PLACEHOLDER|"
        r"INSERT\s+HERE)[^\]\n]*\]",
        re.IGNORECASE,
    ),
    re.compile(r"\{\{\s*[^{}\n]+?\s*\}\}"),
    re.compile(r"\$\{\s*[^{}\n]+?\s*\}"),
    re.compile(
        r"<(?:TODO|TBD|TBC|FIXME|PLACEHOLDER|INSERT(?:\s+HERE)?)(?:\s*:[^>\n]*)?>",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:TODO|TBD|TBC|FIXME|PLACEHOLDER)\b", re.IGNORECASE),
    re.compile(
        r"(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+)?"
        r"(?:待填充|待填写|待补充|待确认|待核实|待核验|待完善|待替换|待提供|待定)"
        r"(?:\s*[：:].*)?\s*$"
    ),
    re.compile(r"https?://example\.(?:com|org|net)(?:/|\b)", re.IGNORECASE),
]

QUANTITATIVE_CLAIM_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*%|[¥￥$]\s*\d|人民币\s*\d|"
    r"\d+(?:\.\d+)?\s*(?:万元|亿元|万美元|人天|小时/年))"
)
PROVENANCE_HINT_RE = re.compile(
    r"(?:来源|依据|假设|测算|口径|截至|地区|情景|基线|"
    r"source|assumption|as[ -]?of|region|baseline|methodology)",
    re.IGNORECASE,
)
URL_OR_CITATION_RE = re.compile(
    r"(?:https?://|\[[^\]]+\]\(https?://|\[\^?\d+\])", re.IGNORECASE
)
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")

COMPLIANCE_TOPIC_KEYWORDS = {
    "personal_and_health_data": (
        "个人信息",
        "敏感个人信息",
        "健康数据",
        "医疗数据",
        "患者数据",
        "病人数据",
        "电子病历数据",
        "patient data",
        "health data",
        "personal data",
        "protected health information",
        "phi",
    ),
    "network_and_system_security": (
        "网络安全",
        "数据安全",
        "等保",
        "关键信息基础设施",
        "cybersecurity",
        "network security",
    ),
    "medical_device_classification": (
        "医疗器械",
        "软件医疗器械",
        "samd",
        "nmpa",
        "fda clearance",
        "medical device",
    ),
    "clinical_research_ethics": (
        "临床研究",
        "临床试验",
        "伦理审查",
        "知情同意",
        "clinical research",
        "clinical trial",
        "ethics review",
        "informed consent",
    ),
    "algorithm_and_model_governance": (
        "临床ai",
        "医疗ai",
        "医学人工智能",
        "辅助诊断",
        "辅助决策",
        "算法治理",
        "模型治理",
        "模型风险",
        "clinical ai",
        "medical ai",
        "clinical decision support",
        "algorithm governance",
        "model governance",
    ),
    "cross_border_data": (
        "数据跨境",
        "跨境数据",
        "数据出境",
        "境外处理",
        "cross-border data",
        "cross border data",
        "data export",
    ),
}


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep command-line failures machine readable."""

    def error(self, message: str) -> NoReturn:
        emit_json(
            {
                "status": "fail",
                "errors": [f"invalid arguments: {message}"],
                "warnings": [],
            }
        )
        raise SystemExit(2)


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def count_words(text: str) -> int:
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_word_count = len(re.findall(r"\b[a-zA-Z0-9]+\b", text))
    return cjk_count + en_word_count


def load_json_object(path: Path, label: str) -> tuple[dict, list[str]]:
    if not path.exists():
        return {}, [f"{label} file not found: {path}"]
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return {}, [f"cannot read {label}: {exc}"]
    if not raw.strip():
        return {}, [f"{label} file is empty: {path}"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, [
            f"cannot read {label} JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ]
    if not isinstance(data, dict):
        return {}, [f"{label} root must be a JSON object"]
    if not data:
        return {}, [f"{label} JSON object is empty"]
    return data, []


def load_blackboard(path: Path | None) -> tuple[dict, list[str]]:
    if path is None:
        return {}, ["blackboard is required"]
    return load_json_object(path, "blackboard")


def contains_any(text: str, options: list[str]) -> bool:
    folded = text.casefold()
    return any(option.casefold() in folded for option in options if option)


def unique_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def format_blackboard_issue(issue: Any) -> str:
    if not isinstance(issue, dict):
        return str(issue)
    code = str(issue.get("code", "BLACKBOARD")).strip() or "BLACKBOARD"
    path = str(issue.get("path", "$")).strip() or "$"
    message = str(issue.get("message", "validation issue")).strip()
    return f"blackboard {code} at {path}: {message}"


def find_placeholders(text: str) -> list[str]:
    hits: list[str] = []
    occupied: list[tuple[int, int]] = []
    for pattern in PLACEHOLDER_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(
                start < old_end and end > old_start for old_start, old_end in occupied
            ):
                continue
            occupied.append((start, end))
            hits.append(match.group(0))
    return sorted(set(hits))


def has_provenance_signal(text: str) -> bool:
    return bool(PROVENANCE_HINT_RE.search(text) or URL_OR_CITATION_RE.search(text))


def markdown_table_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Return zero-based [start, end) ranges for conventional Markdown tables."""

    ranges: list[tuple[int, int]] = []
    index = 0
    while index + 1 < len(lines):
        if "|" in lines[index] and TABLE_SEPARATOR_RE.match(lines[index + 1]):
            end = index + 2
            while end < len(lines) and "|" in lines[end] and lines[end].strip():
                end += 1
            ranges.append((index, end))
            index = end
        else:
            index += 1
    return ranges


def find_quantitative_claim_warnings(text: str) -> list[str]:
    """Flag unsupported quantities once per table or prose block, not once per row."""

    lines = text.splitlines()
    warnings: list[str] = []
    table_line_indexes: set[int] = set()

    for start, end in markdown_table_ranges(lines):
        table_line_indexes.update(range(start, end))
        block = "\n".join(lines[start:end])
        nearby_context = "\n".join(lines[max(0, start - 2) : min(len(lines), end + 3)])
        if QUANTITATIVE_CLAIM_RE.search(block) and not has_provenance_signal(
            nearby_context
        ):
            warnings.append(
                f"table starting line {start + 1}: quantitative claims may need "
                "source, date, region, unit, or assumption label"
            )

    # A wrapped prose paragraph is one claim context. This also lets a source
    # line support the quantity immediately above it.
    paragraph_start: int | None = None
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_start, paragraph_lines
        if paragraph_start is None:
            return
        block = "\n".join(paragraph_lines)
        if QUANTITATIVE_CLAIM_RE.search(block) and not has_provenance_signal(block):
            warnings.append(
                f"paragraph starting line {paragraph_start + 1}: quantitative claim "
                "may need source, date, region, unit, or assumption label"
            )
        paragraph_start = None
        paragraph_lines = []

    for index, line in enumerate(lines):
        if index in table_line_indexes or not line.strip():
            flush_paragraph()
            continue
        if paragraph_start is None:
            paragraph_start = index
        paragraph_lines.append(line)
    flush_paragraph()
    return warnings


def term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 /.-]*", term):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def configured_definition_variants(definition: str) -> list[str]:
    parts = [
        part.strip(" \t,，;；")
        for part in re.split(r"[()（）]", definition)
        if part.strip(" \t,，;；")
    ]
    return unique_strings([definition.strip(), *parts])


def find_terminology_warnings(text: str, rules: dict) -> list[str]:
    warnings: list[str] = []
    restricted_words = rules.get("restricted_words", {})
    standard_terms = rules.get("standard_terms", {})

    if isinstance(restricted_words, dict):
        for word, replacement in restricted_words.items():
            if not isinstance(word, str) or not word:
                continue
            matches = term_pattern(word).findall(text)
            if matches:
                warnings.append(
                    f"restricted term '{word}' appears {len(matches)} time(s); "
                    f"consider '{replacement}' when context supports it"
                )

    if isinstance(standard_terms, dict):
        for abbreviation, definition in standard_terms.items():
            if not isinstance(abbreviation, str) or not isinstance(definition, str):
                continue
            match = term_pattern(abbreviation).search(text)
            if not match:
                continue
            variants = configured_definition_variants(definition)
            first_use_context = text[max(0, match.start() - 160) : match.end() + 160]
            full_text_has_definition = any(
                variant and variant.casefold() in text.casefold()
                for variant in variants
            )
            first_use_has_definition = any(
                variant and variant.casefold() in first_use_context.casefold()
                for variant in variants
            )
            if not full_text_has_definition or not first_use_has_definition:
                warnings.append(
                    f"abbreviation '{abbreviation}' should be defined at first use; "
                    f"configured definition: '{definition}'"
                )
    return warnings


def scalar_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        values: list[str] = []
        for child in value.values():
            values.extend(scalar_text_values(child))
        return values
    if isinstance(value, list):
        values = []
        for child in value:
            values.extend(scalar_text_values(child))
        return values
    return []


def detect_compliance_topics(text: str, blackboard: dict, rules: dict) -> list[str]:
    review_topics = rules.get("review_topics", {})
    healthcare_topics = (
        review_topics.get("healthcare", []) if isinstance(review_topics, dict) else []
    )
    if not isinstance(healthcare_topics, list):
        return []
    corpus = "\n".join([text, *scalar_text_values(blackboard)]).casefold()
    matches: list[str] = []
    for topic in healthcare_topics:
        if not isinstance(topic, str):
            continue
        keywords = COMPLIANCE_TOPIC_KEYWORDS.get(topic, (topic.replace("_", " "),))
        if any(term_pattern(keyword).search(corpus) for keyword in keywords):
            matches.append(topic)
    return matches


def nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def compliance_context(blackboard: dict) -> dict:
    candidates: list[Any] = [
        blackboard.get("compliance_context"),
        blackboard.get("compliance"),
        blackboard.get("decision_context"),
    ]
    alignment = blackboard.get("alignment")
    if isinstance(alignment, dict):
        candidates.extend(
            [
                alignment.get("compliance_context"),
                alignment.get("compliance"),
                alignment.get("decision_context"),
                alignment,
            ]
        )
    metadata = blackboard.get("metadata")
    if isinstance(metadata, dict):
        candidates.append(metadata)

    merged: dict[str, Any] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, value in candidate.items():
            if key not in merged and nonempty(value):
                merged[key] = value

    # decision_schema.md uses business-friendly names for three of the fields
    # required by compliance_rules.json. Keep the rules canonical while
    # accepting those documented aliases from the Blackboard.
    aliases = {
        "jurisdiction": ("geographies", "geography", "region"),
        "data_types": ("data_context_summary", "data_scope"),
        "affected_users": ("affected_population", "affected_people"),
    }
    for canonical, alternatives in aliases.items():
        if nonempty(merged.get(canonical)):
            continue
        for alternative in alternatives:
            if nonempty(merged.get(alternative)):
                merged[canonical] = merged[alternative]
                break
    return merged


def check_high_risk_compliance(
    text: str, blackboard: dict, rules: dict
) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    topics = detect_compliance_topics(text, blackboard, rules)
    if not topics:
        return errors, warnings, topics

    required_fields = rules.get("required_context", [])
    if not isinstance(required_fields, list) or not all(
        isinstance(field, str) and field for field in required_fields
    ):
        errors.append("compliance rules required_context must be a list of field names")
        return errors, warnings, topics

    context = compliance_context(blackboard)
    missing = [field for field in required_fields if not nonempty(context.get(field))]
    if missing:
        warnings.append(
            "high-risk compliance context is incomplete; missing: " + ", ".join(missing)
        )
    if context.get("applicability") != "required":
        warnings.append(
            "high-risk topics are present but compliance_context.applicability "
            "is not recorded as required"
        )

    if not professional_review_record_complete(context):
        verification_rule = str(rules.get("verification_rule", "")).strip()
        message = (
            "high-risk topics still require a completed, named professional review "
            "record: " + ", ".join(topics)
        )
        if verification_rule:
            message += f"; configured rule: {verification_rule}"
        warnings.append(message)
    return errors, warnings, topics


def professional_review_record_complete(context: dict) -> bool:
    if str(context.get("status", "")).strip().casefold() not in {
        "reviewed",
        "professionally_reviewed",
    }:
        return False

    review_required = context.get("review_required")
    records: Any
    if isinstance(review_required, list):
        records = review_required
    elif review_required is True:
        records = context.get("escalations")
    else:
        return False
    if not isinstance(records, list) or not records:
        return False

    for record in records:
        if not isinstance(record, dict):
            return False
        reviewer = record.get("reviewer") or record.get("reviewer_name")
        role = record.get("role") or record.get("reviewer_role")
        as_of = record.get("as_of") or record.get("reviewed_at")
        status = str(record.get("status", "")).strip().casefold()
        if not all(nonempty(value) for value in (reviewer, role, as_of)):
            return False
        if status not in {"completed", "accepted"}:
            return False
    return True


def nested_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def blackboard_mode_errors(blackboard: dict, requested_mode: str) -> list[str]:
    errors: list[str] = []
    metadata_mode = str(nested_dict(blackboard.get("metadata")).get("mode", "")).strip()
    alignment_mode = str(
        nested_dict(blackboard.get("alignment")).get("mode", "")
    ).strip()

    for location, recorded_mode in (
        ("metadata.mode", metadata_mode),
        ("alignment.mode", alignment_mode),
    ):
        if recorded_mode and recorded_mode not in SUPPORTED_MODES:
            errors.append(f"blackboard {location} is unsupported: {recorded_mode}")
        elif recorded_mode and recorded_mode != requested_mode:
            errors.append(
                f"mode mismatch: report mode is {requested_mode}, "
                f"blackboard {location} is {recorded_mode}"
            )
    if metadata_mode and alignment_mode and metadata_mode != alignment_mode:
        errors.append(
            "blackboard mode mismatch: metadata.mode and alignment.mode do not agree"
        )
    return unique_strings(errors)


def normalize_maturity(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def blackboard_maturity(blackboard: dict) -> tuple[str, list[str]]:
    metadata = nested_dict(blackboard.get("metadata"))
    alignment = nested_dict(blackboard.get("alignment"))
    decision_context = nested_dict(blackboard.get("decision_context"))
    decisions = nested_dict(blackboard.get("decisions"))
    candidates = [
        ("maturity", blackboard.get("maturity")),
        ("metadata.maturity", metadata.get("maturity")),
        ("alignment.maturity", alignment.get("maturity")),
        ("decision_context.maturity", decision_context.get("maturity")),
        ("decisions.maturity", decisions.get("maturity")),
    ]
    recorded = [
        (location, normalize_maturity(value))
        for location, value in candidates
        if nonempty(value)
    ]
    if not recorded:
        return "", ["blackboard maturity is required"]

    errors: list[str] = []
    for location, value in recorded:
        if value not in MATURITY_VALUES:
            errors.append(
                f"blackboard {location} has unsupported maturity '{value}'; "
                f"expected one of: {', '.join(MATURITY_VALUES)}"
            )
    distinct = {value for _, value in recorded}
    if len(distinct) > 1:
        errors.append("blackboard maturity fields do not agree")
    return recorded[0][1], errors


def report_maturity(text: str) -> str:
    match = re.search(
        r"(?mi)^\s*(?:[-*+]\s+)?(?:\*\*|__)?"
        r"(?:成果成熟度|成熟度|maturity)(?:\*\*|__)?\s*[:：]\s*`?"
        r"(working[-_ ]draft|review[-_ ]ready|decision[-_ ]ready|"
        r"approved[-_ ]for[-_ ]execution|blocked)\b",
        text,
        re.IGNORECASE,
    )
    return normalize_maturity(match.group(1)) if match else ""


def maturity_checks(
    text: str, blackboard: dict, *, strict: bool
) -> tuple[list[str], list[str], str]:
    errors: list[str] = []
    warnings: list[str] = []
    maturity, maturity_errors = blackboard_maturity(blackboard)
    errors.extend(maturity_errors)
    if not maturity or maturity not in MATURITY_VALUES:
        return errors, warnings, maturity

    stated_maturity = report_maturity(text)
    if not stated_maturity:
        warnings.append("report does not state the blackboard maturity")
    elif stated_maturity != maturity:
        errors.append(
            f"maturity mismatch: report states {stated_maturity}, "
            f"blackboard records {maturity}"
        )

    if maturity == "working_draft":
        warnings.append(
            "blackboard maturity is working_draft; do not present it as decision-ready"
        )
    elif maturity == "blocked":
        errors.append("blackboard maturity is blocked")
    elif maturity == "approved_for_execution":
        context = compliance_context(blackboard)
        approval = context.get("authority_and_approvals") or metadata_approval(
            blackboard
        )
        if not approval_record_complete(approval):
            errors.append(
                "approved_for_execution requires a recorded approving authority and conditions"
            )
    if maturity in {"decision_ready", "approved_for_execution"} and not strict:
        errors.append(f"{maturity} delivery requires --strict")
    return errors, warnings, maturity


def metadata_approval(blackboard: dict) -> Any:
    metadata = nested_dict(blackboard.get("metadata"))
    decisions = nested_dict(blackboard.get("decisions"))
    return (
        blackboard.get("approval")
        or metadata.get("approval")
        or metadata.get("approved_by")
        or decisions.get("approval")
        or decisions.get("approved_by")
    )


def approval_record_complete(approval: Any) -> bool:
    if isinstance(approval, list):
        return bool(approval) and all(
            approval_record_complete(item) for item in approval
        )
    if not isinstance(approval, dict):
        return False
    required = ("authority", "authority_role", "decision", "as_of", "source")
    return all(nonempty(approval.get(field)) for field in required)


def evaluate(
    text: str,
    mode: str,
    blackboard: dict,
    blackboard_errors: list[str] | None = None,
    *,
    strict: bool = False,
    textual_only: bool = False,
    medical_terms: dict | None = None,
    compliance_rules: dict | None = None,
    configuration_errors: list[str] | None = None,
) -> dict:
    supplied_blackboard_errors = list(blackboard_errors or [])
    errors = list(supplied_blackboard_errors)
    errors.extend(configuration_errors or [])
    warnings: list[str] = []
    compliance_topics: list[str] = []
    maturity = ""
    blackboard_ready: bool | None = None

    if mode not in SUPPORTED_MODES:
        errors.append(f"unsupported report mode: {mode}")

    if not text.strip():
        errors.append("report text is empty")

    placeholders = find_placeholders(text)
    if placeholders:
        errors.append("unresolved placeholders: " + ", ".join(placeholders[:8]))

    if textual_only:
        maturity = report_maturity(text)
        if mode != "brief" or blackboard:
            errors.append("--textual-only requires brief mode without a blackboard")
        if strict:
            errors.append("--textual-only cannot be used with --strict")
        if maturity not in {"working_draft", "review_ready"} or re.search(
            r"\b(?:decision[-_ ]ready|approved[-_ ]for[-_ ]execution|blocked)\b",
            text,
            re.IGNORECASE,
        ):
            errors.append(
                "textual-only requires explicit draft maturity and no formal or blocked status"
            )
        warnings.append(
            "textual-only draft check: evidence, financial, compliance and decision readiness "
            "are not validated; not authorization for formal financial or decision delivery"
        )

    if not blackboard:
        if not textual_only and not supplied_blackboard_errors:
            errors.append("blackboard JSON object is empty")
    elif validate_state is None:
        errors.append(BLACKBOARD_IMPORT_ERROR or "blackboard validator is unavailable")
    else:
        try:
            state_report = validate_state(blackboard)
        except Exception as exc:
            errors.append(f"blackboard validation failed: {exc}")
        else:
            if not isinstance(state_report, dict):
                errors.append("blackboard validator returned a non-object report")
            else:
                blackboard_ready = state_report.get("ready") is True
                state_errors = state_report.get("errors", [])
                state_warnings = state_report.get("warnings", [])
                if isinstance(state_errors, list):
                    errors.extend(
                        format_blackboard_issue(item) for item in state_errors
                    )
                else:
                    errors.append(
                        "blackboard validator returned invalid errors payload"
                    )
                if isinstance(state_warnings, list):
                    warnings.extend(
                        format_blackboard_issue(item) for item in state_warnings
                    )
                else:
                    errors.append(
                        "blackboard validator returned invalid warnings payload"
                    )

        errors.extend(blackboard_mode_errors(blackboard, mode))
        maturity_errors, maturity_warnings, maturity = maturity_checks(
            text, blackboard, strict=strict
        )
        errors.extend(maturity_errors)
        warnings.extend(maturity_warnings)

        logic_mesh = nested_dict(blackboard.get("logic_mesh"))
        decisions = nested_dict(blackboard.get("decisions"))
        judgment = str(logic_mesh.get("core_judgment", "")).strip()
        action_levers = decisions.get("action_levers", []) or []
        residual_risks = decisions.get("residual_risks", []) or []
        if judgment and not contains_any(
            text, [judgment, "中心判断", "核心判断", "core judgment"]
        ):
            warnings.append("report may not state the blackboard core judgment")
        if action_levers and not contains_any(
            text, ["行动", "建议", "举措", "action", "recommendation"]
        ):
            warnings.append("report may omit recorded action options")
        if residual_risks and not contains_any(
            text, ["风险", "限制", "不确定", "risk", "limitation"]
        ):
            warnings.append("report may omit recorded residual risks")

    if medical_terms is None:
        medical_terms, term_errors = load_json_object(
            MEDICAL_TERMS_PATH, "medical terms"
        )
        errors.extend(term_errors)
    if medical_terms:
        warnings.extend(find_terminology_warnings(text, medical_terms))

    if compliance_rules is None:
        compliance_rules, rule_errors = load_json_object(
            COMPLIANCE_RULES_PATH, "compliance rules"
        )
        errors.extend(rule_errors)
    if compliance_rules and blackboard:
        compliance_errors, compliance_warnings, compliance_topics = (
            check_high_risk_compliance(text, blackboard, compliance_rules)
        )
        errors.extend(compliance_errors)
        warnings.extend(compliance_warnings)

    word_count = count_words(text)
    if text.strip():
        warnings.extend(find_quantitative_claim_warnings(text))

    errors = unique_strings(errors)
    warnings = unique_strings(warnings)
    blocking = bool(errors or (strict and warnings))
    status = "fail" if blocking else ("pass_with_warnings" if warnings else "pass")
    return {
        "status": status,
        "blocking": blocking,
        "strict": strict,
        "errors": errors,
        "warnings": warnings,
        "word_count": word_count,
        "mode": mode,
        "maturity": maturity or None,
        "blackboard_ready": blackboard_ready,
        "scope": "textual_only" if textual_only else "report_and_blackboard",
        "unchecked": ["evidence", "financial", "compliance", "decision_readiness"]
        if textual_only
        else [],
        "compliance_review_topics": compliance_topics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Validate report, Blackboard, terminology, and compliance context."
    )
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=SUPPORTED_MODES)
    parser.add_argument("--blackboard", type=Path)
    parser.add_argument(
        "--textual-only",
        action="store_true",
        help="Only check brief draft text without Blackboard; never validates financial or decision readiness.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero for deterministic errors and quality warnings.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        text = args.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        emit_json(
            {
                "status": "fail",
                "blocking": True,
                "strict": args.strict,
                "errors": [f"cannot read report: {exc}"],
                "warnings": [],
                "path": str(args.path.resolve()),
                "blackboard_path": (
                    str(args.blackboard.resolve()) if args.blackboard else None
                ),
                "mode": args.mode,
            }
        )
        return 1

    if args.textual_only and args.blackboard is None:
        blackboard, blackboard_errors = {}, []
    else:
        blackboard, blackboard_errors = load_blackboard(args.blackboard)
    if args.textual_only and args.blackboard is not None:
        blackboard_errors.append("--textual-only does not accept --blackboard")
    medical_terms, term_errors = load_json_object(MEDICAL_TERMS_PATH, "medical terms")
    compliance_rules, compliance_errors = load_json_object(
        COMPLIANCE_RULES_PATH, "compliance rules"
    )
    report = evaluate(
        text,
        args.mode,
        blackboard,
        blackboard_errors,
        strict=args.strict,
        textual_only=args.textual_only,
        medical_terms=medical_terms,
        compliance_rules=compliance_rules,
        configuration_errors=[*term_errors, *compliance_errors],
    )
    report["path"] = str(args.path.resolve())
    report["blackboard_path"] = (
        str(args.blackboard.resolve()) if args.blackboard else None
    )
    emit_json(report)
    return 1 if report["blocking"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        emit_json(
            {
                "status": "fail",
                "blocking": True,
                "errors": ["interrupted"],
                "warnings": [],
            }
        )
        sys.exit(130)
    except Exception as exc:  # final guard: never leak a traceback to automation
        emit_json(
            {
                "status": "fail",
                "blocking": True,
                "errors": [f"unexpected strategy gate failure: {exc}"],
                "warnings": [],
            }
        )
        sys.exit(1)
