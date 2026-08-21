"""Validate an offline primary-source Thesis red-team evidence package."""

import re
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

from portfolio_loader import normalize_symbol


SCHEMA_VERSION = "pia_thesis_red_team_v1"
COMPLETE_CONCLUSIONS = {"fatal_breach", "no_fatal_breach_verified"}
ALLOWED_CONCLUSIONS = COMPLETE_CONCLUSIONS | {"insufficient_evidence"}
ALLOWED_SOURCE_TIERS = {
    "issuer",
    "exchange",
    "regulator",
    "audited_filing",
    "official_product_data",
}
REQUIRED_SCOPES = ("macro", "sector", "regulatory")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_FUTURE_SKEW_SECONDS = 300
MAX_WINDOW_END_AGE_SECONDS = 3600


def _timestamp(value: Any, field: str, errors: List[str]) -> float | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field}_must_be_a_timezone_aware_timestamp")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field}_must_be_a_timezone_aware_timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{field}_must_be_a_timezone_aware_timestamp")
        return None
    return parsed.timestamp()


def _valid_public_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def evaluate_thesis_evidence(
    payload: Any,
    *,
    expected_symbols: List[str],
    portfolio_snapshot_binding: Dict[str, Any],
    evaluation_epoch: float,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    result: Dict[str, Any] = {
        "status": "incomplete",
        "evidence_status": "insufficient_evidence",
        "fatal_event_status": "not_assessed",
        "window_start": None,
        "window_end": None,
        "assessment_count": 0,
        "evidence_count": 0,
        "assessments": [],
        "errors": errors,
        "warnings": warnings,
    }
    if not isinstance(payload, dict):
        errors.append("thesis_evidence_root_must_be_an_object")
        return result
    allowed_root_keys = {
        "schema_version",
        "generated_at",
        "window_start",
        "window_end",
        "portfolio_snapshot_binding",
        "scope_coverage",
        "assessments",
        "evidence_items",
    }
    unexpected_root_keys = sorted(set(payload) - allowed_root_keys)
    if unexpected_root_keys:
        errors.append(
            f"unexpected_root_keys:{','.join(unexpected_root_keys)}"
        )
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version_must_equal_{SCHEMA_VERSION}")
    if payload.get("portfolio_snapshot_binding") != portfolio_snapshot_binding:
        errors.append("portfolio_snapshot_binding_mismatch")

    window_start = _timestamp(payload.get("window_start"), "window_start", errors)
    window_end = _timestamp(payload.get("window_end"), "window_end", errors)
    generated_at = _timestamp(payload.get("generated_at"), "generated_at", errors)
    result["window_start"] = payload.get("window_start")
    result["window_end"] = payload.get("window_end")
    if window_start is not None and window_end is not None and window_start >= window_end:
        errors.append("window_start_must_precede_window_end")
    if window_end is not None:
        if window_end > evaluation_epoch + MAX_FUTURE_SKEW_SECONDS:
            errors.append("window_end_is_in_the_future")
        if evaluation_epoch - window_end > MAX_WINDOW_END_AGE_SECONDS:
            errors.append("window_end_is_not_current")
    if generated_at is not None:
        if generated_at > evaluation_epoch + MAX_FUTURE_SKEW_SECONDS:
            errors.append("generated_at_is_in_the_future")
        if window_end is not None and generated_at < window_end:
            errors.append("generated_at_must_not_precede_window_end")

    evidence_items = payload.get("evidence_items")
    if not isinstance(evidence_items, list) or not evidence_items:
        errors.append("evidence_items_must_be_a_non_empty_list")
        evidence_items = []
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    for index, item in enumerate(evidence_items):
        prefix = f"evidence_items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}_must_be_an_object")
            continue
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            errors.append(f"{prefix}.evidence_id_required")
            continue
        if evidence_id in evidence_by_id:
            errors.append(f"duplicate_evidence_id:{evidence_id}")
            continue
        evidence_by_id[evidence_id] = item
        if item.get("source_tier") not in ALLOWED_SOURCE_TIERS:
            errors.append(f"{prefix}.source_tier_not_primary")
        if not _valid_public_url(item.get("source_locator")):
            errors.append(f"{prefix}.source_locator_must_be_public_http_url")
        if not SHA256_RE.fullmatch(str(item.get("content_sha256") or "")):
            errors.append(f"{prefix}.content_sha256_invalid")
        if not isinstance(item.get("claim"), str) or not item["claim"].strip():
            errors.append(f"{prefix}.claim_required")
        published_at = _timestamp(item.get("published_at"), f"{prefix}.published_at", errors)
        retrieved_at = _timestamp(item.get("retrieved_at"), f"{prefix}.retrieved_at", errors)
        if published_at is not None and retrieved_at is not None and published_at > retrieved_at:
            errors.append(f"{prefix}.published_at_after_retrieved_at")
        if retrieved_at is not None and retrieved_at > evaluation_epoch + MAX_FUTURE_SKEW_SECONDS:
            errors.append(f"{prefix}.retrieved_at_is_in_the_future")
        if retrieved_at is not None and window_end is not None and retrieved_at < window_end:
            errors.append(f"{prefix}.retrieved_at_precedes_window_end")
    result["evidence_count"] = len(evidence_by_id)

    def validate_evidence_ids(value: Any, field: str) -> List[str]:
        if not isinstance(value, list) or not value:
            errors.append(f"{field}_must_be_a_non_empty_list")
            return []
        ids = [item for item in value if isinstance(item, str) and item]
        if len(ids) != len(value) or len(ids) != len(set(ids)):
            errors.append(f"{field}_must_contain_unique_non_empty_strings")
        for evidence_id in ids:
            if evidence_id not in evidence_by_id:
                errors.append(f"{field}_unknown_evidence_id:{evidence_id}")
        return ids

    scope_coverage = payload.get("scope_coverage")
    scopes_complete = True
    if not isinstance(scope_coverage, dict):
        errors.append("scope_coverage_must_be_an_object")
        scopes_complete = False
        scope_coverage = {}
    for scope in REQUIRED_SCOPES:
        entry = scope_coverage.get(scope)
        if not isinstance(entry, dict):
            errors.append(f"scope_coverage.{scope}_must_be_an_object")
            scopes_complete = False
            continue
        if entry.get("status") != "complete":
            scopes_complete = False
        validate_evidence_ids(entry.get("evidence_ids"), f"scope_coverage.{scope}.evidence_ids")

    assessments = payload.get("assessments")
    if not isinstance(assessments, list):
        errors.append("assessments_must_be_a_list")
        assessments = []
    normalized_expected = [normalize_symbol(symbol) for symbol in expected_symbols]
    assessment_by_symbol: Dict[str, Dict[str, Any]] = {}
    assessments_complete = True
    for index, assessment in enumerate(assessments):
        prefix = f"assessments[{index}]"
        if not isinstance(assessment, dict):
            errors.append(f"{prefix}_must_be_an_object")
            assessments_complete = False
            continue
        symbol = normalize_symbol(assessment.get("symbol") or "")
        if not symbol:
            errors.append(f"{prefix}.symbol_required")
            assessments_complete = False
            continue
        if symbol in assessment_by_symbol:
            errors.append(f"duplicate_assessment_symbol:{symbol}")
            assessments_complete = False
            continue
        assessment_by_symbol[symbol] = assessment
        conclusion = assessment.get("conclusion")
        if conclusion not in ALLOWED_CONCLUSIONS:
            errors.append(f"{prefix}.conclusion_invalid")
            assessments_complete = False
        elif conclusion not in COMPLETE_CONCLUSIONS:
            assessments_complete = False
        if not isinstance(assessment.get("rationale"), str) or not assessment["rationale"].strip():
            errors.append(f"{prefix}.rationale_required")
        validate_evidence_ids(assessment.get("evidence_ids"), f"{prefix}.evidence_ids")

    returned = set(assessment_by_symbol)
    expected = set(normalized_expected)
    missing = sorted(expected - returned)
    extra = sorted(returned - expected)
    if missing:
        errors.append(f"missing_assessment_symbols:{','.join(missing)}")
        assessments_complete = False
    if extra:
        errors.append(f"unexpected_assessment_symbols:{','.join(extra)}")
        assessments_complete = False
    result["assessment_count"] = len(assessment_by_symbol)
    result["assessments"] = [assessment_by_symbol[symbol] for symbol in normalized_expected if symbol in assessment_by_symbol]

    if errors or not scopes_complete or not assessments_complete:
        if not errors:
            warnings.append("coverage_or_assessment_incomplete")
        return result

    fatal_symbols = [
        symbol
        for symbol in normalized_expected
        if assessment_by_symbol[symbol].get("conclusion") == "fatal_breach"
    ]
    result.update(
        {
            "status": "complete",
            "evidence_status": "ok",
            "fatal_event_status": (
                "fatal_breach_detected" if fatal_symbols else "no_fatal_breach_verified"
            ),
            "fatal_symbols": fatal_symbols,
        }
    )
    return result
