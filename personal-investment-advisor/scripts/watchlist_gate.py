import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from dashboard_gate import validate_dashboard


DEFAULT_MAX_QUOTE_AGE_SECONDS = 72 * 60 * 60
_HALTED_MARKET_STATES = {"HALTED", "SUSPENDED", "DELISTED"}
_UNKNOWN_MARKET_STATES = {"UNKNOWN", "N/A", "NONE", "NULL"}
_OBSERVABLE_MARKET_STATES = {
    "PREPRE",
    "PRE",
    "PREOPEN",
    "PRE_OPEN",
    "AUCTION",
    "OPEN",
    "TRADING",
    "REGULAR",
    "BREAK",
    "LUNCH_BREAK",
    "POST",
    "POSTPOST",
    "AFTER_HOURS",
    "CLOSE",
    "CLOSED",
}


def generate_alerts(data: dict) -> list[str]:
    """Return research-monitoring notices without transaction instructions."""
    alerts: list[str] = []

    catalyst_map = data.get("catalyst_map", {})
    if not isinstance(catalyst_map, dict):
        return alerts
    for field, prefix in (
        ("upcoming", "待核验事件"),
        ("broken", "核心假设证伪信号"),
        ("data_gaps", "数据缺口"),
    ):
        items = catalyst_map.get(field, [])
        if not isinstance(items, list):
            continue
        for item in items:
            alerts.append(f"{prefix}: {item}")

    return alerts


def _empty_categories() -> dict[str, list[str]]:
    return {
        "downside_boundary_crossed": [],
        "upside_boundary_crossed": [],
        "near_boundary": [],
        "not_crossed": [],
        "thresholds_undefined": [],
        "near_rule_undefined": [],
        "insufficient_data": [],
    }


def _parse_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _expected_quote_currency(contract: dict) -> str | None:
    currencies = {
        boundary.get("currency", "").strip().upper()
        for boundary in contract.get("boundaries", [])
        if isinstance(boundary, dict)
        and isinstance(boundary.get("currency"), str)
        and boundary.get("currency", "").strip()
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    return None


def _validate_runtime_quote(
    quote_snapshot: object,
    *,
    expected_symbol: str,
    expected_currency: str | None,
    now: datetime,
    max_age_seconds: float,
) -> tuple[list[str], dict | None]:
    errors: list[str] = []
    if not isinstance(quote_snapshot, dict):
        return ["runtime_quote_missing"], None

    symbol = quote_snapshot.get("symbol")
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not normalized_symbol:
        errors.append("runtime_quote_symbol_invalid")
    elif normalized_symbol != expected_symbol.strip().upper():
        errors.append("runtime_quote_symbol_mismatch")

    current_price = quote_snapshot.get("current_price")
    if (
        not isinstance(current_price, (int, float))
        or isinstance(current_price, bool)
        or not math.isfinite(float(current_price))
        or float(current_price) <= 0
    ):
        errors.append("runtime_quote_price_invalid")

    currency = quote_snapshot.get("currency")
    normalized_currency = currency.strip().upper() if isinstance(currency, str) else ""
    if not normalized_currency:
        errors.append("runtime_quote_currency_invalid")
    elif expected_currency is None:
        errors.append("monitoring_boundary_currency_ambiguous")
    elif normalized_currency != expected_currency:
        errors.append("runtime_quote_currency_mismatch")

    as_of = _parse_aware_datetime(quote_snapshot.get("as_of"))
    if as_of is None:
        errors.append("runtime_quote_as_of_invalid")

    source = quote_snapshot.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append("runtime_quote_source_invalid")

    market_state = quote_snapshot.get("market_state")
    normalized_market_state = (
        market_state.strip().upper() if isinstance(market_state, str) else ""
    )
    if normalized_market_state in _HALTED_MARKET_STATES:
        errors.append("runtime_quote_market_halted")
    elif (
        not normalized_market_state
        or normalized_market_state in _UNKNOWN_MARKET_STATES
        or normalized_market_state not in _OBSERVABLE_MARKET_STATES
    ):
        errors.append("runtime_quote_market_state_unknown")

    age_seconds = None
    if as_of is not None:
        age_seconds = (now - as_of).total_seconds()
        if age_seconds < -300:
            errors.append("runtime_quote_from_future")
        elif age_seconds > max_age_seconds:
            errors.append("runtime_quote_stale")

    if errors:
        return list(dict.fromkeys(errors)), None

    return [], {
        "symbol": normalized_symbol,
        "current_price": float(current_price),
        "currency": normalized_currency,
        "as_of": as_of.isoformat(),
        "source": source.strip(),
        "market_state": normalized_market_state,
        "age_seconds": max(0.0, float(age_seconds)),
        "max_age_seconds": float(max_age_seconds),
    }


def evaluate_watchlist(
    data: dict,
    quote_snapshot: dict | None = None,
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_QUOTE_AGE_SECONDS,
) -> dict:
    """Evaluate user-authorized observation boundaries and fail closed."""
    categories = _empty_categories()
    report = {
        "status": "insufficient_data",
        "detail_status": "evaluation_not_completed",
        "evaluation_status": "insufficient_data",
        "decision_scope": "observation_only",
        "metric": "regular_market_price",
        "categories": categories,
        "evaluations": [],
        "research_alerts": generate_alerts(data) if isinstance(data, dict) else [],
        "validation_errors": [],
        "quote_validation_errors": [],
        "runtime_quote": None,
    }

    if not isinstance(data, dict):
        report["validation_errors"] = ["dashboard payload must be an object"]
        categories["insufficient_data"].append("dashboard_invalid")
        report["status"] = "invalid"
        report["detail_status"] = "dashboard_invalid"
        return report

    validation_errors = validate_dashboard(data)
    if validation_errors:
        report["validation_errors"] = validation_errors
        categories["insufficient_data"].append("dashboard_invalid")
        report["status"] = "invalid"
        report["detail_status"] = "dashboard_invalid"
        return report

    contract = data.get("monitoring_boundaries")
    if not isinstance(contract, dict):
        report["status"] = "insufficient_evidence"
        report["detail_status"] = "thresholds_undefined"
        report["evaluation_status"] = "thresholds_undefined"
        categories["thresholds_undefined"].append("monitoring_boundaries")
        return report

    if (
        not isinstance(max_age_seconds, (int, float))
        or isinstance(max_age_seconds, bool)
        or not math.isfinite(float(max_age_seconds))
        or max_age_seconds <= 0
    ):
        report["quote_validation_errors"] = ["runtime_quote_max_age_invalid"]
        categories["insufficient_data"].append("runtime_quote_max_age_invalid")
        report["status"] = "invalid"
        report["detail_status"] = "runtime_quote_max_age_invalid"
        return report

    evaluation_now = now or datetime.now(timezone.utc)
    if evaluation_now.tzinfo is None or evaluation_now.utcoffset() is None:
        report["quote_validation_errors"] = ["evaluation_clock_invalid"]
        categories["insufficient_data"].append("evaluation_clock_invalid")
        report["status"] = "invalid"
        report["detail_status"] = "evaluation_clock_invalid"
        return report
    evaluation_now = evaluation_now.astimezone(timezone.utc)

    quote_errors, runtime_quote = _validate_runtime_quote(
        quote_snapshot,
        expected_symbol=data["stock_code"],
        expected_currency=_expected_quote_currency(contract),
        now=evaluation_now,
        max_age_seconds=float(max_age_seconds),
    )
    if quote_errors:
        report["quote_validation_errors"] = quote_errors
        categories["insufficient_data"].extend(quote_errors)
        report["status"] = "insufficient_data"
        report["detail_status"] = (
            quote_errors[0] if len(quote_errors) == 1 else "runtime_quote_invalid"
        )
        return report

    report["runtime_quote"] = runtime_quote
    current_price = runtime_quote["current_price"]

    proximity = contract.get("proximity_policy")
    proximity_pct = None
    if isinstance(proximity, dict):
        proximity_pct = float(proximity["value"])

    for boundary in contract.get("boundaries", []):
        boundary_id = boundary["boundary_id"]
        if boundary.get("authority_status") != "user_confirmed":
            categories["insufficient_data"].append(boundary_id)
            continue

        boundary_value = float(boundary["value"])
        operator = boundary["operator"]
        crossed = (
            current_price <= boundary_value
            if operator == "lte"
            else current_price >= boundary_value
        )
        relative_gap = abs(float(current_price) - boundary_value) / boundary_value
        if crossed:
            status = "crossed"
            category = (
                "downside_boundary_crossed"
                if boundary["role"] == "downside_boundary"
                else "upside_boundary_crossed"
            )
        elif proximity_pct is not None and relative_gap <= proximity_pct:
            status = "near"
            category = "near_boundary"
        else:
            status = "not_crossed"
            category = "not_crossed"
            if proximity_pct is None:
                categories["near_rule_undefined"].append(boundary_id)

        categories[category].append(boundary_id)
        report["evaluations"].append(
            {
                "boundary_id": boundary_id,
                "role": boundary["role"],
                "status": status,
                "current_price": current_price,
                "price_as_of": runtime_quote["as_of"],
                "price_source": runtime_quote["source"],
                "market_state": runtime_quote["market_state"],
                "boundary_value": boundary["value"],
                "currency": boundary["currency"],
                "relative_gap": relative_gap,
                "source_locator": boundary["source_locator"],
                "as_of_date": boundary["as_of_date"],
            }
        )

    if categories["insufficient_data"]:
        report["status"] = "insufficient_data"
        report["detail_status"] = "monitoring_boundary_insufficient_data"
        return report

    report["status"] = "ok"
    report["detail_status"] = "complete"
    report["evaluation_status"] = "complete"
    return report


def _cli_failure_report(reason: str, message: str, *, quote_failure: bool) -> dict:
    return {
        "status": "insufficient_data" if quote_failure else "data_error",
        "detail_status": reason,
        "evaluation_status": "insufficient_data",
        "decision_scope": "observation_only",
        "metric": "regular_market_price",
        "categories": {
            **_empty_categories(),
            "insufficient_data": [reason],
        },
        "evaluations": [],
        "research_alerts": [],
        "validation_errors": [] if quote_failure else [message],
        "quote_validation_errors": [reason] if quote_failure else [],
        "runtime_quote": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate non-transactional research monitoring boundaries."
    )
    parser.add_argument("json_path")
    parser.add_argument(
        "--quote-snapshot",
        help=(
            "Path to the runtime quote JSON object containing symbol, current_price, "
            "currency, as_of, source, and market_state. Required when boundaries exist."
        ),
    )
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=DEFAULT_MAX_QUOTE_AGE_SECONDS,
        help="Maximum accepted runtime quote age (default: 259200 seconds).",
    )
    parser.add_argument(
        "--now",
        help="Optional timezone-aware ISO-8601 evaluation time for deterministic replay.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable JSON contract (JSON is also the default output).",
    )
    args = parser.parse_args()

    try:
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = _cli_failure_report(
            "dashboard_unreadable", str(exc), quote_failure=False
        )
    else:
        quote_snapshot = None
        try:
            if args.quote_snapshot:
                quote_snapshot = json.loads(
                    Path(args.quote_snapshot).read_text(encoding="utf-8")
                )
        except (OSError, json.JSONDecodeError) as exc:
            report = _cli_failure_report(
                "runtime_quote_unreadable", str(exc), quote_failure=True
            )
        else:
            evaluation_now = None
            if args.now:
                evaluation_now = _parse_aware_datetime(args.now)
            if args.now and evaluation_now is None:
                report = _cli_failure_report(
                    "evaluation_clock_invalid",
                    "--now must be a timezone-aware ISO-8601 timestamp",
                    quote_failure=True,
                )
            else:
                report = evaluate_watchlist(
                    payload,
                    quote_snapshot,
                    now=evaluation_now,
                    max_age_seconds=args.max_age_seconds,
                )

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    message = json.dumps(report, ensure_ascii=False, indent=2)
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    if report["status"] in {"ok", "not_applicable"}:
        return 0
    if report["status"] == "data_error":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
