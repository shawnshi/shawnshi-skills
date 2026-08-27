"""Validate version 2 presentation-blueprint Markdown without rewriting it.

Only exact standalone block markers and declared field names are structural.
Consequently, prose such as ``// SCRIPT`` or ``[Owner]:`` is not mistaken for
schema syntax.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
STYLE_INDEX_PATH = ROOT / "references" / "styles" / "index.json"
SCHEMA_VERSION = 2
VALIDATION_SCOPE = "structural"

METADATA_REQUIRED = [
    "Schema_Version",
    "Topic",
    "Audience",
    "Objective",
    "Occasion",
    "Deck_Mode",
    "Duration_Minutes",
    "Language",
    "Aspect_Ratio",
    "Confidentiality",
    "Status",
    "Slide_Count",
    "Generated",
]
METADATA_OPTIONAL = [
    "Template_Ref",
    "Decision_Owner",
    "Source_Cutoff",
    "Must_Keep",
    "Deck_ID",
    "Revision",
    "Prepared_By",
    "Reviewed_By",
]
METADATA_FIELDS = METADATA_REQUIRED + METADATA_OPTIONAL

STYLE_FIELDS = [
    "Style_ID",
    "Design_Aesthetic",
    "Background",
    "Typography",
    "Color_Palette",
    "Density",
    "Citation_Treatment",
    "Brand_Rules",
    "Accessibility",
]

SLIDE_HEADER_REQUIRED = ["Slide_ID", "Type", "Page"]
SLIDE_HEADER_OPTIONAL = ["Section"]
SLIDE_HEADER_FIELDS = SLIDE_HEADER_REQUIRED + SLIDE_HEADER_OPTIONAL

SLIDE_TYPES = {
    "Cover",
    "Executive-Summary",
    "Section",
    "Content",
    "Data",
    "Comparison",
    "Roadmap",
    "Decision",
    "Risk",
    "Closing",
    "Appendix",
    "References",
}
DECORATIVE_TYPES = {"Cover", "Section", "Closing"}
CONTENT_TYPES = SLIDE_TYPES - DECORATIVE_TYPES
TERMINAL_TYPES = {"Closing", "Decision"}
POST_TERMINAL_TYPES = {"Appendix", "References"}

BLOCK_MARKERS = ["// NARRATIVE", "// CONTENT", "// EVIDENCE", "// VISUAL", "// DELIVERY"]
END_MARKER = "// END SLIDE"
BLOCK_FIELDS = {
    "// NARRATIVE": ["Goal", "Title", "Takeaway"],
    "// CONTENT": ["Body", "Decision", "Action"],
    "// EVIDENCE": ["Claims", "Evidence", "Open Items", "Risk Flags"],
    "// VISUAL": ["Layout", "Visual Description", "Chart", "Assets"],
    "// DELIVERY": ["Speaker Notes", "Delivery Notes"],
}

CONFIDENTIALITY_VALUES = {"public", "internal", "confidential", "restricted"}
STATUS_VALUES = {"draft", "final"}
DECK_MODE_VALUES = {"full", "section", "one_pager"}
DENSITY_VALUES = {"minimal", "balanced", "dense"}
CITATION_VALUES = {"visible-footer", "inline", "source-note", "not-applicable"}
CLAIM_KINDS = {"fact", "inference", "assumption", "recommendation"}
CLAIM_STATUSES = {"verified", "partial", "unverified"}
OPEN_ITEM_KINDS = {"data", "decision", "asset", "compliance"}
SEVERITIES = {"low", "medium", "high", "critical"}
RISK_CATEGORIES = {"privacy", "security", "legal", "financial", "clinical", "delivery", "reputation", "other"}
ASSET_RIGHTS = {"owned", "licensed", "public-domain", "permission-pending", "not-applicable"}
DEIDENTIFICATION_VALUES = {"not-required", "verified", "pending"}
LAYOUT_IDS = {
    "title-hero",
    "executive-summary",
    "key-stat",
    "two-columns",
    "binary-comparison",
    "comparison-matrix",
    "chart-plus-insight",
    "dashboard",
    "linear-roadmap",
    "swimlane",
    "layered-architecture",
    "hub-spoke",
    "decision-card",
    "risk-matrix",
    "risk-register",
    "quote-callout",
    "reference-list",
    "appendix-detail",
}
CUSTOM_LAYOUT_RE = re.compile(r"^custom:[a-z0-9]+(?:-[a-z0-9]+)*$")

SLIDE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,63}$")
FIELD_LINE_TEMPLATE = r"(?m)^\[(?P<name>{names})\]:[ \t]*(?P<inline>[^\n]*)$"
PLACEHOLDER_PATTERNS = [
    ("moustache", re.compile(r"\{\{[^{}\n]+\}\}")),
    ("tbd", re.compile(r"(?i)(?<![A-Za-z0-9])TBD(?![A-Za-z0-9])")),
    ("todo", re.compile(r"(?i)(?<![A-Za-z0-9])TODO(?![A-Za-z0-9])")),
    ("chinese", re.compile(r"待补|待确认|待核验")),
    ("insert", re.compile(r"(?i)\[INSERT(?:[^\]\n]*)\]")),
    ("baseline", re.compile(r"(?i)\[BASELINE(?:[^\]\n]*)\]")),
]

SLIDE_RE = re.compile(
    r"(?ms)^---[ \t]*\n"
    r"(?P<header>.*?)"
    r"^---[ \t]*\n"
    r"(?P<body>.*?)"
    r"^// END SLIDE[ \t]*$"
)


def issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _unwrap_markdown_fence(content: str) -> tuple[str, str]:
    """Return payload and text outside a case-insensitive Markdown fence."""

    normalized = normalize(content)
    fence_re = re.compile(r"(?ims)^```(?:markdown|md)[ \t]*\n(?P<body>.*?)\n```[ \t]*$")
    candidates = [m for m in fence_re.finditer(normalized) if "<DECK_METADATA>" in m.group("body")]
    if not candidates:
        return normalized, ""
    chosen = candidates[0]
    outside = normalized[: chosen.start()] + normalized[chosen.end() :]
    return chosen.group("body"), outside


def extract_payload(content: str) -> str:
    """Compatibility helper returning only the unwrapped payload."""

    return _unwrap_markdown_fence(content)[0]


def load_source(path: Path | str) -> tuple[str, list[str]]:
    candidate = Path(path)
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8-sig"), [str(candidate)]
    if not candidate.is_dir():
        raise FileNotFoundError(f"Path does not exist: {candidate}")
    outline = candidate / "outline.md"
    if not outline.is_file():
        raise FileNotFoundError(f"Directory does not contain the required outline.md: {candidate}")
    return outline.read_text(encoding="utf-8-sig"), [str(outline)]


def _valid_iso_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _draft_placeholder(value: str, is_draft: bool) -> bool:
    return is_draft and any(pattern.search(value) for _, pattern in PLACEHOLDER_PATTERNS)


def _tag(content: str, tag: str, errors: list[dict[str, Any]]) -> tuple[str, tuple[int, int] | None]:
    opening, closing = f"<{tag}>", f"</{tag}>"
    opening_count, closing_count = content.count(opening), content.count(closing)
    if opening_count != 1 or closing_count != 1:
        errors.append(
            issue(
                "E_TAG_CARDINALITY",
                f"{tag} 必须各有一个开始和结束标签。",
                tag=tag,
                opening_count=opening_count,
                closing_count=closing_count,
            )
        )
        return "", None
    match = re.search(rf"(?s){re.escape(opening)}(.*?){re.escape(closing)}", content)
    if not match:
        errors.append(issue("E_TAG_ORDER", f"{tag} 标签嵌套或顺序无效。", tag=tag))
        return "", None
    value = match.group(1).strip()
    if not value:
        errors.append(issue("E_EMPTY_TAG", f"{tag} 内容为空。", tag=tag))
    return value, match.span()


def parse_key_values(
    text: str,
    required: list[str],
    optional: list[str],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    context: str,
) -> dict[str, str]:
    allowed = required + optional
    values: dict[str, str] = {}
    order: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if ":" not in line:
            errors.append(issue("E_KEY_VALUE_LINE", f"{context} 中存在无法解析的行。", line=line_number, value=line))
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        order.append(key)
        if key in values:
            errors.append(issue("E_DUPLICATE_FIELD", f"{context} 字段重复。", field=key))
        values[key] = value

    for field in required:
        if field not in values:
            errors.append(issue("E_MISSING_FIELD", f"{context} 缺少字段。", field=field))
        elif not values[field]:
            errors.append(issue("E_EMPTY_FIELD", f"{context} 字段为空。", field=field))
    for field in optional:
        if field in values and not values[field]:
            errors.append(issue("E_EMPTY_FIELD", f"{context} 可选字段不得为空。", field=field))
    unknown = [field for field in values if field not in allowed]
    if unknown:
        errors.append(issue("E_UNKNOWN_FIELD", f"{context} 包含未声明字段。", fields=unknown))
    known_order = [field for field in order if field in allowed]
    expected_order = [field for field in allowed if field in values]
    if known_order != expected_order:
        warnings.append(issue("W_FIELD_ORDER", f"{context} 字段顺序偏离推荐顺序。"))
    return values


@lru_cache(maxsize=1)
def _style_ids_from_index() -> tuple[set[str], str | None]:
    try:
        data = json.loads(STYLE_INDEX_PATH.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return set(), "style index is missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return set(), str(exc)

    styles = data.get("styles") if isinstance(data, dict) else None
    if not isinstance(styles, list):
        return set(), "style index must contain a styles array"
    identifiers = {
        item["id"].strip()
        for item in styles
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    }
    return identifiers, None


def _field_regex(fields: Iterable[str]) -> re.Pattern[str]:
    names = "|".join(re.escape(field) for field in fields)
    return re.compile(FIELD_LINE_TEMPLATE.format(names=names))


def parse_fields(
    text: str,
    required: list[str],
    optional: list[str],
    slide_index: int,
    block: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, str]:
    """Parse known fields only; bracketed prose stays inside its field value."""

    allowed = required + optional
    matches = list(_field_regex(allowed).finditer(text))
    if not matches:
        errors.append(issue("E_NO_NESTED_FIELDS", f"Slide {slide_index} 的区块缺少字段。", block=block))
        return {}
    if text[: matches[0].start()].strip():
        errors.append(issue("E_UNEXPECTED_BLOCK_PREFIX", f"Slide {slide_index} 的区块在首个字段前含有未声明内容。", block=block))

    parsed: dict[str, str] = {}
    order: list[str] = []
    for index, match in enumerate(matches):
        name = match.group("name")
        inline = match.group("inline").strip()
        tail_start = match.end()
        tail_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tail = text[tail_start:tail_end].strip()
        value = "\n".join(part for part in (inline, tail) if part).strip()
        order.append(name)
        if name in parsed:
            errors.append(issue("E_DUPLICATE_FIELD", f"Slide {slide_index} 的嵌套字段重复。", block=block, field=name))
        parsed[name] = value

    missing = [field for field in required if field not in parsed]
    empty = [field for field in allowed if field in parsed and not parsed[field]]
    if missing:
        errors.append(issue("E_MISSING_FIELD", f"Slide {slide_index} 的区块缺少字段。", block=block, fields=missing))
    if empty:
        errors.append(issue("E_EMPTY_FIELD", f"Slide {slide_index} 的区块包含空字段。", block=block, fields=empty))
    expected_order = [field for field in allowed if field in parsed]
    if order != expected_order:
        warnings.append(issue("W_FIELD_ORDER", f"Slide {slide_index} 的字段顺序偏离推荐顺序。", block=block))
    return parsed


def split_blocks(body: str, slide_index: int, slide_type: str, errors: list[dict[str, Any]]) -> dict[str, str]:
    marker_re = re.compile(rf"(?m)^(?P<marker>{'|'.join(re.escape(item) for item in BLOCK_MARKERS)})[ \t]*$")
    matches = list(marker_re.finditer(body))
    grouped: dict[str, list[re.Match[str]]] = {marker: [] for marker in BLOCK_MARKERS}
    for match in matches:
        grouped[match.group("marker")].append(match)

    required = ["// NARRATIVE", "// VISUAL", "// DELIVERY"]
    if slide_type in CONTENT_TYPES:
        required += ["// CONTENT", "// EVIDENCE"]
    for marker in BLOCK_MARKERS:
        count = len(grouped[marker])
        if marker in required and count != 1:
            errors.append(issue("E_BLOCK_CARDINALITY", f"Slide {slide_index} 缺少或重复必需区块。", block=marker, count=count))
        elif marker not in required and count > 1:
            errors.append(issue("E_BLOCK_CARDINALITY", f"Slide {slide_index} 的可选区块不得重复。", block=marker, count=count))
    if not matches:
        return {}
    if body[: matches[0].start()].strip():
        errors.append(issue("E_UNEXPECTED_SLIDE_PREFIX", f"Slide {slide_index} 在首个区块前含有未声明内容。"))

    actual_markers = [match.group("marker") for match in matches]
    expected_markers = [marker for marker in BLOCK_MARKERS if marker in actual_markers]
    if actual_markers != expected_markers:
        errors.append(issue("E_BLOCK_ORDER", f"Slide {slide_index} 的顶层区块顺序不符合 Schema。", actual=actual_markers))

    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        marker = match.group("marker")
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[start:end].strip()
        if marker not in blocks:
            blocks[marker] = value
        if not value:
            errors.append(issue("E_EMPTY_BLOCK", f"Slide {slide_index} 的顶层区块为空。", block=marker))
    return blocks


def _parse_pipe_records(
    value: str,
    *,
    record_type: str,
    columns: int,
    id_pattern: str,
    slide_index: int,
    errors: list[dict[str, Any]],
) -> list[list[str]]:
    if value.strip().lower() == "none":
        return []
    records: list[list[str]] = []
    identifiers: set[str] = set()
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        if not re.match(r"^-[ \t]+", line):
            errors.append(issue("E_RECORD_FORMAT", f"Slide {slide_index} 的 {record_type} 记录必须以 '- ' 开始。", line=line_number, value=line))
            continue
        parts = [part.strip() for part in re.sub(r"^-[ \t]+", "", line, count=1).split("|")]
        if len(parts) != columns:
            errors.append(issue("E_RECORD_FORMAT", f"Slide {slide_index} 的 {record_type} 记录列数不正确。", line=line_number, expected=columns, actual=len(parts)))
            continue
        if any(not part for part in parts):
            errors.append(issue("E_RECORD_EMPTY_VALUE", f"Slide {slide_index} 的 {record_type} 记录含有空值。", line=line_number))
        identifier = parts[0]
        if not re.fullmatch(id_pattern, identifier):
            errors.append(issue("E_RECORD_ID", f"Slide {slide_index} 的 {record_type} ID 无效。", line=line_number, value=identifier))
        if identifier in identifiers:
            errors.append(issue("E_DUPLICATE_RECORD_ID", f"Slide {slide_index} 的 {record_type} ID 重复。", value=identifier))
        identifiers.add(identifier)
        records.append(parts)
    if not records:
        errors.append(issue("E_RECORD_FORMAT", f"Slide {slide_index} 的 {record_type} 既不是 none，也没有有效记录。"))
    return records


def _validate_records(slide: dict[str, Any], index: int, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    content, evidence_block, visual = slide["content"], slide["evidence"], slide["visual"]
    is_draft = bool(slide.get("is_draft"))
    decisions: list[list[str]] = []
    if "Decision" in content:
        decisions = _parse_pipe_records(content["Decision"], record_type="Decision", columns=5, id_pattern=r"D\d+", slide_index=index, errors=errors)

    claims: list[list[str]] = []
    evidence: list[list[str]] = []
    open_items: list[list[str]] = []
    risks: list[list[str]] = []
    if evidence_block:
        claims = _parse_pipe_records(evidence_block.get("Claims", ""), record_type="Claims", columns=5, id_pattern=r"C\d+", slide_index=index, errors=errors)
        evidence = _parse_pipe_records(evidence_block.get("Evidence", ""), record_type="Evidence", columns=5, id_pattern=r"E\d+", slide_index=index, errors=errors)
        open_items = _parse_pipe_records(evidence_block.get("Open Items", ""), record_type="Open Items", columns=5, id_pattern=r"O\d+", slide_index=index, errors=errors)
        risks = _parse_pipe_records(evidence_block.get("Risk Flags", ""), record_type="Risk Flags", columns=5, id_pattern=r"R\d+", slide_index=index, errors=errors)
    assets: list[list[str]] = []
    if "Assets" in visual:
        assets = _parse_pipe_records(visual["Assets"], record_type="Assets", columns=4, id_pattern=r"A\d+", slide_index=index, errors=errors)

    for record in decisions:
        if not _draft_placeholder(record[4], is_draft) and record[4] != "unscheduled" and not _valid_iso_date(record[4]):
            errors.append(issue("E_RECORD_DATE", f"Slide {index} 的 Decision 日期必须是 ISO 日期或 unscheduled。", record_id=record[0], value=record[4]))
    for record in claims:
        if not _draft_placeholder(record[1], is_draft) and record[1] not in CLAIM_KINDS:
            errors.append(issue("E_CLAIM_KIND", f"Slide {index} 的 Claim kind 无效。", record_id=record[0], value=record[1]))
        if not _draft_placeholder(record[2], is_draft) and record[2] not in CLAIM_STATUSES:
            errors.append(issue("E_CLAIM_STATUS", f"Slide {index} 的 Claim status 无效。", record_id=record[0], value=record[2]))
    for record in evidence:
        if not _draft_placeholder(record[2], is_draft) and record[2] != "undated" and not _valid_iso_date(record[2]):
            errors.append(issue("E_EVIDENCE_DATE", f"Slide {index} 的 Evidence 日期必须是 ISO 日期或 undated。", record_id=record[0], value=record[2]))
    for record in open_items:
        if not _draft_placeholder(record[1], is_draft) and record[1] not in OPEN_ITEM_KINDS:
            errors.append(issue("E_OPEN_ITEM_KIND", f"Slide {index} 的 Open Item kind 无效。", record_id=record[0], value=record[1]))
        if not _draft_placeholder(record[4], is_draft) and record[4] != "unscheduled" and not _valid_iso_date(record[4]):
            errors.append(issue("E_RECORD_DATE", f"Slide {index} 的 Open Item 日期必须是 ISO 日期或 unscheduled。", record_id=record[0], value=record[4]))
    for record in risks:
        if not _draft_placeholder(record[1], is_draft) and record[1] not in RISK_CATEGORIES:
            errors.append(issue("E_RISK_CATEGORY", f"Slide {index} 的 Risk category 无效。", record_id=record[0], value=record[1]))
        if not _draft_placeholder(record[2], is_draft) and record[2] not in SEVERITIES:
            errors.append(issue("E_RISK_SEVERITY", f"Slide {index} 的 Risk severity 无效。", record_id=record[0], value=record[2]))
    for record in assets:
        if not _draft_placeholder(record[2], is_draft) and record[2] not in ASSET_RIGHTS:
            errors.append(issue("E_ASSET_RIGHTS", f"Slide {index} 的 Assets rights 无效。", record_id=record[0], value=record[2]))
        if not _draft_placeholder(record[3], is_draft) and record[3] not in DEIDENTIFICATION_VALUES:
            errors.append(issue("E_ASSET_DEIDENTIFICATION", f"Slide {index} 的 Assets deidentification 无效。", record_id=record[0], value=record[3]))
        if record[2] == "permission-pending" or record[3] == "pending":
            target = warnings if is_draft else errors
            target.append(
                issue(
                    "W_ASSET_NOT_READY" if is_draft else "E_ASSET_NOT_READY",
                    f"Slide {index} 的资产尚未满足最终交付条件。",
                    record_id=record[0],
                    rights=record[2],
                    deidentification=record[3],
                )
            )

    evidence_ids = {record[0] for record in evidence}
    for record in claims:
        references = record[4]
        if references.lower() == "none":
            referenced_ids: list[str] = []
        elif re.fullmatch(r"E\d+(?:[ \t]*,[ \t]*E\d+)*", references):
            referenced_ids = [part.strip() for part in references.split(",")]
        else:
            errors.append(issue("E_EVIDENCE_REFERENCE_FORMAT", f"Slide {index} 的 Claim 证据引用格式无效。", record_id=record[0], value=references))
            referenced_ids = []
        missing = [item for item in referenced_ids if item not in evidence_ids]
        if missing:
            errors.append(issue("E_EVIDENCE_REFERENCE", f"Slide {index} 的 Claim 引用了不存在的 Evidence。", record_id=record[0], missing=missing))
        if record[2] in {"verified", "partial"} and not referenced_ids:
            errors.append(issue("E_EVIDENCE_REQUIRED", f"Slide {index} 的 verified/partial Claim 必须引用 Evidence。", record_id=record[0]))
        if record[2] == "unverified":
            warnings.append(issue("W_UNVERIFIED_CLAIM", f"Slide {index} 含有结构化未核验主张。", record_id=record[0]))

    cutoff = slide.get("source_cutoff")
    if cutoff and cutoff != "not-applicable" and _valid_iso_date(cutoff):
        for record in evidence:
            if record[2] != "undated" and _valid_iso_date(record[2]) and record[2] > cutoff:
                errors.append(issue("E_SOURCE_CUTOFF", f"Slide {index} 的 Evidence 日期晚于 Source_Cutoff。", record_id=record[0], evidence_date=record[2], source_cutoff=cutoff))

    if slide["type"] == "Decision" and not decisions:
        errors.append(issue("E_DECISION_REQUIRED", f"Slide {index} 的 Decision 页必须包含至少一条 Decision 记录。"))
    if slide["type"] == "Risk" and not risks:
        errors.append(issue("E_RISK_REQUIRED", f"Slide {index} 的 Risk 页必须包含至少一条 Risk Flags 记录。"))
    if slide["type"] in {"Data", "References"} and not evidence:
        errors.append(issue("E_EVIDENCE_REQUIRED", f"Slide {index} 的 {slide['type']} 页必须包含至少一条 Evidence 记录。"))

    slide["records"] = {
        "decisions": decisions,
        "claims": claims,
        "evidence": evidence,
        "open_items": open_items,
        "risk_flags": risks,
        "assets": assets,
    }


def _placeholder_instances(payload: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in PLACEHOLDER_PATTERNS:
        for match in pattern.finditer(payload):
            value = match.group(0)
            key = (kind, value)
            if key not in seen:
                seen.add(key)
                found.append({"kind": kind, "value": value})
    return found[:50]


def _source_schema_version(metadata_text: str) -> int | str:
    match = re.search(r"(?m)^Schema_Version:[ \t]*(?P<version>[^\n]+)$", metadata_text)
    if match:
        value = match.group("version").strip()
        try:
            return int(value)
        except ValueError:
            return value
    # The old canonical contract had these fields but no explicit version.
    if all(re.search(rf"(?m)^{name}:", metadata_text) for name in ("Topic", "Audience", "Objective", "Slide_Count")):
        return 1
    return "unknown"


def _validate_metadata(metadata: dict[str, str], source_schema_version: int | str, errors: list[dict[str, Any]]) -> None:
    if source_schema_version != SCHEMA_VERSION:
        errors.append(
            issue(
                "E_SCHEMA_VERSION_UNSUPPORTED",
                "仅支持 Schema v2；请先迁移旧蓝图。",
                source_schema_version=source_schema_version,
                migration_command="python scripts/migrate_v1.py <outline.md>",
            )
        )
    is_draft = metadata.get("Status") == "draft"
    duration = metadata.get("Duration_Minutes", "")
    if duration and not _draft_placeholder(duration, is_draft):
        try:
            if int(duration) <= 0:
                raise ValueError
        except ValueError:
            errors.append(issue("E_DURATION", "Duration_Minutes 必须是正整数。", value=duration))
    deck_mode = metadata.get("Deck_Mode", "")
    if deck_mode and not _draft_placeholder(deck_mode, is_draft) and deck_mode not in DECK_MODE_VALUES:
        errors.append(issue("E_DECK_MODE", "Deck_Mode 不在允许集合中。", value=deck_mode))
    confidentiality = metadata.get("Confidentiality", "")
    if confidentiality and not _draft_placeholder(confidentiality, is_draft) and confidentiality not in CONFIDENTIALITY_VALUES:
        errors.append(issue("E_CONFIDENTIALITY", "Confidentiality 不在允许集合中。", value=confidentiality))
    status = metadata.get("Status", "")
    if status and status not in STATUS_VALUES:
        errors.append(issue("E_STATUS", "Status 必须是 draft 或 final。", value=status))
    generated = metadata.get("Generated", "")
    if generated and not _draft_placeholder(generated, is_draft) and not _valid_iso_date(generated):
        errors.append(issue("E_GENERATED_DATE", "Generated 必须是有效 ISO 日期。", value=generated))
    cutoff = metadata.get("Source_Cutoff")
    if cutoff and not _draft_placeholder(cutoff, is_draft) and cutoff != "not-applicable" and not _valid_iso_date(cutoff):
        errors.append(issue("E_SOURCE_CUTOFF", "Source_Cutoff 必须是有效 ISO 日期或 not-applicable。", value=cutoff))


def _validate_style(style: dict[str, str], errors: list[dict[str, Any]], *, is_draft: bool = False) -> None:
    density = style.get("Density", "")
    if density and not _draft_placeholder(density, is_draft) and density not in DENSITY_VALUES:
        errors.append(issue("E_DENSITY", "Density 不在允许集合中。", value=density))
    citation = style.get("Citation_Treatment", "")
    if citation and not _draft_placeholder(citation, is_draft) and citation not in CITATION_VALUES:
        errors.append(issue("E_CITATION_TREATMENT", "Citation_Treatment 不在允许集合中。", value=citation))
    style_id = style.get("Style_ID", "")
    if style_id and not _draft_placeholder(style_id, is_draft) and style_id != "custom":
        known, index_error = _style_ids_from_index()
        if index_error:
            errors.append(issue("E_STYLE_INDEX", "无法核验 Style_ID。", detail=index_error))
        elif style_id not in known:
            errors.append(issue("E_STYLE_ID", "Style_ID 不在样式索引中，或应使用 custom。", value=style_id))


def _parse_slide(
    match: re.Match[str],
    index: int,
    source_cutoff: str | None,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    is_draft: bool = False,
) -> dict[str, Any]:
    header = parse_key_values(match.group("header").strip(), SLIDE_HEADER_REQUIRED, SLIDE_HEADER_OPTIONAL, errors, warnings, f"Slide {index} header")
    slide_type = header.get("Type", "")
    blocks = split_blocks(match.group("body"), index, slide_type, errors)

    narrative: dict[str, str] = {}
    content: dict[str, str] = {}
    evidence: dict[str, str] = {}
    visual: dict[str, str] = {}
    delivery: dict[str, str] = {}
    if "// NARRATIVE" in blocks:
        narrative_required = ["Goal", "Title"] + (["Takeaway"] if slide_type in CONTENT_TYPES else [])
        narrative_optional = [] if slide_type in CONTENT_TYPES else ["Takeaway"]
        narrative = parse_fields(blocks["// NARRATIVE"], narrative_required, narrative_optional, index, "// NARRATIVE", errors, warnings)
    if "// CONTENT" in blocks:
        content = parse_fields(blocks["// CONTENT"], ["Body"], ["Decision", "Action"], index, "// CONTENT", errors, warnings)
    if "// EVIDENCE" in blocks:
        evidence = parse_fields(blocks["// EVIDENCE"], ["Claims", "Evidence", "Open Items", "Risk Flags"], [], index, "// EVIDENCE", errors, warnings)
    if "// VISUAL" in blocks:
        visual = parse_fields(blocks["// VISUAL"], ["Layout", "Visual Description"], ["Chart", "Assets"], index, "// VISUAL", errors, warnings)
        layout = visual.get("Layout", "")
        if layout and not _draft_placeholder(layout, is_draft) and layout not in LAYOUT_IDS and not CUSTOM_LAYOUT_RE.fullmatch(layout):
            errors.append(
                issue(
                    "E_LAYOUT_ID",
                    f"Slide {index} 的 Layout 不在布局库中；自定义布局必须使用 custom:<slug>。",
                    value=layout,
                )
            )
    if "// DELIVERY" in blocks:
        delivery = parse_fields(blocks["// DELIVERY"], ["Speaker Notes"], ["Delivery Notes"], index, "// DELIVERY", errors, warnings)

    slide = {
        "slide_id": header.get("Slide_ID", ""),
        "type": slide_type,
        "page": header.get("Page", ""),
        "section": header.get("Section"),
        "narrative": narrative,
        "content": content,
        "evidence": evidence,
        "visual": visual,
        "delivery": delivery,
        "source_cutoff": source_cutoff,
        "is_draft": is_draft,
    }
    _validate_records(slide, index, errors, warnings)
    return slide


def audit_outline(content: str, allow_placeholders: bool | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit one blueprint; v2 placeholder behavior is controlled by Status."""

    del allow_placeholders
    payload, outside = _unwrap_markdown_fence(content)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if outside.strip():
        errors.append(issue("E_EXTERNAL_TEXT", "Markdown 代码围栏之外存在未解析文本。", excerpt=outside.strip()[:160]))

    metadata_text, metadata_span = _tag(payload, "DECK_METADATA", errors)
    style_text, style_span = _tag(payload, "STYLE_INSTRUCTIONS", errors)
    if metadata_span and style_span and metadata_span[0] > style_span[0]:
        errors.append(issue("E_TAG_ORDER", "DECK_METADATA 必须位于 STYLE_INSTRUCTIONS 之前。"))

    source_schema_version = _source_schema_version(metadata_text)
    metadata = parse_key_values(metadata_text, METADATA_REQUIRED, METADATA_OPTIONAL, errors, warnings, "DECK_METADATA")
    style = parse_key_values(style_text, STYLE_FIELDS, [], errors, warnings, "STYLE_INSTRUCTIONS")
    _validate_metadata(metadata, source_schema_version, errors)
    _validate_style(style, errors, is_draft=metadata.get("Status") == "draft")

    slide_matches = list(SLIDE_RE.finditer(payload))
    if not slide_matches:
        errors.append(issue("E_NO_SLIDES", "未检测到以 // END SLIDE 结束的幻灯片。"))

    covered: list[tuple[int, int]] = [span for span in (metadata_span, style_span) if span]
    covered += [match.span() for match in slide_matches]
    residual = list(payload)
    for start, end in covered:
        for position in range(start, end):
            residual[position] = " " if residual[position] != "\n" else "\n"
    unresolved = "".join(residual).strip()
    if unresolved:
        errors.append(issue("E_UNRESOLVED_TEXT", "蓝图含有未被标签或幻灯片结构解析的文本。", excerpt=unresolved[:200]))

    cutoff = metadata.get("Source_Cutoff")
    slides = [_parse_slide(match, index, cutoff, errors, warnings, is_draft=metadata.get("Status") == "draft") for index, match in enumerate(slide_matches, 1)]

    if style.get("Citation_Treatment") == "not-applicable" and any(slide["records"]["evidence"] for slide in slides):
        errors.append(issue("E_CITATION_REQUIRED", "存在 Evidence 记录时 Citation_Treatment 不能为 not-applicable。"))

    page_numbers: list[int] = []
    slide_ids: set[str] = set()
    for index, slide in enumerate(slides, 1):
        slide_id = slide["slide_id"]
        if slide_id and not SLIDE_ID_RE.fullmatch(slide_id):
            errors.append(issue("E_SLIDE_ID", f"Slide {index} 的 Slide_ID 格式无效。", value=slide_id))
        if slide_id in slide_ids:
            errors.append(issue("E_DUPLICATE_SLIDE_ID", f"Slide {index} 的 Slide_ID 重复。", value=slide_id))
        slide_ids.add(slide_id)
        try:
            page_numbers.append(int(slide["page"]))
        except (TypeError, ValueError):
            errors.append(issue("E_PAGE_NUMBER", f"Slide {index} 的 Page 必须是整数。", value=slide["page"]))
        if slide["type"] not in SLIDE_TYPES:
            errors.append(issue("E_SLIDE_TYPE", f"Slide {index} 的 Type 不在允许集合中。", value=slide["type"]))

    if page_numbers and page_numbers != list(range(1, len(slides) + 1)):
        errors.append(issue("E_PAGE_SEQUENCE", "页码必须从 1 开始连续递增。", actual=page_numbers))

    deck_mode = metadata.get("Deck_Mode")
    if deck_mode == "one_pager" and len(slides) != 1:
        errors.append(issue("E_ONE_PAGER_COUNT", "Deck_Mode=one_pager 时必须恰好一页。", actual=len(slides)))
    if deck_mode == "one_pager" and slides and slides[0]["type"] in {"Appendix", "References"}:
        errors.append(issue("E_ONE_PAGER_TYPE", "Deck_Mode=one_pager 不能使用 Appendix 或 References 类型。", value=slides[0]["type"]))
    if deck_mode == "full" and slides:
        if slides[0]["type"] != "Cover":
            errors.append(issue("E_FIRST_SLIDE_TYPE", "Deck_Mode=full 的第一页必须是 Cover。"))
        terminal_index = next((i for i in range(len(slides) - 1, -1, -1) if slides[i]["type"] in TERMINAL_TYPES), None)
        if terminal_index is None:
            errors.append(issue("E_TERMINAL_SLIDE", "Deck_Mode=full 至少需要一个 Closing 或 Decision。"))
        else:
            invalid_after = [
                {"page": index + 1, "type": slide["type"]}
                for index, slide in enumerate(slides[terminal_index + 1 :], terminal_index + 1)
                if slide["type"] not in POST_TERMINAL_TYPES
            ]
            if invalid_after:
                errors.append(issue("E_POST_TERMINAL_TYPE", "Closing 或 Decision 之后仅允许 Appendix/References。", slides=invalid_after))

    declared = metadata.get("Slide_Count", "")
    if declared and not _draft_placeholder(declared, metadata.get("Status") == "draft"):
        try:
            if int(declared) <= 0 or int(declared) != len(slides):
                raise ValueError
        except ValueError:
            errors.append(issue("E_SLIDE_COUNT", "Slide_Count 必须为正整数并与实际页数一致。", declared=declared, actual=len(slides)))

    placeholders = _placeholder_instances(payload)
    if placeholders:
        target = errors if metadata.get("Status") == "final" else warnings
        target.append(
            issue(
                "E_UNRESOLVED_PLACEHOLDER" if target is errors else "W_UNRESOLVED_PLACEHOLDER",
                "最终蓝图不得包含未结构化占位符。" if target is errors else "草稿仍包含占位符，发布前必须处理。",
                instances=placeholders,
            )
        )

    density = style.get("Density", "balanced")
    thresholds = {"minimal": (600, 5), "balanced": (900, 7), "dense": (1200, 10)}
    char_limit, bullet_limit = thresholds.get(density, thresholds["balanced"])
    for index, slide in enumerate(slides, 1):
        body = slide["content"].get("Body", "")
        bullet_count = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", body))
        if len(body) > char_limit or bullet_count > bullet_limit:
            warnings.append(issue("W_CONTENT_DENSITY", f"Slide {index} 的内容可能过密。", characters=len(body), bullets=bullet_count, density=density))
        notes = slide["delivery"].get("Speaker Notes", "")
        if len(notes) > 2000:
            warnings.append(issue("W_SPEAKER_NOTES_LENGTH", f"Slide {index} 的 Speaker Notes 可能过长。", characters=len(notes)))

    review = [issue("R_HUMAN_REVIEW", "结构校验不等于可发布；故事线、证据、视觉、隐私和承诺风险仍需人工复核。")]
    status = "fail" if errors else "warning" if warnings else "pass"
    report = {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": source_schema_version,
        "validation_scope": VALIDATION_SCOPE,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "review": review,
        "summary": {"slide_count": len(slides), "error_count": len(errors), "warning_count": len(warnings)},
    }
    document = {"schema_version": SCHEMA_VERSION, "source_schema_version": source_schema_version, "metadata": metadata, "style_instructions": style, "slides": slides}
    return report, document


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # pragma: no cover
        raise ValueError(message)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StructuredArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="outline.md, directory containing outline.md, or '-' for stdin")
    return parser.parse_args(argv)


def _source_report(path_text: str, stdin_cache: str | None) -> tuple[dict[str, Any], str | None]:
    try:
        if path_text == "-":
            if stdin_cache is None:
                stdin_cache = sys.stdin.read()
            content, source_files = stdin_cache, ["<stdin>"]
        else:
            content, source_files = load_source(Path(path_text))
        report, _ = audit_outline(content)
        report["source_files"] = source_files
        return report, stdin_cache
    except (OSError, UnicodeError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": "unknown",
            "validation_scope": VALIDATION_SCOPE,
            "status": "fail",
            "errors": [issue("E_FILE_READ", str(exc))],
            "warnings": [],
            "review": [],
            "summary": {"slide_count": 0, "error_count": 1, "warning_count": 0},
            "source_files": [] if path_text == "-" else [path_text],
        }, stdin_cache


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.paths.count("-") > 1:
            raise ValueError("stdin '-' may appear only once")
    except ValueError as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": "unknown",
            "validation_scope": VALIDATION_SCOPE,
            "status": "fail",
            "errors": [issue("E_ARGUMENT", str(exc))],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    results: list[dict[str, Any]] = []
    stdin_cache: str | None = None
    for path_text in args.paths:
        report, stdin_cache = _source_report(path_text, stdin_cache)
        results.append(report)

    if len(results) == 1:
        payload: dict[str, Any] = results[0]
    else:
        error_count = sum(result["summary"]["error_count"] for result in results)
        warning_count = sum(result["summary"]["warning_count"] for result in results)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source_schema_version": sorted({str(result["source_schema_version"]) for result in results}),
            "validation_scope": VALIDATION_SCOPE,
            "status": "fail" if error_count else "warning" if warning_count else "pass",
            "results": results,
            "summary": {"source_count": len(results), "error_count": error_count, "warning_count": warning_count},
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if any(result["errors"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
