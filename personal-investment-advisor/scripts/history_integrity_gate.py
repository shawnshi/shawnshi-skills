from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware_iso_datetime(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _iso_date(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def _strict_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _normalize_event(
    event: Any,
    prefix: str,
    errors: list[str],
    as_of_date: date | None,
) -> tuple[str, str, str] | None:
    if not isinstance(event, dict):
        errors.append(f"{prefix} must be an object")
        return None
    event_type = event.get("event_type")
    effective_date = event.get("effective_date")
    factor = event.get("factor")
    if not _non_empty_string(event_type):
        errors.append(f"{prefix}.event_type must be a non-empty string")
    if not _iso_date(effective_date):
        errors.append(f"{prefix}.effective_date must be an ISO date")
    elif as_of_date is not None and date.fromisoformat(effective_date.strip()) > as_of_date:
        errors.append(f"{prefix}.effective_date cannot be after as_of_date")
    if not _non_empty_string(factor):
        errors.append(f"{prefix}.factor must be a non-empty string")
    if errors and any(item.startswith(prefix) for item in errors):
        return None
    return (
        event_type.strip().lower(),
        effective_date.strip(),
        "".join(factor.upper().split()),
    )


def evaluate_history_integrity(payload: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {
            "status": "insufficient_data",
            "detail_status": "invalid_payload",
            "packet_verified": False,
            "technical_metrics_allowed": False,
            "symbol": None,
            "errors": ["history integrity payload must be an object"],
            "event_mismatches": {},
        }

    symbol = payload.get("symbol")
    if not _non_empty_string(symbol):
        errors.append("symbol must be a non-empty string")
        normalized_symbol = None
    else:
        normalized_symbol = symbol.strip().upper()
    if str(payload.get("asset_type") or "").strip().lower() != "etf":
        errors.append("asset_type must be etf")
    if not _iso_date(payload.get("as_of_date")):
        errors.append("as_of_date must be an ISO date")
        parsed_as_of_date = None
    else:
        parsed_as_of_date = date.fromisoformat(payload["as_of_date"].strip())
    for field in ("provider_source", "provider_source_locator", "provider_adjustment"):
        if not _non_empty_string(payload.get(field)):
            errors.append(f"{field} must be a non-empty string")

    coverage = payload.get("official_coverage")
    result_count = None
    control_count = None
    if not isinstance(coverage, dict):
        errors.append("official_coverage must be an object")
    else:
        locator = coverage.get("source_locator")
        if not _non_empty_string(locator):
            errors.append("official_coverage.source_locator must be a non-empty string")
        elif any(
            token in locator.lower()
            for token in ("example.com", "example.test", ".invalid", "localhost")
        ):
            errors.append("official_coverage.source_locator is a reserved test locator")
        if not _aware_iso_datetime(coverage.get("retrieved_at")):
            errors.append("official_coverage.retrieved_at must be a timezone-aware ISO datetime")
        elif (
            parsed_as_of_date is not None
            and datetime.fromisoformat(
                coverage["retrieved_at"].strip().replace("Z", "+00:00")
            ).date()
            < parsed_as_of_date
        ):
            errors.append("official_coverage.retrieved_at cannot be before as_of_date")
        if coverage.get("coverage_status") != "complete":
            errors.append("official_coverage.coverage_status must be complete")
        result_count = coverage.get("result_count")
        control_count = coverage.get("control_query_count")
        if not _strict_nonnegative_int(result_count):
            errors.append("official_coverage.result_count must be a non-negative integer")
        if not _strict_nonnegative_int(control_count):
            errors.append("official_coverage.control_query_count must be a non-negative integer")

    official_events = payload.get("official_events")
    provider_events = payload.get("provider_events")
    if not isinstance(official_events, list):
        errors.append("official_events must be a list")
        official_events = []
    if not isinstance(provider_events, list):
        errors.append("provider_events must be a list")
        provider_events = []
    if _strict_nonnegative_int(result_count) and result_count != len(official_events):
        errors.append("official_coverage.result_count must equal len(official_events)")
    if result_count == 0 and control_count == 0:
        errors.append("zero_result_control_missing")

    normalized_official = {
        normalized
        for index, item in enumerate(official_events)
        if (
            normalized := _normalize_event(
                item,
                f"official_events[{index}]",
                errors,
                parsed_as_of_date,
            )
        )
        is not None
    }
    normalized_provider = {
        normalized
        for index, item in enumerate(provider_events)
        if (
            normalized := _normalize_event(
                item,
                f"provider_events[{index}]",
                errors,
                parsed_as_of_date,
            )
        )
        is not None
    }

    if errors:
        return {
            "status": "insufficient_data",
            "detail_status": "coverage_incomplete",
            "packet_verified": False,
            "technical_metrics_allowed": False,
            "symbol": normalized_symbol,
            "errors": list(dict.fromkeys(errors)),
            "event_mismatches": {},
        }

    missing_from_provider = sorted(normalized_official - normalized_provider)
    extra_in_provider = sorted(normalized_provider - normalized_official)
    mismatches = {
        "missing_from_provider": missing_from_provider,
        "extra_in_provider": extra_in_provider,
    }
    if missing_from_provider or extra_in_provider:
        return {
            "status": "invalid",
            "detail_status": "corporate_action_conflict",
            "packet_verified": False,
            "technical_metrics_allowed": False,
            "symbol": normalized_symbol,
            "errors": [],
            "event_mismatches": mismatches,
        }
    return {
        "status": "ok",
        "detail_status": "packet_verified",
        "packet_verified": True,
        # Packet-only validation cannot authorize technical metrics for an
        # unrelated series. yf.history_integrity_decision performs the final
        # binding to the actual series end, provider, locator and adjustment.
        "technical_metrics_allowed": False,
        "authorization_scope": "packet_only",
        "symbol": normalized_symbol,
        "errors": [],
        "event_mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify ETF provider history against source-backed corporate actions."
    )
    parser.add_argument("packet_json")
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.packet_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = {
            "status": "data_error",
            "detail_status": "input_read_failed",
            "packet_verified": False,
            "technical_metrics_allowed": False,
            "symbol": None,
            "errors": [str(exc)],
            "event_mismatches": {},
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    report = evaluate_history_integrity(payload)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("packet_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
