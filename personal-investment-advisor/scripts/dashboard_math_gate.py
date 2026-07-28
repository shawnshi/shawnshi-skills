from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def _get_nested(data: dict, path: list[str], default: Any = None) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


import re

def _to_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        if isinstance(value, str):
            match = re.search(r"[-+]?\d*\.\d+|\d+", value)
            if match:
                parsed = float(match.group())
                return parsed if math.isfinite(parsed) else None
        return None


def _approx_equal(left: float | None, right: float | None, tolerance: float = 0.02) -> bool:
    if left is None or right is None:
        return True
    if right == 0:
        return abs(left - right) <= tolerance
    return abs(left - right) <= max(tolerance, abs(right) * tolerance)


def validate_math_consistency(data: dict) -> list[str]:
    errors: list[str] = []

    portfolio = data.get("portfolio_context", {})
    if isinstance(portfolio, dict) and portfolio.get("has_position"):
        quantity = _to_float(portfolio.get("quantity"))
        avg_cost = _to_float(portfolio.get("avg_cost"))
        current_price = _to_float(portfolio.get("current_price"))
        market_value = _to_float(portfolio.get("market_value"))
        cost_basis = _to_float(portfolio.get("cost_basis"))
        unrealized_pnl = _to_float(portfolio.get("unrealized_pnl"))
        unrealized_pnl_pct = _to_float(portfolio.get("unrealized_pnl_pct"))

        if quantity is not None and current_price is not None and market_value is not None:
            expected_market_value = round(quantity * current_price, 2)
            if not _approx_equal(market_value, expected_market_value):
                errors.append("portfolio_context.market_value is inconsistent with quantity * current_price")

        if quantity is not None and avg_cost is not None and cost_basis is not None:
            expected_cost_basis = round(quantity * avg_cost, 2)
            if not _approx_equal(cost_basis, expected_cost_basis):
                errors.append("portfolio_context.cost_basis is inconsistent with quantity * avg_cost")

        if market_value is not None and cost_basis is not None and unrealized_pnl is not None:
            expected_pnl = round(market_value - cost_basis, 2)
            if not _approx_equal(unrealized_pnl, expected_pnl):
                errors.append("portfolio_context.unrealized_pnl is inconsistent with market_value - cost_basis")

        if current_price is not None and avg_cost not in (None, 0) and unrealized_pnl_pct is not None:
            expected_pnl_pct = round((current_price - avg_cost) / avg_cost, 4)
            if not _approx_equal(unrealized_pnl_pct, expected_pnl_pct, tolerance=0.001):
                errors.append("portfolio_context.unrealized_pnl_pct is inconsistent with current_price and avg_cost")

    support = _to_float(_get_nested(data, ["dashboard", "data_perspective", "price_position", "support_level"]))
    resistance = _to_float(_get_nested(data, ["dashboard", "data_perspective", "price_position", "resistance_level"]))

    if support is not None and resistance is not None and support > resistance:
        errors.append("support_level cannot be above resistance_level")

    confidence_score = _to_float(data.get("confidence_details", {}).get("score"))
    if confidence_score is not None and not (0 <= confidence_score <= 100):
        errors.append("confidence_details.score must be between 0 and 100")

    return errors


def collect_math_warnings(data: dict) -> list[str]:
    return []


def validate_file(path: str) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_math_consistency(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate mathematical consistency in a stock dashboard JSON.")
    parser.add_argument("json_path")
    args = parser.parse_args()
    try:
        errors = validate_file(args.json_path)
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] dashboard math gate could not read input: {exc}")
        return 2
    for warning in collect_math_warnings(payload):
        print(f"[WARN] {warning}")
    if errors:
        print("[FAIL] dashboard math gate blocked output")
        for error in errors:
            print(f"- {error}")
        return 1
    print("[PASS] dashboard math gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
