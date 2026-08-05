"""Deterministic, read-only portfolio/quote Daily Sync orchestrator.

The orchestrator consumes an already-captured quote packet. It performs no
network calls and does not write positions, dashboards, theses, or journals.
It may close quote completeness, but the top-level workflow remains incomplete
until a separate primary-source Thesis red-team assessment is complete.
"""

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from portfolio_loader import is_cash_position, load_positions, normalize_symbol
from yf import (
    MAX_QUOTE_AGE_SECONDS,
    _expected_position_metadata,
    build_portfolio_batch_audit,
)
from quote_evidence_contract import (
    build_portfolio_snapshot_binding,
    canonical_json_binding,
)


SCHEMA_VERSION = "pia_daily_sync_offline_v3"


def _thesis_not_assessed() -> Dict[str, Any]:
    return {
        "status": "not_assessed",
        "evidence_status": "insufficient_evidence",
        "fatal_event_status": "not_assessed",
        "reason": (
            "This offline quote packet does not establish primary-source company, "
            "industry, regulatory, or macro event coverage. Missing news is not "
            "evidence that a thesis is safe."
        ),
    }


def _base_report(
    positions_file: Optional[str],
    quotes_file: Optional[str],
    now_epoch: Optional[float],
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "incomplete",
        "decision_scope": "research_only",
        "operation_mode": "read_only_offline",
        "evaluation_epoch": now_epoch,
        "inputs": {
            "positions_file": str(Path(positions_file).expanduser().resolve())
            if positions_file
            else None,
            "quotes_file": str(Path(quotes_file).expanduser().resolve())
            if quotes_file
            else None,
        },
        "stages": [
            {"stage": "positions_validation", "status": "not_run", "errors": [], "warnings": []},
            {"stage": "quote_package_validation", "status": "not_run", "errors": [], "warnings": []},
            {"stage": "quote_contract_validation", "status": "not_run", "errors": [], "warnings": []},
            {"stage": "completeness", "status": "not_run", "errors": [], "warnings": []},
            {
                "stage": "thesis_red_team",
                "status": "not_assessed",
                "errors": [],
                "warnings": ["primary_event_evidence_not_supplied"],
            },
        ],
        "requested": 0,
        "succeeded": 0,
        "matched": 0,
        "completeness": {
            "complete": False,
            "expected_symbols": [],
            "returned_symbols": [],
            "missing_symbols": [],
            "extra_symbols": [],
            "duplicate_symbols": [],
            "coverage_complete": False,
            "identity_complete": False,
            "supplied_audit_complete": False,
            "recomputed_audit_complete": False,
            "thesis_assessment_complete": False,
        },
        "quote_snapshot": [],
        "input_bindings": {
            "portfolio_snapshot": None,
            "quote_package": None,
            "quote_snapshot": None,
        },
        "supplied_portfolio_batch_audit": None,
        "recomputed_portfolio_batch_audit": None,
        "thesis_red_team": _thesis_not_assessed(),
        "errors": [],
        "warnings": [],
    }


def _read_json(path: str, label: str) -> Any:
    resolved = Path(path).expanduser()
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{label}_read_error: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label}_json_error: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _normalize_quote_package(payload: Any) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    records: Any = None
    audit: Any = None

    if isinstance(payload, dict):
        records = payload.get("records")
        audit = payload.get("portfolio_batch_audit")
        has_inline_audit = any(
            "portfolio_batch_audit" in record
            for record in records or []
            if isinstance(record, dict)
        ) if isinstance(records, list) else False
        if has_inline_audit:
            errors.append("inline_portfolio_batch_audit_not_allowed")
    else:
        errors.append("quotes_root_must_be_an_object")

    if not isinstance(records, list):
        errors.append("quotes.records_must_be_a_list")
        records = []
    elif any(not isinstance(record, dict) for record in records):
        errors.append("every_quote_record_must_be_an_object")
        records = [record for record in records if isinstance(record, dict)]
    if not isinstance(audit, dict):
        if "missing_portfolio_batch_audit" not in errors:
            errors.append("missing_portfolio_batch_audit")
        audit = None
    return records, audit, warnings, errors


def _positive_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _record_price(record: Dict[str, Any]) -> Optional[float]:
    info = record.get("info") if isinstance(record.get("info"), dict) else {}
    context = (
        record.get("portfolio_context")
        if isinstance(record.get("portfolio_context"), dict)
        else {}
    )
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    for value in (
        info.get("regularMarketPrice"),
        info.get("currentPrice"),
        context.get("current_price"),
        summary.get("last_close"),
    ):
        parsed = _positive_number(value)
        if parsed is not None:
            return parsed
    return None


def _successful_record(record: Dict[str, Any]) -> bool:
    return not record.get("error") and not record.get("errors") and _record_price(record) is not None


def _audit_claim_errors(
    audit: Optional[Dict[str, Any]],
    expected_symbols: List[str],
    records: List[Dict[str, Any]],
    expected_portfolio_binding: Dict[str, Any],
) -> List[str]:
    if not isinstance(audit, dict):
        return ["missing_portfolio_batch_audit"]
    errors: List[str] = []
    requested = len(expected_symbols)
    expected_set = set(expected_symbols)
    count_fields = {
        "requested_count": requested,
        "result_record_count": len(records),
        "resolved_symbol_count": requested,
        "unique_resolved_symbol_count": requested,
        "quote_success_count": requested,
        "portfolio_matched_count": requested,
        "quote_contract_matched_count": requested,
    }
    for field, expected in count_fields.items():
        if audit.get(field) != expected:
            errors.append(f"portfolio_batch_audit.{field}_mismatch")
    if audit.get("complete") is not True:
        errors.append("portfolio_batch_audit.complete_not_true")
    if audit.get("coverage_complete") is not True:
        errors.append("portfolio_batch_audit.coverage_complete_not_true")
    if audit.get("portfolio_load_status") != "ok":
        errors.append("portfolio_batch_audit.portfolio_load_status_not_ok")
    if audit.get("portfolio_load_error") not in (None, ""):
        errors.append("portfolio_batch_audit.portfolio_load_error_present")
    if audit.get("strict_quote_contract") is not True:
        errors.append("portfolio_batch_audit.strict_quote_contract_not_true")
    if audit.get("quote_contract_failures", {}) not in (None, {}):
        errors.append("portfolio_batch_audit.quote_contract_failures_not_empty")
    if audit.get("portfolio_snapshot_binding") != expected_portfolio_binding:
        errors.append("portfolio_batch_audit.portfolio_snapshot_binding_mismatch")

    for field in (
        "quote_failed_symbols",
        "unmatched_symbols",
        "duplicate_requested_symbols",
        "missing_requested_symbols",
        "unexpected_requested_symbols",
        "result_error_symbols",
        "stale_quote_symbols",
    ):
        if audit.get(field, []) not in (None, []):
            errors.append(f"portfolio_batch_audit.{field}_not_empty")

    audit_expected = {
        normalize_symbol(symbol)
        for symbol in audit.get("expected_active_symbols", [])
        if isinstance(symbol, str)
    }
    audit_returned = [
        normalize_symbol(symbol)
        for symbol in audit.get("returned_symbols", [])
        if isinstance(symbol, str)
    ]
    if audit_expected != expected_set:
        errors.append("portfolio_batch_audit.expected_active_symbols_mismatch")
    if len(audit_returned) != requested or set(audit_returned) != expected_set:
        errors.append("portfolio_batch_audit.returned_symbols_mismatch")
    return sorted(set(errors))


def _iso_utc(epoch: Any) -> Optional[str]:
    value = _positive_number(epoch)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except (OverflowError, OSError, ValueError):
        return None


def _build_quote_snapshot(
    records: List[Dict[str, Any]],
    expected_positions: Dict[str, Dict[str, Any]],
    contract_failures: Dict[str, List[str]],
    now_epoch: float,
) -> List[Dict[str, Any]]:
    expected_order = {symbol: index for index, symbol in enumerate(expected_positions)}
    indexed_records = list(enumerate(records))
    indexed_records.sort(
        key=lambda item: (
            expected_order.get(
                normalize_symbol(item[1].get("symbol") or ""),
                len(expected_order),
            ),
            normalize_symbol(item[1].get("symbol") or ""),
            item[0],
        )
    )
    snapshots: List[Dict[str, Any]] = []
    for _, record in indexed_records:
        symbol = normalize_symbol(record.get("symbol") or "")
        info = record.get("info") if isinstance(record.get("info"), dict) else {}
        context = (
            record.get("portfolio_context")
            if isinstance(record.get("portfolio_context"), dict)
            else {}
        )
        position = expected_positions.get(symbol, {})
        quote_epoch = _positive_number(info.get("regularMarketTime"))
        failures = list(contract_failures.get(symbol, []))
        snapshots.append(
            {
                "symbol": symbol or str(record.get("query") or "UNKNOWN"),
                "current_price": _record_price(record),
                "currency": info.get("currency"),
                "position_currency": position.get("currency"),
                "exchange": info.get("exchange") or info.get("exchangeName"),
                "provider_quote_type": info.get("quoteType"),
                "position_market": position.get("market"),
                "position_asset_type": position.get("asset_type"),
                "market_state": info.get("marketState"),
                "as_of": _iso_utc(quote_epoch),
                "quote_age_seconds": round(now_epoch - quote_epoch, 3)
                if quote_epoch is not None
                else None,
                "source": (record.get("data_sources") or {}).get("price")
                if isinstance(record.get("data_sources"), dict)
                else None,
                "source_locator": (record.get("data_sources") or {}).get(
                    "price_locator"
                )
                if isinstance(record.get("data_sources"), dict)
                else None,
                "position_match_status": context.get("position_status"),
                "identity_status": "matched" if not failures else "failed",
                "identity_errors": failures,
                "record_status": "success" if _successful_record(record) else "failed",
            }
        )
    return snapshots


def evaluate_daily_sync(
    *,
    positions_file: str,
    quotes_file: str,
    now_epoch: Optional[float] = None,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> Dict[str, Any]:
    evaluation_epoch = time.time() if now_epoch is None else now_epoch
    report = _base_report(positions_file, quotes_file, evaluation_epoch)

    if (
        isinstance(evaluation_epoch, bool)
        or not isinstance(evaluation_epoch, (int, float))
        or not math.isfinite(float(evaluation_epoch))
        or float(evaluation_epoch) <= 0
    ):
        report["status"] = "invalid_input"
        report["errors"] = ["now_epoch_must_be_a_positive_finite_number"]
        report["stages"][0]["status"] = "failed"
        report["stages"][0]["errors"] = list(report["errors"])
        return report
    evaluation_epoch = float(evaluation_epoch)
    report["evaluation_epoch"] = evaluation_epoch
    if (
        isinstance(max_quote_age_seconds, bool)
        or not isinstance(max_quote_age_seconds, (int, float))
        or not math.isfinite(float(max_quote_age_seconds))
        or float(max_quote_age_seconds) <= 0
    ):
        report["status"] = "invalid_input"
        report["errors"] = ["max_quote_age_seconds_must_be_positive"]
        report["stages"][0]["status"] = "failed"
        report["stages"][0]["errors"] = list(report["errors"])
        return report

    try:
        raw_portfolio = _read_json(positions_file, "positions_file")
        raw_portfolio_binding = build_portfolio_snapshot_binding(raw_portfolio)
        portfolio = load_positions(positions_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        error = f"positions_validation_failed: {exc}"
        report["status"] = "invalid_input"
        report["errors"] = [error]
        report["stages"][0]["status"] = "failed"
        report["stages"][0]["errors"] = [error]
        return report

    active_positions = [
        position
        for position in portfolio.get("positions", [])
        if not is_cash_position(position)
    ]
    portfolio_binding = build_portfolio_snapshot_binding(portfolio)
    if portfolio_binding != raw_portfolio_binding:
        error = "positions_snapshot_changed_or_loader_cache_mismatch"
        report["status"] = "invalid_input"
        report["errors"] = [error]
        report["stages"][0]["status"] = "failed"
        report["stages"][0]["errors"] = [error]
        return report
    report["input_bindings"]["portfolio_snapshot"] = portfolio_binding
    expected_symbols = [
        normalize_symbol(position.get("symbol") or "")
        for position in active_positions
    ]
    report["requested"] = len(expected_symbols)
    report["completeness"]["expected_symbols"] = expected_symbols
    positions_stage = report["stages"][0]
    if not expected_symbols:
        positions_stage["status"] = "failed"
        positions_stage["errors"] = ["no_active_non_cash_positions"]
        report["errors"] = list(positions_stage["errors"])
        return report
    positions_stage.update(
        {
            "status": "complete",
            "active_non_cash_count": len(expected_symbols),
            "active_non_cash_symbols": expected_symbols,
            "inactive_zero_quantity_symbols": portfolio.get(
                "_inactive_zero_quantity_symbols", []
            ),
        }
    )

    try:
        quotes_payload = _read_json(quotes_file, "quotes_file")
    except ValueError as exc:
        error = str(exc)
        report["status"] = "invalid_input"
        report["errors"] = [error]
        report["stages"][1]["status"] = "failed"
        report["stages"][1]["errors"] = [error]
        return report
    try:
        report["input_bindings"]["quote_package"] = canonical_json_binding(
            quotes_payload
        )
    except (TypeError, ValueError) as exc:
        error = f"quotes_file_canonicalization_error: {exc}"
        report["status"] = "invalid_input"
        report["errors"] = [error]
        report["stages"][1]["status"] = "failed"
        report["stages"][1]["errors"] = [error]
        return report

    records, supplied_audit, package_warnings, package_errors = _normalize_quote_package(
        quotes_payload
    )
    package_stage = report["stages"][1]
    package_stage["warnings"] = package_warnings
    package_stage["errors"] = package_errors
    package_stage["record_count"] = len(records)
    package_stage["status"] = "complete" if not package_errors else "incomplete"
    report["warnings"].extend(package_warnings)
    report["supplied_portfolio_batch_audit"] = supplied_audit

    returned_symbols = [
        normalize_symbol(record.get("symbol") or "")
        for record in records
        if normalize_symbol(record.get("symbol") or "")
    ]
    duplicates = sorted(
        {symbol for symbol in returned_symbols if returned_symbols.count(symbol) > 1}
    )
    expected_set = set(expected_symbols)
    returned_set = set(returned_symbols)
    missing = sorted(expected_set - returned_set)
    extra = sorted(returned_set - expected_set)
    report["succeeded"] = sum(_successful_record(record) for record in records)
    report["matched"] = sum(
        1
        for record in records
        if isinstance(record.get("portfolio_context"), dict)
        and record["portfolio_context"].get("position_status") == "matched"
    )

    expected_metadata = _expected_position_metadata(portfolio)
    recomputed_audit = build_portfolio_batch_audit(
        records,
        requested_count=len(expected_symbols),
        expected_symbols=expected_symbols,
        portfolio_load_status=portfolio.get("_status"),
        portfolio_load_error=None,
        expected_position_metadata=expected_metadata,
        now_epoch=evaluation_epoch,
        max_quote_age_seconds=int(max_quote_age_seconds),
        portfolio_snapshot_binding=portfolio_binding,
    )
    report["recomputed_portfolio_batch_audit"] = recomputed_audit
    supplied_audit_errors = _audit_claim_errors(
        supplied_audit, expected_symbols, records, portfolio_binding
    )
    supplied_audit_complete = not supplied_audit_errors
    contract_failures = {
        symbol: list(errors)
        for symbol, errors in recomputed_audit.get(
            "quote_contract_failures", {}
        ).items()
    }
    for record in records:
        symbol = normalize_symbol(record.get("symbol") or "") or str(
            record.get("query") or "UNKNOWN"
        )
        sources = (
            record.get("data_sources")
            if isinstance(record.get("data_sources"), dict)
            else {}
        )
        price_source = sources.get("price")
        expected_locator = f"yfinance:{symbol}:quote"
        if price_source != "Yahoo Finance":
            contract_failures.setdefault(symbol, []).append(
                "identity_mismatch.data_sources.price"
            )
        if sources.get("price_locator") != expected_locator:
            contract_failures.setdefault(symbol, []).append(
                "identity_mismatch.data_sources.price_locator"
            )
    identity_complete = (
        recomputed_audit.get("quote_contract_matched_count") == len(expected_symbols)
        and not contract_failures
        and len(records) == len(expected_symbols)
    )
    coverage_complete = (
        len(records) == len(expected_symbols)
        and len(returned_symbols) == len(expected_symbols)
        and not missing
        and not extra
        and not duplicates
    )
    recomputed_complete = recomputed_audit.get("complete") is True

    contract_stage = report["stages"][2]
    contract_stage["status"] = (
        "complete" if recomputed_complete and not contract_failures else "incomplete"
    )
    contract_stage["errors"] = [
        f"{symbol}: {error}"
        for symbol in sorted(contract_failures)
        for error in contract_failures[symbol]
    ]
    contract_stage["warnings"] = [
        f"{symbol}: {warning}"
        for symbol in sorted(recomputed_audit.get("quote_contract_warnings", {}))
        for warning in recomputed_audit["quote_contract_warnings"][symbol]
    ]
    contract_stage["supplied_audit_errors"] = supplied_audit_errors

    report["quote_snapshot"] = _build_quote_snapshot(
        records,
        expected_metadata,
        contract_failures,
        evaluation_epoch,
    )
    report["input_bindings"]["quote_snapshot"] = canonical_json_binding(
        report["quote_snapshot"]
    )
    completeness = report["completeness"]
    completeness.update(
        {
            "expected_symbols": expected_symbols,
            "returned_symbols": returned_symbols,
            "missing_symbols": missing,
            "extra_symbols": extra,
            "duplicate_symbols": duplicates,
            "coverage_complete": coverage_complete,
            "identity_complete": identity_complete,
            "supplied_audit_complete": supplied_audit_complete,
            "recomputed_audit_complete": recomputed_complete,
        }
    )
    quote_refresh_complete = (
        not package_errors
        and coverage_complete
        and identity_complete
        and supplied_audit_complete
        and recomputed_complete
        and report["succeeded"] == len(expected_symbols)
        and report["matched"] == len(expected_symbols)
    )
    thesis_assessment_complete = (
        report["thesis_red_team"].get("status") == "complete"
        and report["thesis_red_team"].get("evidence_status") == "ok"
    )
    completeness["complete"] = quote_refresh_complete
    completeness["thesis_assessment_complete"] = thesis_assessment_complete
    completeness_stage = report["stages"][3]
    completeness_stage["status"] = (
        "complete" if quote_refresh_complete else "incomplete"
    )
    completeness_stage["errors"] = sorted(
        set(
            package_errors
            + supplied_audit_errors
            + ([] if coverage_complete else ["quote_universe_not_exact"])
            + ([] if identity_complete else ["quote_identity_not_complete"])
            + ([] if recomputed_complete else ["recomputed_batch_audit_incomplete"])
        )
    )
    workflow_complete = quote_refresh_complete and thesis_assessment_complete
    report["errors"] = list(completeness_stage["errors"])
    if not thesis_assessment_complete:
        report["errors"].append("thesis_red_team_incomplete")
    report["status"] = "complete" if workflow_complete else "incomplete"
    return report


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        report = _base_report(None, None, None)
        report["status"] = "invalid_input"
        report["errors"] = [f"argument_error: {message}"]
        report["stages"][0]["status"] = "failed"
        report["stages"][0]["errors"] = list(report["errors"])
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(2)


def main() -> None:
    parser = JsonArgumentParser(
        description="Read-only offline PIA Daily Sync quote/portfolio contract audit."
    )
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--quotes-file", required=True)
    parser.add_argument("--now-epoch", type=float)
    parser.add_argument(
        "--max-quote-age-seconds",
        type=int,
        default=MAX_QUOTE_AGE_SECONDS,
    )
    args = parser.parse_args()
    report = evaluate_daily_sync(
        positions_file=args.positions_file,
        quotes_file=args.quotes_file,
        now_epoch=args.now_epoch,
        max_quote_age_seconds=args.max_quote_age_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] == "complete":
        raise SystemExit(0)
    if report["status"] == "invalid_input":
        raise SystemExit(2)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
