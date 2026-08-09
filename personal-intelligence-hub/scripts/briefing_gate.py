from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mix_policy import allocate_target_counts


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
    observed_domain_counts: dict[str, int] = {
        domain: 0 for domain in schema["domain_mix"]["domains"]
    }
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"top_10[{index}] must be an object")
            continue
        for field in schema["required_item_fields"]:
            if field not in item or (
                field != "secondary_domains" and not _non_empty(item.get(field))
            ):
                errors.append(f"missing top_10[{index}].{field}")
        if item.get("intelligence_level") not in schema["enums"]["intelligence_level"]:
            errors.append(f"invalid top_10[{index}].intelligence_level")
        if item.get("confidence") not in schema["enums"]["confidence"]:
            errors.append(f"invalid top_10[{index}].confidence")
        primary_domain = item.get("primary_domain")
        if primary_domain not in schema["enums"]["primary_domain"]:
            errors.append(f"invalid top_10[{index}].primary_domain")
        else:
            observed_domain_counts[primary_domain] += 1
        secondary_domains = item.get("secondary_domains")
        if not isinstance(secondary_domains, list):
            errors.append(f"top_10[{index}].secondary_domains must be a list")
        else:
            invalid_secondary = [
                domain
                for domain in secondary_domains
                if domain not in schema["enums"]["primary_domain"]
            ]
            if invalid_secondary:
                errors.append(f"invalid top_10[{index}].secondary_domains")
            if primary_domain in secondary_domains:
                errors.append(
                    f"top_10[{index}].secondary_domains cannot repeat primary_domain"
                )
        major_signal = item.get("major_signal")
        if not isinstance(major_signal, bool):
            errors.append(f"top_10[{index}].major_signal must be boolean")
        if major_signal is True and str(item.get("major_signal_reason") or "").strip().lower() in {
            "",
            "none",
        }:
            errors.append(f"top_10[{index}].major_signal_reason is required")
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

    mix = data.get("mix")
    mix_contract = schema["domain_mix"]
    domains = mix_contract["domains"]
    if not isinstance(mix, dict):
        errors.append("mix must be an object")
    else:
        for field in mix_contract["required_mix_fields"]:
            if field not in mix:
                errors.append(f"missing mix.{field}")

        ratios: dict[str, dict[str, float]] = {}
        for ratio_name in ("default_ratio", "effective_ratio"):
            ratio = mix.get(ratio_name)
            if not isinstance(ratio, dict):
                errors.append(f"mix.{ratio_name} must be an object")
                continue
            if any(
                not isinstance(ratio.get(domain), (int, float))
                for domain in domains
            ):
                errors.append(f"mix.{ratio_name} must contain numeric domain ratios")
                continue
            normalized = {domain: float(ratio[domain]) for domain in domains}
            if not math.isclose(sum(normalized.values()), 1.0, abs_tol=1e-9):
                errors.append(f"mix.{ratio_name} must sum to 1.0")
            ratios[ratio_name] = normalized

        expected_default = mix_contract["default_ratio"]
        if "default_ratio" in ratios and any(
            not math.isclose(
                ratios["default_ratio"][domain],
                float(expected_default[domain]),
                abs_tol=1e-9,
            )
            for domain in domains
        ):
            errors.append("mix.default_ratio must equal the schema default")
        if "default_ratio" in ratios and "effective_ratio" in ratios:
            if any(
                abs(
                    ratios["effective_ratio"][domain]
                    - ratios["default_ratio"][domain]
                )
                > float(mix_contract["max_ratio_shift"]) + 1e-9
                for domain in domains
            ):
                errors.append("mix.effective_ratio exceeds max_ratio_shift")

        count_maps: dict[str, dict[str, int]] = {}
        for count_name in ("target_counts", "actual_counts"):
            counts = mix.get(count_name)
            if not isinstance(counts, dict):
                errors.append(f"mix.{count_name} must be an object")
                continue
            if any(
                not isinstance(counts.get(domain), int) or counts[domain] < 0
                for domain in domains
            ):
                errors.append(f"mix.{count_name} must contain non-negative integers")
                continue
            count_maps[count_name] = {domain: counts[domain] for domain in domains}

        adjustment = mix.get("adjustment")
        if not isinstance(adjustment, dict):
            errors.append("mix.adjustment must be an object")
        else:
            for field in mix_contract["required_adjustment_fields"]:
                if field not in adjustment:
                    errors.append(f"missing mix.adjustment.{field}")
            applied = adjustment.get("applied")
            if not isinstance(applied, bool):
                errors.append("mix.adjustment.applied must be boolean")
            trigger_urls = adjustment.get("trigger_urls")
            if not isinstance(trigger_urls, list):
                errors.append("mix.adjustment.trigger_urls must be a list")
                trigger_urls = []
            if applied is True:
                if adjustment.get("favored_domain") not in domains:
                    errors.append("mix.adjustment.favored_domain must be a valid domain")
                if str(adjustment.get("reason") or "").strip().lower() in {"", "none"}:
                    errors.append("mix.adjustment.reason is required when applied")
                if not trigger_urls:
                    errors.append("mix.adjustment.trigger_urls is required when applied")
                elif any(url not in urls for url in trigger_urls):
                    errors.append("mix.adjustment.trigger_urls must reference retained items")
            elif "default_ratio" in ratios and "effective_ratio" in ratios and any(
                not math.isclose(
                    ratios["default_ratio"][domain],
                    ratios["effective_ratio"][domain],
                    abs_tol=1e-9,
                )
                for domain in domains
            ):
                errors.append("mix adjustment is required when effective_ratio changes")

        supply_exception = mix.get("supply_exception")
        if not isinstance(supply_exception, dict):
            errors.append("mix.supply_exception must be an object")
        else:
            for field in mix_contract["required_supply_exception_fields"]:
                if field not in supply_exception:
                    errors.append(f"missing mix.supply_exception.{field}")
            if not isinstance(supply_exception.get("applied"), bool):
                errors.append("mix.supply_exception.applied must be boolean")
            missing_domains = supply_exception.get("missing_domains")
            if not isinstance(missing_domains, list) or any(
                domain not in domains for domain in missing_domains
            ):
                errors.append("mix.supply_exception.missing_domains is invalid")

        if "actual_counts" in count_maps and count_maps["actual_counts"] != observed_domain_counts:
            errors.append("mix.actual_counts does not match retained items")
        if "target_counts" in count_maps:
            if sum(count_maps["target_counts"].values()) != len(items):
                errors.append("mix.target_counts must sum to retained item count")
            if "effective_ratio" in ratios:
                expected_targets = allocate_target_counts(
                    len(items), ratios["effective_ratio"]
                )
                if count_maps["target_counts"] != expected_targets:
                    errors.append("mix.target_counts does not match effective_ratio")
        if "target_counts" in count_maps and "actual_counts" in count_maps and isinstance(supply_exception, dict):
            expected_missing = [
                domain
                for domain in domains
                if count_maps["actual_counts"][domain]
                < count_maps["target_counts"][domain]
            ]
            deviation = count_maps["actual_counts"] != count_maps["target_counts"]
            if deviation and supply_exception.get("applied") is not True:
                errors.append("mix deviation requires supply_exception")
            if not deviation and supply_exception.get("applied") is True:
                errors.append("mix.supply_exception cannot be applied without deviation")
            if supply_exception.get("applied") is True:
                if str(supply_exception.get("reason") or "").strip().lower() in {"", "none"}:
                    errors.append("mix.supply_exception.reason is required when applied")
                if supply_exception.get("missing_domains") != expected_missing:
                    errors.append("mix.supply_exception.missing_domains does not match deviation")
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
