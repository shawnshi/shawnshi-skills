"""Offline feasibility check for user-supplied A-share terms; never submits orders."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from instrument_gate import validate_instrument
from source_timing_contract import aware
from market_calendar import CalendarError, is_closed, load_table

VERSION = "pia_cn_actionability_v1"
MAX_BYTES = 1024 * 1024
SHANGHAI = ZoneInfo("Asia/Shanghai")


def finite(value: Any, *, positive: bool = False) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (not positive or value > 0)


def evaluate(data: Any, *, now: datetime | None = None, holiday_calendar_file: Path | None = None) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema_version") != VERSION:
        return {"status": "invalid_input", "errors": [f"schema_version must be {VERSION}"]}
    now = now or datetime.now(SHANGHAI)
    if now.tzinfo is None or now.utcoffset() is None:
        return {"status": "invalid_input", "errors": ["now must be timezone-aware"]}
    errors: list[str] = []
    instrument, quote, rules, terms = (data.get(k) for k in ("instrument", "quote", "rules", "terms"))
    if not isinstance(instrument, dict) or instrument.get("market") != "CN" or instrument.get("asset_type") != "stock" or instrument.get("currency") != "CNY" or not isinstance(instrument.get("symbol"), str) or not instrument["symbol"].strip() or instrument.get("exchange") not in ("SSE", "SZSE", "BSE"):
        errors.append("instrument must identify CN stock and CNY currency")
    else:
        identity = validate_instrument(instrument["symbol"], "CN", "stock", "CNY")
        expected = {"SS": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(instrument["symbol"].rsplit(".", 1)[-1])
        if not identity["valid"] or identity["normalized_symbol"] != instrument["symbol"] or instrument["exchange"] != expected:
            errors.append("instrument requires canonical symbol and matching exchange")
    if errors:
        return {"status": "invalid_input", "errors": errors}
    if holiday_calendar_file is not None:
        try:
            table = load_table(Path(holiday_calendar_file))
            exchange = instrument["exchange"]
            current_day = now.astimezone(SHANGHAI).date()
            official_sources = [source for source in table["sources"] if isinstance(source, dict) and source.get("kind") == "official_exchange_closure_notice" and source.get("market") == exchange]
            if not official_sources or str(current_day.year) not in table["markets"].get(exchange, {}):
                raise CalendarError("matching official exchange/year closure notice is required")
            if is_closed(table, exchange, current_day):
                return {"status": "market_closed", "detail_status": "verified_exchange_calendar_closed", "actionability": "not_actionable", "symbol": instrument["symbol"], "trading_date": current_day.isoformat(), "calendar_source_locators": [source["locator"] for source in official_sources], "limitations": ["Regular exchange closure only; this does not verify exceptional suspensions or instrument-level trading status."]}
        except (CalendarError, OSError, ValueError) as exc:
            return {"status": "invalid_input", "errors": [f"holiday_calendar_invalid: {exc}"]}
    if not isinstance(quote, dict) or quote.get("market_state") != "REGULAR" or not isinstance(quote.get("source_locator"), str) or not quote["source_locator"].startswith("https://") or quote.get("symbol") != instrument.get("symbol") or not isinstance(quote.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", quote["content_sha256"]) or not finite(quote.get("price_cny"), positive=True) or not finite(quote.get("volume_shares")) or quote.get("volume_shares", -1) < 0:
        errors.append("quote requires REGULAR state, sourced positive price and nonnegative volume")
    if not isinstance(rules, dict) or not isinstance(rules.get("source_locator"), str) or not rules["source_locator"].startswith("https://") or not isinstance(rules.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", rules["content_sha256"]) or rules.get("trading_allowed") is not True or rules.get("exchange") != instrument.get("exchange") or rules.get("symbol") != instrument.get("symbol"):
        errors.append("rules require source hash, exchange and trading_allowed=true")
    if not isinstance(terms, dict) or terms.get("side") not in ("buy", "sell") or type(terms.get("quantity")) is not int or terms["quantity"] <= 0 or not finite(terms.get("price_cny"), positive=True):
        errors.append("terms require buy/sell, positive integer quantity and price")
    if errors:
        return {"status": "invalid_input", "errors": errors}
    try:
        observed = aware(quote.get("as_of"))
        retrieved = aware(quote.get("retrieved_at"))
        rule_retrieved = aware(rules.get("retrieved_at"))
        current = now.astimezone(SHANGHAI)
        if current.weekday() >= 5 or rules.get("trading_date") != current.date().isoformat() or observed.astimezone(SHANGHAI).date() != current.date():
            errors.append("quote and rules must cover current Shanghai trading day")
        if not observed <= retrieved <= now.astimezone(observed.tzinfo) or not rule_retrieved <= now.astimezone(rule_retrieved.tzinfo) or now.astimezone(observed.tzinfo) - observed > timedelta(seconds=900):
            errors.append("quote or rule time is future, stale or inconsistent")
    except (TypeError, ValueError, AttributeError):
        errors.append("quote and rules require timezone-aware seconds-level timestamps")
    lower, upper = rules.get("lower_limit_cny"), rules.get("upper_limit_cny")
    if lower is None or upper is None:
        if lower is not None or upper is not None or not isinstance(rules.get("no_price_limit_reason"), str) or not rules["no_price_limit_reason"].strip():
            errors.append("price limits must both be numeric or both absent with explicit official reason")
    elif not finite(lower, positive=True) or not finite(upper, positive=True) or lower > upper or not lower <= terms["price_cny"] <= upper:
        errors.append("requested price outside valid price limit")
    lot, step = rules.get("minimum_buy_lot"), rules.get("buy_increment")
    if type(lot) is not int or type(step) is not int or lot <= 0 or step <= 0:
        errors.append("minimum_buy_lot and buy_increment must be positive integers")
    elif terms["side"] == "buy" and (terms["quantity"] < lot or (terms["quantity"] - lot) % step != 0):
        errors.append("buy quantity violates sourced lot rules")
    available = data.get("available_sell_quantity")
    if terms["side"] == "sell" and (type(available) is not int or available < terms["quantity"]):
        errors.append("sell quantity exceeds confirmed currently sellable shares")
    participation = data.get("max_volume_participation")
    if not finite(participation) or not 0 < participation <= 1 or terms["quantity"] > quote["volume_shares"] * participation:
        errors.append("volume participation missing or exceeded")
    costs = data.get("cost_bps")
    if not isinstance(costs, dict) or any(not finite(costs.get(key)) or costs[key] < 0 for key in ("commission", "spread", "impact", "sell_tax")):
        errors.append("explicit nonnegative commission, spread, impact and sell_tax bps required")
        total_cost = None
    else:
        total_cost = sum(costs[key] for key in ("commission", "spread", "impact")) + (costs["sell_tax"] if terms["side"] == "sell" else 0)
    if terms["side"] == "buy":
        cash = data.get("available_cash_cny")
        if not finite(cash) or cash < 0 or total_cost is None or cash < terms["quantity"] * terms["price_cny"] * (1 + total_cost / 10000):
            errors.append("available cash does not cover notional and estimated costs")
    if errors:
        return {"status": "insufficient_evidence", "errors": errors}
    return {"status": "complete", "detail_status": "input_terms_feasible_under_supplied_snapshots", "estimated_cost_bps": total_cost, "actionability": "human_review_required_no_order", "limitations": ["Supplied exchange rules, source authenticity, sellable quantity, quotes, liquidity and available cash require independent confirmation; market impact is an estimate."]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline A-share proposed-term feasibility gate")
    parser.add_argument("assessment", type=Path)
    parser.add_argument("--holiday-calendar-file", type=Path, help="Reverify official exchange closure before assessing same-day terms")
    args = parser.parse_args()
    try:
        with args.assessment.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input_size_limit")
        result = evaluate(json.loads(raw.decode("utf-8")), holiday_calendar_file=args.holiday_calendar_file)
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "invalid_input", "errors": [f"assessment unreadable: {type(exc).__name__}: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    return {"complete": 0, "insufficient_evidence": 2, "market_closed": 2}.get(result["status"], 3)


if __name__ == "__main__":
    sys.exit(main())
