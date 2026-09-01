from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from history_manager import (
    generate_content_id,
    generate_event_id,
    normalize_text,
    normalize_url,
)
from mix_policy import allocate_target_counts
from run_contract import item_hash


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references" / "briefing_schema.json"
V13_SCHEMA_PATH = ROOT / "references" / "briefing_schema_v1.3.json"
V12_SCHEMA_PATH = ROOT / "references" / "briefing_schema_v1.2.json"
V11_SCHEMA_PATH = ROOT / "references" / "briefing_schema_v1.1.json"
V10_SCHEMA_PATH = ROOT / "references" / "briefing_schema_v1.0.json"
TEMPLATE_PATH = ROOT / "references" / "briefing_template.md"
TEMPLATE_TOKEN_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
UNRESOLVED_SENTINELS = {"TBD", "TODO", "LLM_PENDING"}
STRICT_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
V14_TERMINAL_DISPOSITIONS = {
    "invalid_or_unknown_date",
    "outside_window",
    "source_exclusion",
    "historical_duplicate",
    "below_heuristic_threshold",
    "candidate_capacity",
    "semantic_duplicate",
    "below_quality_gate",
    "semantic_capacity",
    "red_team_rejected",
    "retained",
}


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
    raw = str(value)
    if not STRICT_ISO_DATE_PATTERN.fullmatch(raw):
        return False
    try:
        date.fromisoformat(raw)
        return True
    except (TypeError, ValueError):
        return False


def _valid_datetime(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def _parsed_date(value: Any) -> date | None:
    if value in (None, "", "unknown"):
        return None
    raw = str(value)
    if not STRICT_ISO_DATE_PATTERN.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


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


def _validate_v11_data(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    schema = cast(
        dict[str, Any],
        schema or json.loads(V11_SCHEMA_PATH.read_text(encoding="utf-8")),
    )
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings

    for field in schema["required_top_level"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if data.get("schema_version") != schema["version"]:
        errors.append(f"schema_version must equal {schema['version']}")
    if str(data.get("model_used") or "").strip().lower() == "heuristic":
        errors.append("heuristic output cannot be archived as a formal briefing")
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
    window_start = _parsed_date(window.get("start")) if isinstance(window, dict) else None
    window_end = _parsed_date(window.get("end")) if isinstance(window, dict) else None
    if window_start and window_end and window_start > window_end:
        errors.append("window.start cannot be after window.end")

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
        if (
            not isinstance(primary_domain, str)
            or primary_domain not in schema["enums"]["primary_domain"]
        ):
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
        if major_signal is True:
            qualifies_as_l3 = (
                item.get("intelligence_level") == "L3"
                and item.get("confidence") == "high"
                and item.get("source_type") == "primary"
                and item.get("near_term_decision_impact") is True
            )
            qualifies_as_l4 = item.get("intelligence_level") == "L4"
            if not (qualifies_as_l3 or qualifies_as_l4):
                errors.append(f"top_10[{index}] fails major_signal eligibility")
        for field in ("event_date", "published_at"):
            if not _valid_date_or_unknown(item.get(field)):
                errors.append(f"top_10[{index}].{field} must be an ISO date or unknown")
            parsed_item_date = _parsed_date(item.get(field))
            if (
                parsed_item_date is not None
                and window_start is not None
                and window_end is not None
                and not (window_start <= parsed_item_date <= window_end)
            ):
                errors.append(f"top_10[{index}].{field} is outside window")
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


def _aware_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _validate_v10_data(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    schema = json.loads(V10_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings
    for field in schema["required_top_level"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must equal 1.0")
    if not _valid_datetime(data.get("generated_at")):
        errors.append("generated_at must be an ISO datetime")
    items = data.get("top_10")
    if not isinstance(items, list):
        errors.append("top_10 must be a list")
        items = []
    if len(items) > int(schema["max_top_items"]):
        errors.append("top_10 exceeds the legacy maximum")
    urls: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"top_10[{index}] must be an object")
            continue
        for field in schema["required_item_fields"]:
            if field not in item or not _non_empty(item.get(field)):
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
    if len(urls) != len(set(urls)):
        errors.append("top_10 contains duplicate urls")
    if not isinstance(data.get("data_gaps"), list):
        errors.append("data_gaps must be a list")
    unresolved = _find_unresolved(data)
    if unresolved:
        errors.append("unresolved template value at: " + ", ".join(unresolved[:10]))
    if len(items) < 3:
        warnings.append("legacy briefing contains fewer than three signals")
    return errors, warnings


def _ratio_map(
    value: Any,
    name: str,
    domains: list[str],
    errors: list[str],
) -> dict[str, float] | None:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return None
    if any(not isinstance(value.get(domain), (int, float)) for domain in domains):
        errors.append(f"{name} must contain numeric domain ratios")
        return None
    normalized = {domain: float(value[domain]) for domain in domains}
    if any(number < 0 for number in normalized.values()) or not math.isclose(
        sum(normalized.values()), 1.0, abs_tol=1e-9
    ):
        errors.append(f"{name} must contain non-negative ratios summing to 1.0")
    return normalized


def _validate_v12_data(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    schema = cast(
        dict[str, Any],
        schema or json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
    )
    is_v14 = str(schema.get("version") or "") == "1.4"

    def is_contract_integer(value: Any) -> bool:
        return type(value) is int if is_v14 else isinstance(value, int)

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"], warnings
    for field in schema["required_top_level"]:
        if field not in data:
            errors.append(f"missing required field: {field}")
    if data.get("schema_version") != schema["version"]:
        errors.append(f"schema_version must equal {schema['version']}")
    if not _non_empty(data.get("run_id")):
        errors.append("run_id cannot be empty")
    report_date = _parsed_date(data.get("report_date"))
    if report_date is None:
        errors.append("report_date must be an ISO date")
    generated_at = _aware_datetime(data.get("generated_at"))
    if generated_at is None:
        errors.append("generated_at must be a timezone-aware ISO datetime")
    if str(data.get("model_used") or "").strip().lower() in {"", "heuristic"}:
        errors.append("heuristic output cannot be archived as a formal briefing")
    for field in ("topic", "region", "punchline", "insights", "digest", "market"):
        if not _non_empty(data.get(field)):
            errors.append(f"{field} cannot be empty")

    window = data.get("window")
    window_start: date | None = None
    window_end: date | None = None
    if not isinstance(window, dict):
        errors.append("window must be an object")
    else:
        for field in schema["required_window_fields"]:
            if not _non_empty(window.get(field)):
                errors.append(f"missing window.{field}")
        if window.get("mode") != "calendar_days":
            errors.append("window.mode must equal calendar_days")
        days = window.get("days")
        days_value = cast(int, days) if is_contract_integer(days) else None
        if days_value is None or days_value <= 0:
            errors.append("window.days must be a positive integer")
        window_start = _parsed_date(window.get("start"))
        window_end = _parsed_date(window.get("end"))
        if window_start is None or window_end is None:
            errors.append("window start and end must be ISO dates")
        elif days_value is not None and window_start != window_end - timedelta(days=days_value - 1):
            errors.append("window does not contain the declared number of calendar days")
        if report_date is not None and window_end != report_date:
            errors.append("report_date must equal window.end")
        try:
            ZoneInfo(str(window.get("timezone")))
        except ZoneInfoNotFoundError:
            errors.append("window.timezone must be a valid IANA timezone")

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

    pipeline = data.get("pipeline")
    semantic_review: dict[str, Any] = {}
    red_team: dict[str, Any] = {}
    if not isinstance(pipeline, dict):
        errors.append("pipeline must be an object")
    else:
        baseline_sha = str(pipeline.get("baseline_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", baseline_sha):
            errors.append("pipeline.baseline_sha256 must be a SHA-256 hex digest")
        if pipeline.get("supplement_status") not in {"completed", "degraded", "no_increment"}:
            errors.append("pipeline.supplement_status is invalid")
        semantic_review = pipeline.get("semantic_review") or {}
        if not isinstance(semantic_review, dict):
            errors.append("pipeline.semantic_review must be an object")
            semantic_review = {}
        elif semantic_review.get("status") != "passed":
            errors.append("pipeline.semantic_review.status must be passed")
        if is_v14:
            for field in schema["pipeline_contract"]["required_semantic_fields"]:
                if field not in semantic_review:
                    errors.append(f"missing pipeline.semantic_review.{field}")
        if semantic_review.get("reviewer_kind") != "semantic_model":
            errors.append("pipeline.semantic_review.reviewer_kind must be semantic_model")
        for field in ("reviewer_id", "invocation_id"):
            if not _non_empty(semantic_review.get(field)):
                errors.append(f"pipeline.semantic_review.{field} is required")
        if not is_contract_integer(semantic_review.get("turns_used")) or semantic_review.get(
            "turns_used", 0
        ) < 1:
            errors.append("pipeline.semantic_review.turns_used must be positive")
        if semantic_review.get("halt_condition_met") is not True:
            errors.append("pipeline.semantic_review.halt_condition_met must be true")
        for field in (
            "request_sha256",
            "input_bundle_sha256",
            "access_log_sha256",
            "output_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(semantic_review.get(field) or "")):
                errors.append(f"pipeline.semantic_review.{field} must be a SHA-256 hex digest")
        if (
            not is_contract_integer(semantic_review.get("verified_access_count"))
            or semantic_review.get("verified_access_count", -1) < 0
        ):
            errors.append("pipeline.semantic_review.verified_access_count is invalid")
        red_team = pipeline.get("red_team") or {}
        if not isinstance(red_team, dict) or red_team.get("status") not in {"passed", "not_required"}:
            errors.append("pipeline.red_team status is invalid")
            red_team = {}
        else:
            if is_v14:
                for field in schema["pipeline_contract"]["required_red_team_fields"]:
                    if field not in red_team:
                        errors.append(f"missing pipeline.red_team.{field}")
            reviewer_kind = red_team.get("reviewer_kind")
            deterministic_no_l4 = (
                reviewer_kind == "deterministic_gate"
                and red_team.get("status") == "not_required"
            )
            if reviewer_kind not in {"logic_adversary", "deterministic_gate"}:
                errors.append(
                    "pipeline.red_team.reviewer_kind must be logic_adversary or deterministic_gate"
                )
            for field in ("reviewer_id", "invocation_id"):
                if not _non_empty(red_team.get(field)):
                    errors.append(f"pipeline.red_team.{field} is required")
            turns_used = red_team.get("turns_used")
            turns_value = (
                cast(int, turns_used) if is_contract_integer(turns_used) else None
            )
            if deterministic_no_l4:
                if turns_value != 0:
                    errors.append(
                        "pipeline.red_team.turns_used must be zero for deterministic_gate"
                    )
            elif turns_value is None or turns_value < 1:
                errors.append("pipeline.red_team.turns_used must be positive")
            if red_team.get("halt_condition_met") is not True:
                errors.append("pipeline.red_team.halt_condition_met must be true")
            if not re.fullmatch(r"[0-9a-f]{64}", str(red_team.get("request_sha256") or "")):
                errors.append("pipeline.red_team.request_sha256 must be a SHA-256 hex digest")

    items = data.get("top_10")
    if not isinstance(items, list):
        errors.append("top_10 must be a list")
        items = []
    if len(items) > int(schema["max_top_items"]):
        errors.append(f"top_10 must contain at most {schema['max_top_items']} items")
    urls: list[str] = []
    event_ids: list[str] = []
    semantic_identity_ids: list[str] = []
    dedupe_records: list[tuple[str, bool, str, str]] = []
    observed_domain_counts = {domain: 0 for domain in schema["domain_mix"]["domains"]}
    eligible_major_urls: set[str] = set()
    eligible_major_urls_by_domain: dict[str, set[str]] = {
        domain: set() for domain in schema["domain_mix"]["domains"]
    }
    l4_hashes: set[str] = set()
    final_item_hashes: list[str] = []
    covered_values = red_team.get("covered_item_hashes", [])
    if is_v14 and not isinstance(covered_values, list):
        errors.append("pipeline.red_team.covered_item_hashes must be a list")
        covered_values = []
    covered_hashes = {str(value) for value in covered_values}
    for index, item in enumerate(items):
        path = f"top_10[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        for field in schema["required_item_fields"]:
            if field not in item or (field != "secondary_domains" and not _non_empty(item.get(field))):
                errors.append(f"missing {path}.{field}")
        candidate_refs = item.get("candidate_refs")
        if (
            not isinstance(candidate_refs, list)
            or not candidate_refs
            or len(candidate_refs) != len(set(str(value) for value in candidate_refs))
            or any(
                re.fullmatch(r"cand-[0-9a-f]{64}", str(value)) is None
                for value in candidate_refs
            )
        ):
            errors.append(f"{path}.candidate_refs must contain unique candidate references")
        current_hash = item_hash(item)
        final_item_hashes.append(current_hash)
        event_id = str(item.get("event_id") or "")
        event_ids.append(event_id)
        identity = item.get("event_identity")
        has_complete_semantic_identity = False
        if not isinstance(identity, dict):
            errors.append(f"{path}.event_identity must be an object")
        elif item.get("identity_quality") == "semantic":
            try:
                expected_event_id = generate_event_id(identity)
                if event_id != expected_event_id:
                    errors.append(f"{path}.event_id does not match event_identity")
                else:
                    has_complete_semantic_identity = True
            except ValueError:
                errors.append(f"{path}.event_identity is incomplete")
        elif item.get("identity_quality") == "provisional":
            expected_event_id = generate_content_id(
                str(item.get("url") or ""),
                str(item.get("title") or ""),
                str(item.get("source") or ""),
            )
            if event_id != expected_event_id:
                errors.append(f"{path}.event_id does not match provisional content identity")
        if is_v14 and isinstance(identity, dict):
            try:
                semantic_identity_ids.append(generate_event_id(identity))
            except ValueError:
                pass
        if item.get("identity_quality") not in schema["enums"]["identity_quality"]:
            errors.append(f"invalid {path}.identity_quality")
        if item.get("intelligence_level") not in schema["enums"]["intelligence_level"]:
            errors.append(f"invalid {path}.intelligence_level")
        if item.get("confidence") not in schema["enums"]["confidence"]:
            errors.append(f"invalid {path}.confidence")
        primary_domain = item.get("primary_domain")
        if primary_domain not in schema["enums"]["primary_domain"]:
            errors.append(f"invalid {path}.primary_domain")
        else:
            observed_domain_counts[primary_domain] += 1
            if isinstance(identity, dict) and identity.get("primary_domain") != primary_domain:
                errors.append(f"{path}.event_identity primary_domain mismatch")
        secondary = item.get("secondary_domains")
        if not isinstance(secondary, list) or any(
            domain not in schema["enums"]["primary_domain"] for domain in secondary
        ):
            errors.append(f"invalid {path}.secondary_domains")
        elif primary_domain in secondary:
            errors.append(f"{path}.secondary_domains cannot repeat primary_domain")
        if item.get("source_type") not in schema["enums"]["source_type"]:
            errors.append(f"invalid {path}.source_type")
        if item.get("corroboration_status") not in schema["enums"]["corroboration_status"]:
            errors.append(f"invalid {path}.corroboration_status")
        if item.get("source_type") == "secondary" and item.get("corroboration_status") != "multi_independent":
            errors.append(f"{path} secondary source requires multi_independent corroboration")
        if (
            is_v14
            and item.get("corroboration_status") == "multi_independent"
            and isinstance(candidate_refs, list)
            and len(candidate_refs) < 2
        ):
            errors.append(f"{path} multi_independent corroboration requires at least two candidate_refs")

        access = item.get("access_check")
        if not isinstance(access, dict):
            errors.append(f"{path}.access_check must be an object")
        else:
            for field in schema["required_access_check_fields"]:
                if field not in access:
                    errors.append(f"missing {path}.access_check.{field}")
            if access.get("status") != "verified":
                errors.append(f"{path}.access_check must be verified")
            requested_url = str(access.get("requested_url") or "")
            if not requested_url.startswith(("http://", "https://")):
                errors.append(f"{path}.access_check.requested_url must be HTTP(S)")
            elif normalize_url(requested_url) != normalize_url(str(item.get("url") or "")):
                errors.append(f"{path}.access_check.requested_url must match item url")
            if not str(access.get("final_url") or "").startswith(("http://", "https://")):
                errors.append(f"{path}.access_check.final_url must be HTTP(S)")
            checked_at = _aware_datetime(access.get("checked_at"))
            if checked_at is None:
                errors.append(f"{path}.access_check.checked_at must be timezone-aware")
            elif generated_at is not None and checked_at > generated_at:
                errors.append(f"{path}.access_check.checked_at cannot follow generated_at")
            method = access.get("method")
            if method not in {"http_get", "browser", "api", "document"}:
                errors.append(f"{path}.access_check.method is invalid")
            status_code = access.get("http_status")
            status_value = (
                cast(int, status_code) if is_contract_integer(status_code) else None
            )
            if method in {"http_get", "api"} and (
                status_value is None or not 200 <= status_value < 400
            ):
                errors.append(f"{path}.access_check.http_status must show successful access")

        published = _parsed_date(item.get("published_at"))
        if published is None:
            errors.append(f"{path}.published_at must be a known ISO date")
        elif window_start is not None and window_end is not None and not (
            window_start <= published <= window_end
        ):
            errors.append(f"{path}.published_at is outside window")
        event_day = _parsed_date(item.get("event_date"))
        if item.get("event_date") != "unknown" and event_day is None:
            errors.append(f"{path}.event_date must be an ISO date or unknown")
        if event_day is not None and published is not None and event_day > published:
            errors.append(f"{path}.event_date cannot follow published_at")
        if isinstance(identity, dict) and identity.get("event_date") != item.get("event_date"):
            errors.append(f"{path}.event_identity event_date mismatch")
        observed_at = _aware_datetime(item.get("observed_at"))
        retrieved_at = _aware_datetime(item.get("retrieved_at"))
        if observed_at is None:
            errors.append(f"{path}.observed_at must be timezone-aware")
        if retrieved_at is None:
            errors.append(f"{path}.retrieved_at must be timezone-aware")
        if generated_at is not None:
            if observed_at is not None and observed_at > generated_at:
                errors.append(f"{path}.observed_at cannot follow generated_at")
            if retrieved_at is not None and retrieved_at > generated_at:
                errors.append(f"{path}.retrieved_at cannot follow generated_at")
        if published is not None and retrieved_at is not None and retrieved_at.date() < published:
            errors.append(f"{path}.retrieved_at cannot precede published_at")
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            errors.append(f"{path}.url must be an HTTP(S) URL")
        urls.append(url)
        dedupe_records.append(
            (
                event_id,
                has_complete_semantic_identity,
                normalize_url(url),
                normalize_text(str(item.get("title") or "")),
            )
        )
        major_signal = item.get("major_signal")
        if not isinstance(major_signal, bool):
            errors.append(f"{path}.major_signal must be boolean")
        major_reason = str(item.get("major_signal_reason") or "").strip().lower()
        qualifies_l3 = (
            item.get("intelligence_level") == "L3"
            and item.get("confidence") == "high"
            and item.get("source_type") == "primary"
            and isinstance(access, dict)
            and access.get("status") == "verified"
            and item.get("near_term_decision_impact") is True
        )
        qualifies_l4 = (
            item.get("intelligence_level") == "L4"
            and red_team.get("status") == "passed"
            and current_hash in covered_hashes
        )
        if major_signal is True:
            if major_reason in {"", "none"}:
                errors.append(f"{path}.major_signal_reason is required")
            if not (qualifies_l3 or qualifies_l4):
                errors.append(f"{path} fails major_signal eligibility")
            else:
                eligible_major_urls.add(url)
                if primary_domain in eligible_major_urls_by_domain:
                    eligible_major_urls_by_domain[primary_domain].add(url)
        if item.get("near_term_decision_impact") is True and str(
            item.get("decision_impact_reason") or ""
        ).strip().lower() in {"", "none"}:
            errors.append(f"{path}.decision_impact_reason is required")
        if is_v14 and type(item.get("near_term_decision_impact")) is not bool:
            errors.append(f"{path}.near_term_decision_impact must be boolean")
        if item.get("intelligence_level") == "L4":
            l4_hashes.add(current_hash)

    if not is_v14 and len(urls) != len(set(urls)):
        errors.append("top_10 contains duplicate urls")
    if len(event_ids) != len(set(event_ids)):
        errors.append("top_10 contains duplicate event_ids")
    if is_v14 and len(semantic_identity_ids) != len(set(semantic_identity_ids)):
        errors.append("top_10 contains duplicate semantic event identities")
    if is_v14:
        duplicate_url = False
        duplicate_title = False
        for left_index, left in enumerate(dedupe_records):
            for right in dedupe_records[left_index + 1 :]:
                left_id, left_complete, left_url, left_title = left
                right_id, right_complete, right_url, right_title = right
                if left_id and left_id == right_id:
                    continue
                if left_complete and right_complete and left_id != right_id:
                    continue
                if left_url == right_url:
                    duplicate_url = True
                if left_title and left_title == right_title:
                    duplicate_title = True
        if duplicate_url:
            errors.append("top_10 contains duplicate urls")
        if duplicate_title:
            errors.append("top_10 contains duplicate normalized titles")
    reviewed_hashes = sorted(str(value) for value in semantic_review.get("reviewed_item_hashes", []))
    if reviewed_hashes != sorted(final_item_hashes):
        errors.append("pipeline.semantic_review.reviewed_item_hashes do not match final items")
    if (
        is_contract_integer(semantic_review.get("verified_access_count"))
        and semantic_review.get("verified_access_count", 0) != len(items)
    ):
        errors.append(
            "pipeline.semantic_review.verified_access_count must equal distinct retained-item access mappings"
        )
    lineage_bindings = semantic_review.get("lineage_bindings")
    if not isinstance(lineage_bindings, list):
        errors.append("pipeline.semantic_review.lineage_bindings must be a list")
    else:
        lineage_outputs: list[str] = []
        for index, binding in enumerate(lineage_bindings):
            if not isinstance(binding, dict):
                errors.append(f"pipeline.semantic_review.lineage_bindings[{index}] must be an object")
                continue
            output_hash = str(binding.get("output_item_sha256") or "")
            lineage_outputs.append(output_hash)
            inputs = binding.get("inputs")
            if not isinstance(inputs, list) or not inputs:
                errors.append(
                    f"pipeline.semantic_review.lineage_bindings[{index}].inputs is required"
                )
                continue
            for input_index, value in enumerate(inputs):
                if (
                    not isinstance(value, dict)
                    or re.fullmatch(r"cand-[0-9a-f]{64}", str(value.get("candidate_ref") or "")) is None
                    or re.fullmatch(r"[0-9a-f]{64}", str(value.get("candidate_object_sha256") or "")) is None
                ):
                    errors.append(
                        "pipeline.semantic_review.lineage_bindings"
                        f"[{index}].inputs[{input_index}] is invalid"
                    )
        if sorted(lineage_outputs) != sorted(final_item_hashes):
            errors.append("pipeline.semantic_review.lineage outputs do not match final items")
    if l4_hashes and not l4_hashes.issubset(covered_hashes):
        errors.append("L4 items require matching red-team item hashes")
    if is_v14:
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in covered_hashes):
            errors.append("pipeline.red_team.covered_item_hashes contains an invalid hash")
        if not covered_hashes.issubset(set(final_item_hashes)):
            errors.append("pipeline.red_team.covered_item_hashes contains an unknown item hash")
        if l4_hashes and red_team.get("status") != "passed":
            errors.append("L4 items require red-team status passed")
        if not l4_hashes and red_team.get("status") == "passed" and not covered_hashes:
            errors.append("targeted red-team review must record covered item hashes")
        if red_team.get("status") == "not_required" and covered_hashes:
            errors.append("not-required red-team cannot claim covered item hashes")
    elif not l4_hashes and red_team.get("status") == "passed" and not covered_hashes:
        warnings.append("red-team status is passed but no item hashes are recorded")

    mix = data.get("mix")
    domains = schema["domain_mix"]["domains"]
    if not isinstance(mix, dict):
        errors.append("mix must be an object")
    else:
        for field in schema["domain_mix"]["required_mix_fields"]:
            if field not in mix:
                errors.append(f"missing mix.{field}")
        default_ratio = _ratio_map(mix.get("default_ratio"), "mix.default_ratio", domains, errors)
        requested_ratio = _ratio_map(mix.get("requested_ratio"), "mix.requested_ratio", domains, errors)
        effective_ratio = _ratio_map(mix.get("effective_ratio"), "mix.effective_ratio", domains, errors)
        expected_default = schema["domain_mix"]["default_ratio"]
        if default_ratio and any(
            not math.isclose(default_ratio[domain], float(expected_default[domain]), abs_tol=1e-9)
            for domain in domains
        ):
            errors.append("mix.default_ratio must equal the schema default")
        ratio_source = mix.get("ratio_source")
        if ratio_source not in {"schema_default", "focus_config", "user"}:
            errors.append("mix.ratio_source is invalid")
        if ratio_source != "schema_default" and str(mix.get("ratio_reason") or "").strip().lower() in {"", "none"}:
            errors.append("mix.ratio_reason is required for a non-default request")
        if requested_ratio and effective_ratio and any(
            abs(effective_ratio[domain] - requested_ratio[domain])
            > float(schema["domain_mix"]["max_ratio_shift"]) + 1e-9
            for domain in domains
        ):
            errors.append("mix.effective_ratio exceeds max shift from requested_ratio")

        count_maps: dict[str, dict[str, int]] = {}
        for name in ("target_counts", "actual_counts"):
            value = mix.get(name)
            if not isinstance(value, dict) or any(
                not is_contract_integer(value.get(domain)) or value[domain] < 0
                for domain in domains
            ):
                errors.append(f"mix.{name} must contain non-negative integers")
            else:
                count_maps[name] = {domain: value[domain] for domain in domains}
        if count_maps.get("actual_counts") != observed_domain_counts:
            errors.append("mix.actual_counts does not match retained items")
        if "target_counts" in count_maps and sum(count_maps["target_counts"].values()) != len(items):
            errors.append("mix.target_counts must sum to retained item count")
        if effective_ratio and "target_counts" in count_maps and count_maps["target_counts"] != allocate_target_counts(len(items), effective_ratio):
            errors.append("mix.target_counts does not match effective_ratio")

        adjustment = mix.get("adjustment")
        if not isinstance(adjustment, dict):
            errors.append("mix.adjustment must be an object")
            adjustment = {}
        else:
            for field in schema["domain_mix"]["required_adjustment_fields"]:
                if field not in adjustment:
                    errors.append(f"missing mix.adjustment.{field}")
        applied = adjustment.get("applied")
        if not isinstance(applied, bool):
            errors.append("mix.adjustment.applied must be boolean")
        expected_effective = dict(requested_ratio or {})
        favored = [domain for domain in domains if eligible_major_urls_by_domain[domain]]
        expected_applied = False
        expected_favored = "none"
        expected_triggers: list[str] = []
        expected_reason = "none"
        if requested_ratio and len(favored) == 1:
            expected_favored = favored[0]
            other_domain = next(domain for domain in domains if domain != expected_favored)
            shift = min(
                float(schema["domain_mix"]["max_ratio_shift"]),
                requested_ratio[other_domain],
            )
            if shift > 0:
                expected_applied = True
                expected_effective[expected_favored] += shift
                expected_effective[other_domain] -= shift
                expected_triggers = sorted(eligible_major_urls_by_domain[expected_favored])
                expected_reason = "；".join(
                    sorted(
                        {
                            str(item.get("major_signal_reason") or "已通过高影响资讯门槛")
                            for item in items
                            if item.get("url") in expected_triggers
                        }
                    )
                )
            else:
                expected_favored = "none"
                expected_reason = "requested ratio has no remaining adjustment headroom"
        elif len(favored) > 1:
            expected_reason = "两个领域均有高影响资讯，维持请求比例"
        if requested_ratio and effective_ratio and any(
            not math.isclose(effective_ratio[domain], expected_effective[domain], abs_tol=1e-9)
            for domain in domains
        ):
            errors.append("mix.effective_ratio does not match recomputed major-signal policy")
        if applied is not expected_applied:
            errors.append("mix.adjustment.applied does not match recomputed policy")
        actual_triggers = adjustment.get("trigger_urls")
        if not isinstance(actual_triggers, list):
            errors.append("mix.adjustment.trigger_urls must be a list")
            actual_triggers = []
        if sorted(str(url) for url in actual_triggers) != expected_triggers:
            errors.append("mix.adjustment.trigger_urls do not match recomputed policy")
        if adjustment.get("favored_domain") != expected_favored:
            errors.append("mix.adjustment.favored_domain does not match recomputed policy")
        if str(adjustment.get("reason") or "") != expected_reason:
            errors.append("mix.adjustment.reason does not match recomputed policy")

        supply = mix.get("supply_exception")
        if not isinstance(supply, dict):
            errors.append("mix.supply_exception must be an object")
            supply = {}
        else:
            for field in schema["domain_mix"]["required_supply_exception_fields"]:
                if field not in supply:
                    errors.append(f"missing mix.supply_exception.{field}")
        if not isinstance(supply.get("applied"), bool):
            errors.append("mix.supply_exception.applied must be boolean")
        missing_domains = supply.get("missing_domains")
        if not isinstance(missing_domains, list) or any(domain not in domains for domain in missing_domains):
            errors.append("mix.supply_exception.missing_domains is invalid")
            missing_domains = []
        if "target_counts" in count_maps and "actual_counts" in count_maps:
            expected_missing = [
                domain
                for domain in domains
                if count_maps["actual_counts"][domain] < count_maps["target_counts"][domain]
            ]
            expected_supply = {
                "applied": bool(expected_missing),
                "reason": (
                    "合格候选不足：" + "、".join(expected_missing)
                    if expected_missing
                    else "none"
                ),
                "missing_domains": expected_missing,
            }
            if any(supply.get(field) != value for field, value in expected_supply.items()):
                errors.append("mix.supply_exception does not match recomputed target shortfall")
            deviation = count_maps["actual_counts"] != count_maps["target_counts"]
            if deviation and supply.get("applied") is not True:
                errors.append("mix deviation requires supply_exception")
            if not deviation and supply.get("applied") is True:
                errors.append("mix.supply_exception cannot be applied without deviation")
            if supply.get("applied") is True:
                if missing_domains != expected_missing:
                    errors.append("mix.supply_exception.missing_domains does not match deviation")
                if str(supply.get("reason") or "").strip().lower() in {"", "none"}:
                    errors.append("mix.supply_exception.reason is required when applied")

    coverage = data.get("coverage")
    if not isinstance(coverage, dict):
        errors.append("coverage must be an object")
    else:
        if coverage.get("run_status") not in schema["enums"]["run_status"]:
            errors.append("coverage.run_status is invalid")
        if coverage.get("coverage_confidence") not in schema["enums"]["coverage_confidence"]:
            errors.append("coverage.coverage_confidence is invalid")
        run_status = coverage.get("run_status")
        expected_coverage_confidence = (
            {
                "complete": "high",
                "degraded": "medium",
                "failed": "low",
            }.get(run_status)
            if isinstance(run_status, str)
            else None
        )
        if (
            expected_coverage_confidence is not None
            and coverage.get("coverage_confidence") != expected_coverage_confidence
        ):
            errors.append("coverage.coverage_confidence does not match run_status")
        attempted = coverage.get("source_attempted")
        succeeded = coverage.get("source_succeeded")
        failed = coverage.get("source_failed")
        if any(
            not is_contract_integer(value) or cast(int, value) < 0
            for value in (attempted, succeeded, failed)
        ):
            errors.append("coverage source counts must be non-negative integers")
        else:
            attempted_value = cast(int, attempted)
            succeeded_value = cast(int, succeeded)
            failed_value = cast(int, failed)
            if attempted_value != succeeded_value + failed_value:
                errors.append("coverage source counts do not reconcile")
            else:
                expected_rate = (
                    succeeded_value / attempted_value if attempted_value else 0.0
                )
                if not isinstance(
                    coverage.get("source_success_rate"), (int, float)
                ) or not math.isclose(
                    float(coverage.get("source_success_rate", -1)),
                    expected_rate,
                    abs_tol=1e-6,
                ):
                    errors.append("coverage.source_success_rate does not match counts")
        dated_rate = coverage.get("dated_candidate_rate")
        if not isinstance(dated_rate, (int, float)) or not 0 <= float(dated_rate) <= 1:
            errors.append("coverage.dated_candidate_rate must be between 0 and 1")
        lane_failures = coverage.get("required_lane_failures")
        if not isinstance(lane_failures, list):
            errors.append("coverage.required_lane_failures must be a list")
            lane_failures = []
        if coverage.get("run_status") == "complete" and (
            coverage.get("baseline_status") in {"degraded", "failed"} or lane_failures
        ):
            errors.append("coverage.run_status must be degraded when required coverage failed")
        if attempted == 0 and coverage.get("run_status") == "complete":
            errors.append("coverage.run_status cannot be complete without attempted sources")
        if coverage.get("run_status") == "failed" and items:
            errors.append("failed coverage cannot retain formal top items")

    funnel = data.get("candidate_funnel")
    if not isinstance(funnel, dict):
        errors.append("candidate_funnel must be an object")
    else:
        observed = funnel.get("observed")
        dispositions = funnel.get("terminal_dispositions")
        if not is_contract_integer(observed) or cast(int, observed) < 0:
            errors.append("candidate_funnel.observed must be a non-negative integer")
        if not isinstance(dispositions, dict) or any(
            not is_contract_integer(value) or cast(int, value) < 0
            for value in dispositions.values()
        ):
            errors.append("candidate_funnel.terminal_dispositions must contain non-negative integers")
        elif is_contract_integer(observed):
            if is_v14:
                unknown = sorted(set(dispositions) - V14_TERMINAL_DISPOSITIONS)
                if unknown:
                    errors.append(
                        "candidate_funnel contains unknown terminal dispositions: "
                        + ", ".join(unknown)
                    )
            if sum(dispositions.values()) != cast(int, observed):
                errors.append("candidate_funnel terminal dispositions do not conserve observed items")
            if dispositions.get("retained") != len(items):
                errors.append("candidate_funnel retained count does not match top_10")

    gaps = data.get("data_gaps")
    if not isinstance(gaps, list):
        errors.append("data_gaps must be a list")
    else:
        for index, gap in enumerate(gaps):
            if not isinstance(gap, dict):
                errors.append(f"data_gaps[{index}] must be an object")
                continue
            for field in schema["required_gap_fields"]:
                if not _non_empty(gap.get(field)):
                    errors.append(f"missing data_gaps[{index}].{field}")

    unresolved = _find_unresolved(data)
    if unresolved:
        errors.append("unresolved template value at: " + ", ".join(unresolved[:10]))
    if len(items) < 3:
        warnings.append("fewer than three verified signals; confirm that the scan scope was sufficient")
    source_counts: dict[str, int] = {}
    for item in items:
        source = str(item.get("source") or "")
        source_counts[source] = source_counts.get(source, 0) + 1
    if items and max(source_counts.values(), default=0) / len(items) > 0.5:
        warnings.append("one source supplies more than half of retained items")
    if not levers:
        warnings.append("no action levers; acceptable when evidence does not justify an action")
    return errors, warnings


def validate_briefing_data(
    data: dict[str, Any], schema: dict[str, Any] | None = None
) -> tuple[list[str], list[str]]:
    if not isinstance(data, dict):
        return ["root must be a JSON object"], []
    version = str((schema or {}).get("version") or data.get("schema_version") or "")
    if version == "1.0":
        return _validate_v10_data(data)
    if version == "1.1":
        selected_schema = schema or json.loads(V11_SCHEMA_PATH.read_text(encoding="utf-8"))
        return _validate_v11_data(data, selected_schema)
    if version == "1.2":
        selected_schema = schema or json.loads(V12_SCHEMA_PATH.read_text(encoding="utf-8"))
        return _validate_v12_data(data, selected_schema)
    if version == "1.3":
        selected_schema = schema or json.loads(V13_SCHEMA_PATH.read_text(encoding="utf-8"))
        return _validate_v12_data(data, selected_schema)
    if version == "1.4":
        selected_schema = schema or json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        return _validate_v12_data(data, selected_schema)
    return [f"unsupported schema_version: {version or 'missing'}"], []


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
