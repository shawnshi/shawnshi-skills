from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references" / "briefing_schema.json"
TEMPLATE_PATH = ROOT / "references" / "briefing_template.md"
TEMPLATE_TOKEN_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
UNRESOLVED_SENTINELS = {"TBD", "TODO", "LLM_PENDING"}


def _known_template_tokens() -> set[str]:
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return set()
    return set(TEMPLATE_TOKEN_PATTERN.findall(template))


KNOWN_TEMPLATE_TOKENS = _known_template_tokens()


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [])


def _valid_date_or_unknown(value: Any) -> bool:
    if value == "unknown":
        return True
    try:
        date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _valid_datetime(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def _find_unresolved(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            findings.extend(_find_unresolved(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_find_unresolved(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized = value.strip()
        if (
            normalized.upper() in UNRESOLVED_SENTINELS
            or normalized.upper().startswith("PENDING_")
            or any(token in value for token in KNOWN_TEMPLATE_TOKENS)
        ):
            findings.append(path)
    return findings


def validate_briefing_data(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    schema = schema or json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings

    for field in schema["required_top_level"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if data.get("schema_version") != schema["version"]:
        errors.append(f"schema_version must equal {schema['version']}")
    if not _valid_datetime(data.get("generated_at")):
        errors.append("generated_at must be an ISO datetime")
    for field in ("topic", "region", "punchline", "insights", "digest", "market"):
        if not _non_empty(data.get(field)):
            errors.append(f"{field} cannot be empty")

    window = data.get("window")
    if not isinstance(window, dict):
        errors.append("window must be an object")
    else:
        for field in schema["required_window_fields"]:
            if not _non_empty(window.get(field)):
                errors.append(f"missing window.{field}")
        for field in ("start", "end"):
            if not _valid_date_or_unknown(window.get(field)):
                errors.append(f"window.{field} must be an ISO date or unknown")

    levers = data.get("action_levers")
    if not isinstance(levers, list):
        errors.append("action_levers must be a list")
        levers = []
    for index, lever in enumerate(levers):
        if not isinstance(lever, dict):
            errors.append(f"action_levers[{index}] must be an object")
            continue
        for field in schema["required_action_lever_fields"]:
            if not _non_empty(lever.get(field)):
                errors.append(f"missing action_levers[{index}].{field}")

    items = data.get("top_10")
    if not isinstance(items, list):
        errors.append("top_10 must be a list")
        items = []
    if len(items) > int(schema["max_top_items"]):
        errors.append(f"top_10 must contain at most {schema['max_top_items']} items")
    urls: list[str] = []
    has_l4 = False
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"top_10[{index}] must be an object")
            continue
        for field in schema["required_item_fields"]:
            if not _non_empty(item.get(field)):
                errors.append(f"missing top_10[{index}].{field}")
        if item.get("intelligence_level") not in schema["enums"]["intelligence_level"]:
            errors.append(f"invalid top_10[{index}].intelligence_level")
        if item.get("confidence") not in schema["enums"]["confidence"]:
            errors.append(f"invalid top_10[{index}].confidence")
        for field in ("event_date", "published_at"):
            if not _valid_date_or_unknown(item.get(field)):
                errors.append(f"top_10[{index}].{field} must be an ISO date or unknown")
        if not _valid_datetime(item.get("retrieved_at")):
            errors.append(f"top_10[{index}].retrieved_at must be an ISO datetime")
        url = str(item.get("url") or "")
        if not url.startswith(("https://", "http://")):
            errors.append(f"top_10[{index}].url must be an HTTP(S) URL")
        urls.append(url)
        has_l4 = has_l4 or item.get("intelligence_level") == "L4"

    if len(urls) != len(set(urls)):
        errors.append("top_10 contains duplicate urls")
    gaps = data.get("data_gaps")
    if not isinstance(gaps, list):
        errors.append("data_gaps must be a list")
    if has_l4:
        audit = data.get("adversarial_audit")
        if not isinstance(audit, dict):
            errors.append("L4 items require adversarial_audit")
        else:
            for field in schema["l4_required_audit_fields"]:
                if not _non_empty(audit.get(field)):
                    errors.append(f"missing adversarial_audit.{field}")

    unresolved = _find_unresolved(data)
    if unresolved:
        errors.append(
            "unresolved template value at: " + ", ".join(unresolved[:10])
        )
    if len(items) < 3:
        warnings.append("fewer than three verified signals; confirm that the scan scope was sufficient")
    if not levers:
        warnings.append("no action levers; acceptable when evidence does not justify an action")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only briefing schema validator.")
    parser.add_argument("json_path")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] could not read JSON: {exc}")
        return 2
    errors, warnings = validate_briefing_data(data)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        print("[FAIL] briefing schema validation failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("[PASS] briefing schema validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
