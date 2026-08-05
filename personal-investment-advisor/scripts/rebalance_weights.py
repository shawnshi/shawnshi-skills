"""Read-only PIA current-weight calculator and optional allocation experiment.

Current weights are calculated only from a validated Daily Sync report. The
module performs no network calls and never mutates the positions file. An
optional policy is delegated to the offline inverse-volatility research
experiment; its output is not written into holdings.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from portfolio_loader import (
    get_exchange_rate_details,
    is_cash_position,
    load_positions,
    normalize_symbol,
)
from rebalance_optimizer import run_inverse_volatility_experiment
from quote_evidence_contract import (
    MAX_QUOTE_FUTURE_SKEW_SECONDS,
    build_portfolio_snapshot_binding,
    canonical_json_binding,
    quote_freshness_policy,
)


SCHEMA_VERSION = "pia_rebalance_research_v1"
DAILY_SYNC_SCHEMA_VERSION = "pia_daily_sync_offline_v3"
MAX_DAILY_SYNC_REPORT_AGE_SECONDS = 15 * 60
MAX_FX_AGE_SECONDS = 72 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 60


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_aware_iso(value: Any) -> datetime | None:
    parsed = _parse_iso(value)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _base_report(filepath: str | None, quotes_file: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid_input",
        "detail_status": "not_evaluated",
        "research_only": True,
        "decision_scope": "research_only",
        "operation_mode": "read_only_offline",
        "mutation_performed": False,
        "inputs": {
            "positions_file": str(Path(filepath).expanduser().resolve()) if filepath else None,
            "daily_sync_report": str(Path(quotes_file).expanduser().resolve()) if quotes_file else None,
        },
        "current_weight_status": "not_computed",
        "current_weights": [],
        "allocation_experiment": {
            "status": "not_requested",
            "research_only": True,
        },
        "inactive_zero_quantity_symbols": [],
        "errors": [],
        "warnings": [],
        "fail_closed": {"enforced": True, "triggered": True},
    }


def _fail(
    report: dict[str, Any],
    detail_status: str,
    errors: Iterable[str],
    *,
    status: str,
) -> dict[str, Any]:
    report["status"] = status
    report["detail_status"] = detail_status
    report["errors"] = list(errors)
    report["fail_closed"] = {"enforced": True, "triggered": True}
    return report


def _read_json(path: str, label: str) -> Any:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label}_read_error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label}_json_error: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def _normalized_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def _stage_status(report: dict[str, Any], stage_name: str) -> str | None:
    stages = report.get("stages")
    if not isinstance(stages, list):
        return None
    matches = [
        stage
        for stage in stages
        if isinstance(stage, dict) and stage.get("stage") == stage_name
    ]
    if len(matches) != 1:
        return None
    status = matches[0].get("status")
    return status if isinstance(status, str) else None


def _validate_daily_sync_report(
    payload: Any,
    *,
    positions_path: str,
    active_positions: list[dict[str, Any]],
    consumer_epoch: float,
    max_report_age_seconds: int,
    current_portfolio_binding: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Validate the offline Daily Sync result without trusting its top status.

    The current Daily Sync workflow remains top-level ``incomplete`` until a
    separate Thesis red-team pass is done. Weight calculation only consumes its
    independently closed quote-completeness contract.
    """

    if not isinstance(payload, dict):
        return {}, ["daily_sync_report root must be an object"]
    errors: list[str] = []
    if payload.get("schema_version") != DAILY_SYNC_SCHEMA_VERSION:
        errors.append(
            f"daily_sync_report.schema_version must equal {DAILY_SYNC_SCHEMA_VERSION}"
        )
    if payload.get("decision_scope") != "research_only":
        errors.append("daily_sync_report.decision_scope must equal research_only")
    if payload.get("operation_mode") != "read_only_offline":
        errors.append("daily_sync_report.operation_mode must equal read_only_offline")
    report_positions_path = _normalized_path(
        (payload.get("inputs") or {}).get("positions_file")
        if isinstance(payload.get("inputs"), dict)
        else None
    )
    if report_positions_path != _normalized_path(positions_path):
        errors.append("daily_sync_report positions_file does not match the current portfolio")

    bindings = payload.get("input_bindings")
    if not isinstance(bindings, dict):
        bindings = {}
        errors.append("daily_sync_report.input_bindings must be an object")
    if bindings.get("portfolio_snapshot") != current_portfolio_binding:
        errors.append("daily_sync_report portfolio snapshot binding does not match current holdings")

    report_quote_path = (
        (payload.get("inputs") or {}).get("quotes_file")
        if isinstance(payload.get("inputs"), dict)
        else None
    )
    if not isinstance(report_quote_path, str) or not report_quote_path.strip():
        errors.append("daily_sync_report original quotes_file path is missing")
    else:
        try:
            current_quote_package = _read_json(report_quote_path, "daily_sync_input_quotes_file")
            current_quote_binding = canonical_json_binding(current_quote_package)
        except (TypeError, ValueError) as exc:
            current_quote_binding = None
            errors.append(f"daily_sync_report original quote package cannot be verified: {exc}")
        if bindings.get("quote_package") != current_quote_binding:
            errors.append("daily_sync_report quote package binding does not match current input")

    completeness = payload.get("completeness")
    if not isinstance(completeness, dict) or completeness.get("complete") is not True:
        errors.append("daily_sync_report quote completeness is not complete")
    for stage_name in (
        "positions_validation",
        "quote_package_validation",
        "quote_contract_validation",
        "completeness",
    ):
        if _stage_status(payload, stage_name) != "complete":
            errors.append(f"daily_sync_report stage {stage_name} is not complete")
    audit = payload.get("recomputed_portfolio_batch_audit")
    if not isinstance(audit, dict) or audit.get("complete") is not True:
        errors.append("daily_sync_report recomputed quote audit is not complete")

    expected_positions = {
        normalize_symbol(position.get("symbol") or ""): position
        for position in active_positions
        if not is_cash_position(position)
    }
    expected_symbols = set(expected_positions)
    if isinstance(audit, dict):
        raw_audit_symbols = audit.get("expected_active_symbols")
        if not isinstance(raw_audit_symbols, list):
            errors.append(
                "daily_sync_report recomputed audit expected_active_symbols must be a list"
            )
            audit_symbols: set[str] = set()
        else:
            audit_symbols = {
                normalize_symbol(symbol)
                for symbol in raw_audit_symbols
                if isinstance(symbol, str) and normalize_symbol(symbol)
            }
        if audit_symbols != expected_symbols:
            errors.append(
                "daily_sync_report recomputed audit is not bound to the active portfolio universe"
            )
        if audit.get("strict_quote_contract") is not True:
            errors.append("daily_sync_report strict quote contract is not enabled")
        for field in (
            "quote_contract_failures",
            "quote_failed_symbols",
            "result_error_symbols",
            "stale_quote_symbols",
            "unmatched_symbols",
        ):
            if audit.get(field) not in ({}, [], None):
                errors.append(f"daily_sync_report recomputed audit {field} is not empty")
    snapshots = payload.get("quote_snapshot")
    if not isinstance(snapshots, list):
        return {}, errors + ["daily_sync_report.quote_snapshot must be a list"]
    try:
        current_snapshot_binding = canonical_json_binding(snapshots)
    except (TypeError, ValueError) as exc:
        current_snapshot_binding = None
        errors.append(f"daily_sync_report quote snapshot cannot be bound: {exc}")
    if bindings.get("quote_snapshot") != current_snapshot_binding:
        errors.append("daily_sync_report quote snapshot binding mismatch")
    by_symbol: dict[str, dict[str, Any]] = {}
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, dict):
            errors.append(f"daily_sync_report.quote_snapshot[{index}] must be an object")
            continue
        symbol = normalize_symbol(snapshot.get("symbol") or "")
        if not symbol:
            errors.append(f"daily_sync_report.quote_snapshot[{index}].symbol is invalid")
            continue
        if symbol in by_symbol:
            errors.append(f"daily_sync_report contains duplicate quote for {symbol}")
            continue
        by_symbol[symbol] = snapshot
    if set(by_symbol) != expected_symbols:
        missing = sorted(expected_symbols - set(by_symbol))
        extra = sorted(set(by_symbol) - expected_symbols)
        if missing:
            errors.append("daily_sync_report missing active symbols: " + ", ".join(missing))
        if extra:
            errors.append("daily_sync_report contains unexpected symbols: " + ", ".join(extra))

    evaluation_epoch = _finite_number(payload.get("evaluation_epoch"))
    if evaluation_epoch is None or evaluation_epoch <= 0:
        errors.append("daily_sync_report.evaluation_epoch must be positive and finite")
    else:
        report_age_seconds = consumer_epoch - evaluation_epoch
        if report_age_seconds < -MAX_FUTURE_SKEW_SECONDS:
            errors.append("daily_sync_report.evaluation_epoch is in the future")
        elif report_age_seconds > max_report_age_seconds:
            errors.append("daily_sync_report is stale for current-weight calculation")
    for symbol, snapshot in by_symbol.items():
        position = expected_positions.get(symbol, {})
        price = _finite_number(snapshot.get("current_price"))
        if price is None or price <= 0:
            errors.append(f"{symbol}: current_price must be positive and finite")
        if snapshot.get("identity_status") != "matched":
            errors.append(f"{symbol}: quote identity_status is not matched")
        if snapshot.get("record_status") != "success":
            errors.append(f"{symbol}: quote record_status is not success")
        if snapshot.get("identity_errors") not in ([], None):
            errors.append(f"{symbol}: quote identity_errors is not empty")
        expected_currency = str(position.get("currency") or "").upper()
        quote_currency = str(snapshot.get("currency") or "").upper()
        if quote_currency != expected_currency:
            errors.append(f"{symbol}: quote currency does not match position currency")
        if str(snapshot.get("position_currency") or "").upper() != expected_currency:
            errors.append(f"{symbol}: quote position_currency is not bound to the portfolio")
        if str(snapshot.get("position_market") or "").upper() != str(
            position.get("market") or ""
        ).upper():
            errors.append(f"{symbol}: quote position_market is not bound to the portfolio")
        if str(snapshot.get("position_asset_type") or "").lower() != str(
            position.get("asset_type") or ""
        ).lower():
            errors.append(f"{symbol}: quote position_asset_type is not bound to the portfolio")
        if snapshot.get("source") != "Yahoo Finance":
            errors.append(f"{symbol}: quote source is not the Daily Sync provider")
        if snapshot.get("source_locator") != f"yfinance:{symbol}:quote":
            errors.append(f"{symbol}: quote source_locator is not contract-bound")
        quote_as_of = _parse_aware_iso(snapshot.get("as_of"))
        if quote_as_of is None:
            errors.append(f"{symbol}: quote as_of must be a timezone-aware ISO datetime")
        quote_age = _finite_number(snapshot.get("quote_age_seconds"))
        if quote_age is None:
            errors.append(f"{symbol}: quote_age_seconds must be finite")
        if quote_as_of is not None and evaluation_epoch is not None and quote_age is not None:
            recomputed_age = evaluation_epoch - quote_as_of.astimezone(timezone.utc).timestamp()
            if abs(recomputed_age - quote_age) > 1.0:
                errors.append(f"{symbol}: quote age is not bound to evaluation_epoch")
        market_state = snapshot.get("market_state")
        freshness = quote_freshness_policy(market_state)
        if not isinstance(market_state, str) or not market_state.strip():
            errors.append(f"{symbol}: quote market_state is missing")
        elif freshness.get("applied_max_age_seconds") is None:
            errors.append(f"{symbol}: quote market_state is unknown")
        if quote_as_of is not None:
            actual_age = consumer_epoch - quote_as_of.astimezone(timezone.utc).timestamp()
            if actual_age < -MAX_QUOTE_FUTURE_SKEW_SECONDS:
                errors.append(f"{symbol}: quote as_of exceeds allowed future skew")
            elif (
                freshness.get("applied_max_age_seconds") is not None
                and actual_age > float(freshness["applied_max_age_seconds"])
            ):
                errors.append(
                    f"{symbol}: quote is stale for market_state {str(market_state).strip().upper()}"
                )
    return by_symbol, errors


def _dated_fx(
    portfolio: dict[str, Any],
    currency: str,
    *,
    reference_epoch: float,
) -> tuple[dict[str, Any] | None, str | None]:
    base_currency = str(portfolio.get("base_currency") or "").upper()
    normalized_currency = str(currency or "").upper()
    try:
        details = get_exchange_rate_details(normalized_currency, portfolio)
    except ValueError as exc:
        return None, str(exc)
    if normalized_currency == base_currency:
        return {
            "rate": 1.0,
            "pair": f"{base_currency}/{base_currency}",
            "as_of": None,
            "source": "currency_identity",
            "source_locator": None,
            "retrieved_at": None,
            "data_status": "base_currency_identity",
        }, None
    if details.get("data_status") != "dated_snapshot":
        return None, (
            f"{normalized_currency}: cross-currency current weights require a dated, "
            "source-labelled exchange-rate snapshot"
        )
    metadata_by_currency = portfolio.get("exchange_rate_metadata")
    metadata = None
    if isinstance(metadata_by_currency, dict):
        metadata = next(
            (
                value
                for key, value in metadata_by_currency.items()
                if isinstance(key, str) and key.strip().upper() == normalized_currency
            ),
            None,
        )
    if not isinstance(metadata, dict):
        return None, f"{normalized_currency}: exchange-rate metadata is missing"
    fx_as_of = _parse_iso(metadata.get("as_of"))
    if fx_as_of is None:
        return None, f"{normalized_currency}: exchange-rate as_of is invalid"
    fx_retrieved = _parse_aware_iso(metadata.get("retrieved_at"))
    if fx_retrieved is None:
        return None, f"{normalized_currency}: exchange-rate retrieved_at is invalid"
    if not isinstance(metadata.get("source"), str) or not metadata["source"].strip():
        return None, f"{normalized_currency}: exchange-rate source is missing"
    if not isinstance(metadata.get("source_locator"), str) or not metadata[
        "source_locator"
    ].strip():
        return None, f"{normalized_currency}: exchange-rate source_locator is missing"
    comparable_as_of = (
        fx_as_of.replace(tzinfo=timezone.utc)
        if fx_as_of.tzinfo is None
        else fx_as_of.astimezone(timezone.utc)
    )
    fx_age_seconds = reference_epoch - comparable_as_of.timestamp()
    if fx_age_seconds < -MAX_FUTURE_SKEW_SECONDS:
        return None, f"{normalized_currency}: exchange-rate as_of is in the future"
    if fx_age_seconds > MAX_FX_AGE_SECONDS:
        return None, f"{normalized_currency}: exchange-rate snapshot is stale"
    if fx_retrieved.astimezone(timezone.utc).timestamp() > reference_epoch + MAX_FUTURE_SKEW_SECONDS:
        return None, f"{normalized_currency}: exchange-rate retrieved_at is in the future"
    return {
        "rate": details["rate"],
        "pair": metadata.get("pair"),
        "as_of": metadata.get("as_of"),
        "source": metadata.get("source"),
        "source_locator": metadata.get("source_locator"),
        "retrieved_at": metadata.get("retrieved_at"),
        "age_seconds": round(fx_age_seconds, 3),
        "max_age_seconds": MAX_FX_AGE_SECONDS,
        "data_status": "dated_snapshot",
    }, None


def recalculate_all_weights(
    filepath: str,
    *,
    quotes_file: str | None = None,
    policy_file: str | None = None,
    now_epoch: float | None = None,
    max_report_age_seconds: int = MAX_DAILY_SYNC_REPORT_AGE_SECONDS,
) -> dict[str, Any]:
    """Calculate current weights without fetching data or mutating holdings."""

    report = _base_report(filepath, quotes_file)
    explicit_replay = now_epoch is not None
    consumer_epoch = time.time() if now_epoch is None else _finite_number(now_epoch)
    if consumer_epoch is None or consumer_epoch <= 0:
        return _fail(
            report,
            "evaluation_epoch_invalid",
            ["now_epoch must be a positive finite JSON number"],
            status="invalid_input",
        )
    if (
        isinstance(max_report_age_seconds, bool)
        or not isinstance(max_report_age_seconds, (int, float))
        or not math.isfinite(float(max_report_age_seconds))
        or float(max_report_age_seconds) <= 0
    ):
        return _fail(
            report,
            "report_age_policy_invalid",
            ["max_report_age_seconds must be positive and finite"],
            status="invalid_input",
        )
    report["evaluation_epoch"] = consumer_epoch
    report["time_basis"] = (
        "explicit_point_in_time_replay" if explicit_replay else "current_runtime"
    )
    report["max_daily_sync_report_age_seconds"] = float(max_report_age_seconds)
    if not filepath:
        return _fail(
            report,
            "positions_file_missing",
            ["filepath is required"],
            status="invalid_input",
        )
    try:
        raw_portfolio = _read_json(filepath, "positions_file")
    except ValueError as exc:
        return _fail(
            report,
            "positions_validation_failed",
            [str(exc)],
            status="invalid_input",
        )
    try:
        current_portfolio_binding = build_portfolio_snapshot_binding(raw_portfolio)
    except ValueError as exc:
        return _fail(
            report,
            "positions_snapshot_binding_failed",
            [str(exc)],
            status="invalid_input",
        )
    if isinstance(raw_portfolio, dict) and "rebalance_policy" in raw_portfolio:
        return _fail(
            report,
            "embedded_rebalance_policy_prohibited",
            [
                "rebalance policy must be supplied as a separate --policy-file using pia_inverse_volatility_policy_v1"
            ],
            status="invalid_input",
        )
    try:
        portfolio = load_positions(filepath)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _fail(
            report,
            "positions_validation_failed",
            [str(exc)],
            status="invalid_input",
        )
    if build_portfolio_snapshot_binding(portfolio) != current_portfolio_binding:
        return _fail(
            report,
            "positions_snapshot_changed_or_loader_cache_mismatch",
            ["loaded positions do not match the current file snapshot"],
            status="invalid_input",
        )
    active_positions = portfolio.get("positions", [])
    report["inactive_zero_quantity_symbols"] = portfolio.get(
        "_inactive_zero_quantity_symbols", []
    )
    if not active_positions:
        return _fail(
            report,
            "no_active_positions",
            ["portfolio has no active positions"],
            status="insufficient_evidence",
        )

    non_cash_positions = [
        position for position in active_positions if not is_cash_position(position)
    ]
    quotes: dict[str, dict[str, Any]] = {}
    if non_cash_positions:
        if not quotes_file:
            return _fail(
                report,
                "validated_daily_sync_report_required",
                [
                    "current weights for non-cash positions require --quotes-file pointing to a validated Daily Sync report"
                ],
                status="insufficient_evidence",
            )
        try:
            quote_payload = _read_json(quotes_file, "quotes_file")
        except ValueError as exc:
            return _fail(
                report,
                "daily_sync_report_unreadable",
                [str(exc)],
                status="invalid_input",
            )
        quotes, quote_errors = _validate_daily_sync_report(
            quote_payload,
            positions_path=filepath,
            active_positions=active_positions,
            consumer_epoch=consumer_epoch,
            max_report_age_seconds=int(max_report_age_seconds),
            current_portfolio_binding=current_portfolio_binding,
        )
        if quote_errors:
            return _fail(
                report,
                "daily_sync_quote_contract_failed",
                quote_errors,
                status="insufficient_evidence",
            )

    rows: list[dict[str, Any]] = []
    evidence_errors: list[str] = []
    for position in active_positions:
        symbol = normalize_symbol(position.get("symbol") or "")
        quantity = _finite_number(position.get("quantity"))
        if quantity is None or quantity <= 0:
            evidence_errors.append(f"{symbol}: active quantity must be positive and finite")
            continue
        fx, fx_error = _dated_fx(
            portfolio,
            str(position.get("currency") or ""),
            reference_epoch=consumer_epoch,
        )
        if fx_error or fx is None:
            evidence_errors.append(fx_error or f"{symbol}: exchange-rate evidence missing")
            continue
        if is_cash_position(position):
            price = 1.0
            quote_evidence = {
                "as_of": None,
                "source": "cash_unit_identity",
                "source_locator": None,
            }
        else:
            snapshot = quotes[symbol]
            price = float(snapshot["current_price"])
            quote_evidence = {
                "as_of": snapshot.get("as_of"),
                "source": snapshot.get("source"),
                "source_locator": snapshot.get("source_locator"),
                "market_state": snapshot.get("market_state"),
            }
        market_value = quantity * price * float(fx["rate"])
        rows.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "currency": str(position.get("currency") or "").upper(),
                "current_price": price,
                "quote": quote_evidence,
                "fx_to_base": fx,
                "market_value_base": round(market_value, 10),
                "_market_value_exact": market_value,
            }
        )
    if evidence_errors:
        return _fail(
            report,
            "market_value_evidence_incomplete",
            evidence_errors,
            status="insufficient_evidence",
        )
    total_value = sum(row["_market_value_exact"] for row in rows)
    if not math.isfinite(total_value) or total_value <= 0:
        return _fail(
            report,
            "portfolio_market_value_invalid",
            ["portfolio market value must be positive and finite"],
            status="insufficient_evidence",
        )
    for row in rows:
        row["current_weight"] = round(row["_market_value_exact"] / total_value, 10)
        row.pop("_market_value_exact", None)

    report["base_currency"] = str(portfolio.get("base_currency") or "").upper()
    report["portfolio_market_value_base"] = round(total_value, 10)
    report["current_weights"] = rows
    if explicit_replay:
        report["current_weight_status"] = "computed_for_explicit_point_in_time_replay"
    else:
        report["current_weight_status"] = (
            "computed_from_validated_daily_sync_quotes"
            if non_cash_positions
            else "computed_from_cash_identity_and_dated_fx"
        )

    if policy_file:
        try:
            policy = _read_json(policy_file, "policy_file")
        except ValueError as exc:
            return _fail(
                report,
                "policy_file_unreadable",
                [str(exc)],
                status="invalid_input",
            )
        experiment = run_inverse_volatility_experiment(active_positions, policy)
        report["allocation_experiment"] = experiment
        if experiment["status"] != "complete":
            return _fail(
                report,
                "allocation_experiment_failed",
                experiment.get("errors", ["allocation experiment failed"]),
                status=experiment.get("status", "invalid_input"),
            )

    report["status"] = "complete"
    report["detail_status"] = (
        "current_weights_and_research_experiment_computed"
        if policy_file
        else "current_weights_computed"
    )
    report["errors"] = []
    report["fail_closed"] = {"enforced": True, "triggered": False}
    return report


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(
            json.dumps(
                _fail(
                    _base_report(None, None),
                    "argument_error",
                    [f"argument_error: {message}"],
                    status="invalid_input",
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(
        description=(
            "Calculate current weights from a validated Daily Sync report and optionally "
            "run an offline inverse-volatility research experiment."
        )
    )
    parser.add_argument("--filepath", required=True)
    parser.add_argument(
        "--quotes-file",
        help="Path to the validated JSON report emitted by daily_sync.py.",
    )
    parser.add_argument("--policy-file")
    parser.add_argument(
        "--as-of-epoch",
        type=float,
        help=(
            "Explicit point-in-time replay epoch. Omit for current-runtime freshness; "
            "replay output is labelled and must not be presented as current."
        ),
    )
    args = parser.parse_args()
    report = recalculate_all_weights(
        args.filepath,
        quotes_file=args.quotes_file,
        policy_file=args.policy_file,
        now_epoch=args.as_of_epoch,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
