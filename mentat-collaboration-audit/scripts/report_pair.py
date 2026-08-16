#!/usr/bin/env python3
"""Render and validate a deterministic collaboration-audit report pair."""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HTML_TEMPLATE = SKILL_ROOT / "assets" / "template.html"
DEFAULT_MARKDOWN_TEMPLATE = SKILL_ROOT / "references" / "report-template.md"

RECOMMENDATION_ID_PATTERN = re.compile(r"^R-[0-9]{2,}$")
FINDING_ID_PATTERN = re.compile(r"^F-[0-9]{2,}$")
UNRESOLVED_PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")
NETWORK_RESOURCE_PATTERN = re.compile(
    r"(?is)(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//"
    r"|@import\s+(?:url\()?\s*['\"]?\s*(?:https?:)?//"
    r"|url\(\s*['\"]?\s*(?:https?:)?//"
)

STATUSES = {
    "not_started",
    "in_progress",
    "implemented",
    "validated",
    "blocked",
    "superseded",
    "rejected",
}
AUTHORIZATIONS = {"required", "approved", "denied", "not_required"}
VALIDATION_RESULTS = {"not_run", "pass", "fail", "blocked"}
TERMINAL_WITH_CLOSURE = {"superseded", "rejected"}

MARKDOWN_START = "<!-- REPORT_PAIR_RECOMMENDATIONS_START -->"
MARKDOWN_END = "<!-- REPORT_PAIR_RECOMMENDATIONS_END -->"
MARKDOWN_COLUMNS = (
    "id",
    "finding_ids",
    "action",
    "implementation_layer",
    "owner",
    "status",
    "authorization",
    "validation_criterion",
    "validation_result",
    "validation_evidence",
    "closure_reason",
    "closure_evidence",
)


class ReportPairError(ValueError):
    """Raised when a manifest or rendered report violates the pair contract."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _require_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportPairError(f"{path} must be a non-empty string")
    if "\n" in value or "\r" in value:
        raise ReportPairError(f"{path} must not contain line breaks")
    return value.strip()


def _optional_text(value: Any, path: str) -> str:
    if value is None or value == "":
        return ""
    return _require_text(value, path)


def _require_string_list(
    value: Any,
    path: str,
    *,
    allow_empty: bool,
    pattern: re.Pattern[str] | None = None,
) -> list[str]:
    if not isinstance(value, list):
        raise ReportPairError(f"{path} must be a list")
    if not allow_empty and not value:
        raise ReportPairError(f"{path} must not be empty")

    result: list[str] = []
    for index, item in enumerate(value):
        text = _require_text(item, f"{path}[{index}]")
        if pattern is not None and not pattern.fullmatch(text):
            raise ReportPairError(f"{path}[{index}] has invalid format: {text}")
        result.append(text)
    if len(result) != len(set(result)):
        raise ReportPairError(f"{path} must not contain duplicates")
    return result


def _normalize_recommendation(value: Any, index: int) -> dict[str, Any]:
    path = f"recommendations[{index}]"
    if not isinstance(value, Mapping):
        raise ReportPairError(f"{path} must be an object")

    recommendation_id = _require_text(value.get("id"), f"{path}.id")
    if not RECOMMENDATION_ID_PATTERN.fullmatch(recommendation_id):
        raise ReportPairError(f"{path}.id has invalid format: {recommendation_id}")

    finding_ids = _require_string_list(
        value.get("finding_ids"),
        f"{path}.finding_ids",
        allow_empty=False,
        pattern=FINDING_ID_PATTERN,
    )
    action = _require_text(value.get("action"), f"{path}.action")
    implementation_layer = _require_text(
        value.get("implementation_layer"), f"{path}.implementation_layer"
    )
    owner = _require_text(value.get("owner"), f"{path}.owner")

    status = _require_text(value.get("status"), f"{path}.status")
    if status not in STATUSES:
        raise ReportPairError(f"{path}.status is invalid: {status}")
    authorization = _require_text(
        value.get("authorization"), f"{path}.authorization"
    )
    if authorization not in AUTHORIZATIONS:
        raise ReportPairError(
            f"{path}.authorization is invalid: {authorization}"
        )

    validation = value.get("validation")
    if not isinstance(validation, Mapping):
        raise ReportPairError(f"{path}.validation must be an object")
    criterion = _require_text(
        validation.get("criterion"), f"{path}.validation.criterion"
    )
    result = _require_text(validation.get("result"), f"{path}.validation.result")
    if result not in VALIDATION_RESULTS:
        raise ReportPairError(f"{path}.validation.result is invalid: {result}")
    evidence = _require_string_list(
        validation.get("evidence"),
        f"{path}.validation.evidence",
        allow_empty=True,
    )
    if result in {"pass", "fail"} and not evidence:
        raise ReportPairError(
            f"{path}.validation.evidence is required when result is {result}"
        )
    if status == "validated" and result != "pass":
        raise ReportPairError(
            f"{path}.status validated requires validation.result pass"
        )

    closure_reason = _optional_text(
        value.get("closure_reason"), f"{path}.closure_reason"
    )
    closure_evidence = _require_string_list(
        value.get("closure_evidence", []),
        f"{path}.closure_evidence",
        allow_empty=True,
    )
    if status in TERMINAL_WITH_CLOSURE and (
        not closure_reason or not closure_evidence
    ):
        raise ReportPairError(
            f"{path} with status {status} requires closure_reason and closure_evidence"
        )

    return {
        "id": recommendation_id,
        "finding_ids": finding_ids,
        "action": action,
        "implementation_layer": implementation_layer,
        "owner": owner,
        "status": status,
        "authorization": authorization,
        "validation": {
            "criterion": criterion,
            "result": result,
            "evidence": evidence,
        },
        "closure_reason": closure_reason,
        "closure_evidence": closure_evidence,
    }


def normalize_manifest(value: Any) -> dict[str, Any]:
    """Validate and normalize one canonical report manifest."""
    if not isinstance(value, Mapping):
        raise ReportPairError("manifest must be an object")

    report_id = _require_text(value.get("report_id"), "report_id")
    previous_value = value.get("previous_report_id")
    previous_report_id = (
        None
        if previous_value is None
        else _require_text(previous_value, "previous_report_id")
    )
    if previous_report_id == report_id:
        raise ReportPairError("previous_report_id must differ from report_id")

    raw_recommendations = value.get("recommendations")
    if not isinstance(raw_recommendations, list) or not raw_recommendations:
        raise ReportPairError("recommendations must be a non-empty list")
    recommendations = [
        _normalize_recommendation(item, index)
        for index, item in enumerate(raw_recommendations)
    ]
    ids = [item["id"] for item in recommendations]
    if len(ids) != len(set(ids)):
        raise ReportPairError("recommendation IDs must be unique")

    title_value = value.get("title", "协作审计报告")
    title = _require_text(title_value, "title")
    return {
        "report_id": report_id,
        "previous_report_id": previous_report_id,
        "title": title,
        "recommendations": recommendations,
    }


def _semantic_fingerprint(recommendation: Mapping[str, Any]) -> str:
    semantic_payload = {
        "finding_ids": sorted(recommendation["finding_ids"]),
        "action": recommendation["action"],
        "implementation_layer": recommendation["implementation_layer"],
        "owner": recommendation["owner"],
    }
    encoded = json.dumps(
        semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def validate_manifest(
    manifest: Any,
    previous_manifest: Any | None = None,
) -> dict[str, Any]:
    """Validate a manifest and, when supplied, its prior-batch identity contract."""
    current = normalize_manifest(manifest)
    previous_id = current["previous_report_id"]

    if previous_manifest is None:
        if previous_id is not None:
            raise ReportPairError(
                "previous_manifest is required when previous_report_id is set"
            )
        return current

    previous = normalize_manifest(previous_manifest)
    if previous_id != previous["report_id"]:
        raise ReportPairError(
            "previous_report_id does not match previous manifest report_id"
        )

    current_by_id = {item["id"]: item for item in current["recommendations"]}
    missing_ids = [
        item["id"]
        for item in previous["recommendations"]
        if item["id"] not in current_by_id
    ]
    if missing_ids:
        raise ReportPairError(
            "previous recommendation IDs disappeared: " + ", ".join(missing_ids)
        )

    for old_item in previous["recommendations"]:
        recommendation_id = old_item["id"]
        new_item = current_by_id[recommendation_id]
        if _semantic_fingerprint(old_item) != _semantic_fingerprint(new_item):
            raise ReportPairError(
                f"semantic drift for stable recommendation ID {recommendation_id}"
            )
    return current


def _markdown_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("|", "&#124;")


def _json_list(value: Sequence[str]) -> str:
    return json.dumps(list(value), ensure_ascii=False, separators=(",", ":"))


def _recommendation_cells(recommendation: Mapping[str, Any]) -> list[str]:
    validation = recommendation["validation"]
    return [
        recommendation["id"],
        _json_list(recommendation["finding_ids"]),
        recommendation["action"],
        recommendation["implementation_layer"],
        recommendation["owner"],
        recommendation["status"],
        recommendation["authorization"],
        validation["criterion"],
        validation["result"],
        _json_list(validation["evidence"]),
        recommendation["closure_reason"],
        _json_list(recommendation["closure_evidence"]),
    ]


def _render_markdown_table(recommendations: Sequence[Mapping[str, Any]]) -> str:
    headers = (
        "编号",
        "发现编号",
        "动作",
        "实施层级",
        "所有者",
        "状态",
        "授权",
        "验证标准",
        "验证结果",
        "验证证据",
        "关闭原因",
        "关闭证据",
    )
    lines = [
        MARKDOWN_START,
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for recommendation in recommendations:
        cells = [_markdown_cell(value) for value in _recommendation_cells(recommendation)]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(MARKDOWN_END)
    return "\n".join(lines)


def _render_html_table(recommendations: Sequence[Mapping[str, Any]]) -> str:
    headers = (
        "编号",
        "发现编号",
        "动作",
        "实施层级",
        "所有者",
        "状态",
        "授权",
        "验证标准",
        "验证结果",
        "验证证据",
        "关闭原因",
        "关闭证据",
    )
    fields = MARKDOWN_COLUMNS
    lines = [
        '<table id="recommendations" data-report-pair-section="recommendations">',
        "  <thead><tr>"
        + "".join(f"<th>{html_lib.escape(header)}</th>" for header in headers)
        + "</tr></thead>",
        "  <tbody>",
    ]
    for recommendation in recommendations:
        validation = recommendation["validation"]
        attributes = (
            f'data-recommendation-id="{html_lib.escape(recommendation["id"], quote=True)}" '
            f'data-status="{html_lib.escape(recommendation["status"], quote=True)}" '
            f'data-validation-result="{html_lib.escape(validation["result"], quote=True)}"'
        )
        lines.append(f"    <tr {attributes}>")
        for field, value in zip(fields, _recommendation_cells(recommendation)):
            lines.append(
                f'      <td data-field="{field}">{html_lib.escape(value)}</td>'
            )
        lines.append("    </tr>")
    lines.extend(("  </tbody>", "</table>"))
    return "\n".join(lines)


def _replace_once(template: str, placeholder: str, value: str, name: str) -> str:
    if template.count(placeholder) != 1:
        raise ReportPairError(f"{name} must contain exactly one {placeholder}")
    return template.replace(placeholder, value)


def render_markdown(
    manifest: Any,
    *,
    template_text: str | None = None,
    previous_manifest: Any | None = None,
) -> str:
    """Render Markdown from the canonical manifest."""
    current = validate_manifest(manifest, previous_manifest)
    template = (
        DEFAULT_MARKDOWN_TEMPLATE.read_text(encoding="utf-8")
        if template_text is None
        else template_text
    )
    rendered = _replace_once(
        template,
        "{{RECOMMENDATIONS}}",
        _render_markdown_table(current["recommendations"]),
        "Markdown template",
    )
    replacements = {
        "{{REPORT_ID}}": current["report_id"],
        "{{PREVIOUS_REPORT_ID}}": current["previous_report_id"] or "—",
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, _markdown_cell(value))
    unresolved = UNRESOLVED_PLACEHOLDER_PATTERN.findall(rendered)
    if unresolved:
        raise ReportPairError(
            "Markdown contains unresolved placeholders: " + ", ".join(sorted(set(unresolved)))
        )
    return rendered.rstrip() + "\n"


def _assert_self_contained_template(template: str) -> None:
    if NETWORK_RESOURCE_PATTERN.search(template):
        raise ReportPairError("HTML template must not reference network resources")


def render_html(
    manifest: Any,
    *,
    template_text: str | None = None,
    previous_manifest: Any | None = None,
) -> str:
    """Render self-contained HTML from the canonical manifest."""
    current = validate_manifest(manifest, previous_manifest)
    template = (
        DEFAULT_HTML_TEMPLATE.read_text(encoding="utf-8")
        if template_text is None
        else template_text
    )
    _assert_self_contained_template(template)
    rendered = _replace_once(
        template,
        "{{RECOMMENDATIONS}}",
        _render_html_table(current["recommendations"]),
        "HTML template",
    )
    scope = f'Report ID: {current["report_id"]}'
    if current["previous_report_id"]:
        scope += f' · Previous report ID: {current["previous_report_id"]}'
    replacements = {
        "{{TITLE}}": html_lib.escape(current["title"]),
        "{{SCOPE_AND_COVERAGE}}": html_lib.escape(scope),
        "{{KEY_FINDINGS}}": "<p>—</p>",
        "{{FINDINGS_TABLE}}": "<p>—</p>",
        "{{METRICS}}": "<p>—</p>",
        "{{LIMITATIONS}}": "<p>—</p>",
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    unresolved = UNRESOLVED_PLACEHOLDER_PATTERN.findall(rendered)
    if unresolved:
        raise ReportPairError(
            "HTML contains unresolved placeholders: " + ", ".join(sorted(set(unresolved)))
        )
    _assert_self_contained_template(rendered)
    return rendered.rstrip() + "\n"


def _decode_json_list(value: str, path: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReportPairError(f"{path} is not a JSON list: {exc.msg}") from exc
    return _require_string_list(decoded, path, allow_empty=True)


def _parsed_recommendation(cells: Mapping[str, str], path: str) -> dict[str, Any]:
    missing = [field for field in MARKDOWN_COLUMNS if field not in cells]
    if missing:
        raise ReportPairError(f"{path} missing fields: {', '.join(missing)}")
    return {
        "id": cells["id"],
        "finding_ids": _decode_json_list(cells["finding_ids"], f"{path}.finding_ids"),
        "action": cells["action"],
        "implementation_layer": cells["implementation_layer"],
        "owner": cells["owner"],
        "status": cells["status"],
        "authorization": cells["authorization"],
        "validation": {
            "criterion": cells["validation_criterion"],
            "result": cells["validation_result"],
            "evidence": _decode_json_list(
                cells["validation_evidence"], f"{path}.validation_evidence"
            ),
        },
        "closure_reason": cells["closure_reason"],
        "closure_evidence": _decode_json_list(
            cells["closure_evidence"], f"{path}.closure_evidence"
        ),
    }


def parse_markdown_recommendations(markdown_text: str) -> list[dict[str, Any]]:
    """Extract the visible recommendation rows from rendered Markdown."""
    if markdown_text.count(MARKDOWN_START) != 1 or markdown_text.count(MARKDOWN_END) != 1:
        raise ReportPairError("Markdown recommendation section is missing or duplicated")
    start = markdown_text.index(MARKDOWN_START) + len(MARKDOWN_START)
    end = markdown_text.index(MARKDOWN_END, start)
    rows: list[dict[str, Any]] = []
    for line in markdown_text[start:end].splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        values = [
            html_lib.unescape(cell.strip())
            for cell in stripped[1:-1].split("|")
        ]
        if not values or values[0] in {"编号", "---"}:
            continue
        if all(set(value) <= {"-", ":"} for value in values):
            continue
        if len(values) != len(MARKDOWN_COLUMNS):
            raise ReportPairError(
                f"Markdown recommendation row has {len(values)} columns; expected {len(MARKDOWN_COLUMNS)}"
            )
        cells = dict(zip(MARKDOWN_COLUMNS, values))
        rows.append(_parsed_recommendation(cells, f"markdown[{len(rows)}]"))
    return rows


class _RecommendationHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_found = False
        self.in_table = False
        self.current_row: dict[str, Any] | None = None
        self.current_field: str | None = None
        self.current_text: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table" and attributes.get("id") == "recommendations":
            if self.section_found:
                raise ReportPairError("HTML recommendation section is duplicated")
            self.section_found = True
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag == "tr" and "data-recommendation-id" in attributes:
            if self.current_row is not None:
                raise ReportPairError("HTML recommendation rows are nested")
            self.current_row = {"attributes": attributes, "cells": {}}
            return
        if tag == "td" and self.current_row is not None:
            field = attributes.get("data-field")
            if not field:
                raise ReportPairError("HTML recommendation cell lacks data-field")
            self.current_field = field
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_field is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.current_row is not None and self.current_field is not None:
            self.current_row["cells"][self.current_field] = "".join(self.current_text).strip()
            self.current_field = None
            self.current_text = []
            return
        if tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
            return
        if tag == "table" and self.in_table:
            self.in_table = False


def parse_html_recommendations(html_text: str) -> list[dict[str, Any]]:
    """Extract and cross-check visible recommendation rows from rendered HTML."""
    parser = _RecommendationHTMLParser()
    try:
        parser.feed(html_text)
        parser.close()
    except ReportPairError:
        raise
    except Exception as exc:
        raise ReportPairError(f"HTML parse failed: {exc}") from exc
    if not parser.section_found:
        raise ReportPairError("HTML recommendation section is missing")

    recommendations: list[dict[str, Any]] = []
    for index, row in enumerate(parser.rows):
        recommendation = _parsed_recommendation(row["cells"], f"html[{index}]")
        attributes = row["attributes"]
        attribute_checks = {
            "data-recommendation-id": recommendation["id"],
            "data-status": recommendation["status"],
            "data-validation-result": recommendation["validation"]["result"],
        }
        for attribute, visible_value in attribute_checks.items():
            if attributes.get(attribute) != visible_value:
                raise ReportPairError(
                    f"html[{index}] {attribute} does not match visible value"
                )
        recommendations.append(recommendation)
    return recommendations


def _pair_projection(recommendation: Mapping[str, Any]) -> tuple[Any, ...]:
    validation = recommendation["validation"]
    return (
        recommendation["id"],
        recommendation["status"],
        validation["result"],
        _sha256_text(validation["criterion"]),
        tuple(sorted(validation["evidence"])),
    )


def _full_projection(recommendation: Mapping[str, Any]) -> tuple[Any, ...]:
    validation = recommendation["validation"]
    return (
        recommendation["id"],
        tuple(recommendation["finding_ids"]),
        recommendation["action"],
        recommendation["implementation_layer"],
        recommendation["owner"],
        recommendation["status"],
        recommendation["authorization"],
        validation["criterion"],
        validation["result"],
        tuple(sorted(validation["evidence"])),
        recommendation["closure_reason"],
        tuple(sorted(recommendation["closure_evidence"])),
    )


def validate_pair(
    manifest: Any,
    markdown_text: str,
    html_text: str,
    *,
    previous_manifest: Any | None = None,
) -> dict[str, Any]:
    """Validate manifest, Markdown, and HTML recommendation parity."""
    current = validate_manifest(manifest, previous_manifest)
    canonical = current["recommendations"]
    markdown_rows = parse_markdown_recommendations(markdown_text)
    html_rows = parse_html_recommendations(html_text)

    expected_ids = [item["id"] for item in canonical]
    markdown_ids = [item["id"] for item in markdown_rows]
    html_ids = [item["id"] for item in html_rows]
    if markdown_ids != expected_ids:
        raise ReportPairError(
            f"Markdown ID sequence mismatch: expected {expected_ids}, got {markdown_ids}"
        )
    if html_ids != expected_ids:
        raise ReportPairError(
            f"HTML ID sequence mismatch: expected {expected_ids}, got {html_ids}"
        )

    canonical_pair = [_pair_projection(item) for item in canonical]
    if [_pair_projection(item) for item in markdown_rows] != canonical_pair:
        raise ReportPairError("Markdown status or validation projection mismatch")
    if [_pair_projection(item) for item in html_rows] != canonical_pair:
        raise ReportPairError("HTML status or validation projection mismatch")

    canonical_full = [_full_projection(item) for item in canonical]
    if [_full_projection(item) for item in markdown_rows] != canonical_full:
        raise ReportPairError("Markdown visible recommendation content mismatch")
    if [_full_projection(item) for item in html_rows] != canonical_full:
        raise ReportPairError("HTML visible recommendation content mismatch")

    projection_bytes = json.dumps(
        canonical_pair, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "status": "pass",
        "report_id": current["report_id"],
        "recommendation_count": len(expected_ids),
        "recommendation_ids": expected_ids,
        "pair_projection_sha256": _sha256_bytes(projection_bytes),
    }


def render_report_pair(
    manifest: Any,
    *,
    previous_manifest: Any | None = None,
    markdown_template_text: str | None = None,
    html_template_text: str | None = None,
) -> dict[str, Any]:
    """Render both formats and validate them before returning either one."""
    markdown_text = render_markdown(
        manifest,
        template_text=markdown_template_text,
        previous_manifest=previous_manifest,
    )
    html_text = render_html(
        manifest,
        template_text=html_template_text,
        previous_manifest=previous_manifest,
    )
    validation = validate_pair(
        manifest,
        markdown_text,
        html_text,
        previous_manifest=previous_manifest,
    )
    return {"markdown": markdown_text, "html": html_text, "validation": validation}


def _load_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ReportPairError(f"{path} is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReportPairError(f"{path} is not valid JSON: {exc.msg}") from exc
    return value, raw


def _normalized_path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _write_exclusive_batch(files: Sequence[tuple[Path, bytes]]) -> None:
    keys = [_normalized_path_key(path) for path, _ in files]
    if len(keys) != len(set(keys)):
        raise ReportPairError("output paths must be distinct")
    for path, _ in files:
        if not path.parent.is_dir():
            raise ReportPairError(f"output parent does not exist: {path.parent}")
        if path.exists():
            raise ReportPairError(f"refusing to overwrite existing output: {path}")

    created: list[Path] = []
    try:
        for path, content in files:
            with path.open("xb") as handle:
                handle.write(content)
            created.append(path)
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise


def write_report_pair(
    *,
    manifest_path: Path,
    markdown_path: Path,
    html_path: Path,
    previous_manifest_path: Path | None = None,
    receipt_path: Path | None = None,
    markdown_template_path: Path = DEFAULT_MARKDOWN_TEMPLATE,
    html_template_path: Path = DEFAULT_HTML_TEMPLATE,
) -> dict[str, Any]:
    """Render, validate, and exclusively write a report pair and receipt."""
    manifest_path = Path(manifest_path)
    markdown_path = Path(markdown_path)
    html_path = Path(html_path)
    if markdown_path.parent.resolve() != html_path.parent.resolve():
        raise ReportPairError("Markdown and HTML must use the same output directory")
    if markdown_path.stem != html_path.stem:
        raise ReportPairError("Markdown and HTML must share one filename stem")

    manifest, manifest_bytes = _load_json(manifest_path)
    previous_manifest = None
    previous_bytes: bytes | None = None
    if previous_manifest_path is not None:
        previous_manifest, previous_bytes = _load_json(Path(previous_manifest_path))

    rendered = render_report_pair(
        manifest,
        previous_manifest=previous_manifest,
        markdown_template_text=Path(markdown_template_path).read_text(encoding="utf-8"),
        html_template_text=Path(html_template_path).read_text(encoding="utf-8"),
    )
    markdown_bytes = rendered["markdown"].encode("utf-8")
    html_bytes = rendered["html"].encode("utf-8")
    validation = rendered["validation"]

    receipt_target = (
        markdown_path.with_suffix(".receipt.json")
        if receipt_path is None
        else Path(receipt_path)
    )
    receipt_core = {
        "receipt_version": 1,
        "report_id": validation["report_id"],
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "previous_manifest_sha256": (
            _sha256_bytes(previous_bytes) if previous_bytes is not None else None
        ),
        "markdown_sha256": _sha256_bytes(markdown_bytes),
        "html_sha256": _sha256_bytes(html_bytes),
        "validator_sha256": _sha256_bytes(Path(__file__).read_bytes()),
        "recommendation_count": validation["recommendation_count"],
        "recommendation_ids": validation["recommendation_ids"],
        "pair_projection_sha256": validation["pair_projection_sha256"],
    }
    receipt_id = _sha256_bytes(
        json.dumps(
            receipt_core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    receipt = {"receipt_id": receipt_id, **receipt_core}
    receipt_bytes = (
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    _write_exclusive_batch(
        (
            (markdown_path, markdown_bytes),
            (html_path, html_bytes),
            (receipt_target, receipt_bytes),
        )
    )
    return {
        "status": "pass",
        "markdown": str(markdown_path),
        "html": str(html_path),
        "receipt": str(receipt_target),
        "receipt_id": receipt_id,
        "recommendation_ids": validation["recommendation_ids"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render and validate one canonical collaboration-audit report pair."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--markdown-template", type=Path, default=DEFAULT_MARKDOWN_TEMPLATE
    )
    parser.add_argument("--html-template", type=Path, default=DEFAULT_HTML_TEMPLATE)
    args = parser.parse_args()
    try:
        result = write_report_pair(
            manifest_path=args.manifest,
            markdown_path=args.markdown,
            html_path=args.html,
            previous_manifest_path=args.previous_manifest,
            receipt_path=args.receipt,
            markdown_template_path=args.markdown_template,
            html_template_path=args.html_template,
        )
    except (OSError, ReportPairError) as exc:
        print(f"REPORT_PAIR_FAIL: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
