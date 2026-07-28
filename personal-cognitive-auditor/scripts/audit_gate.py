import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_PERIOD_TYPES = {"daily", "weekly", "monthly", "annual"}
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
) -> tuple[list[str], list[str]]:
    """Return deterministic errors and non-blocking editorial warnings."""
    errors: list[str] = []
    warnings: list[str] = []

    if not text.strip():
        return ["audit body is empty"], warnings

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
            "Validate personal-cognitive-auditor output. Only deterministic "
            "template-mode placeholder and handoff-schema failures block delivery."
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
    args = parser.parse_args()

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
