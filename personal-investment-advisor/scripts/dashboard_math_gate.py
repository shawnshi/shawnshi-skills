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


def _to_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _approx_equal(left: float | None, right: float | None, tolerance: float = 0.01) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance + 1e-12


def validate_math_consistency(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["dashboard root must be an object"]

    portfolio = data.get("portfolio_context", {})
    if portfolio is not None and not isinstance(portfolio, dict):
        errors.append("portfolio_context must be an object when provided")
    if isinstance(portfolio, dict) and portfolio.get("has_position"):
        raw_numeric_fields = {
            "quantity": portfolio.get("quantity"),
            "avg_cost": portfolio.get("avg_cost"),
            "current_price": portfolio.get("current_price"),
            "market_value": portfolio.get("market_value"),
            "cost_basis": portfolio.get("cost_basis"),
            "unrealized_pnl": portfolio.get("unrealized_pnl"),
            "unrealized_pnl_pct": portfolio.get("unrealized_pnl_pct"),
            "fx_rate_to_base": portfolio.get("fx_rate_to_base"),
        }
        values: dict[str, float | None] = {}
        for field, raw_value in raw_numeric_fields.items():
            parsed = _to_float(raw_value)
            values[field] = parsed
            if parsed is None:
                errors.append(
                    f"portfolio_context.{field} must be a finite JSON number"
                )

        quantity = values["quantity"]
        avg_cost = values["avg_cost"]
        current_price = values["current_price"]
        market_value = values["market_value"]
        cost_basis = values["cost_basis"]
        unrealized_pnl = values["unrealized_pnl"]
        unrealized_pnl_pct = values["unrealized_pnl_pct"]
        fx_rate = values["fx_rate_to_base"]

        for field, value in {
            "quantity": quantity,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "fx_rate_to_base": fx_rate,
        }.items():
            if value is not None and value <= 0:
                errors.append(f"portfolio_context.{field} must be positive")
        for field, value in {
            "market_value": market_value,
            "cost_basis": cost_basis,
        }.items():
            if value is not None and value < 0:
                errors.append(f"portfolio_context.{field} cannot be negative")

        if (
            quantity is not None
            and current_price is not None
            and market_value is not None
            and fx_rate is not None
        ):
            expected_market_value = round(quantity * current_price * fx_rate, 2)
            if not _approx_equal(market_value, expected_market_value):
                errors.append(
                    "portfolio_context.market_value is inconsistent with "
                    "quantity * current_price * fx_rate_to_base"
                )

        if (
            quantity is not None
            and avg_cost is not None
            and cost_basis is not None
            and fx_rate is not None
        ):
            expected_cost_basis = round(quantity * avg_cost * fx_rate, 2)
            if not _approx_equal(cost_basis, expected_cost_basis):
                errors.append(
                    "portfolio_context.cost_basis is inconsistent with "
                    "quantity * avg_cost * fx_rate_to_base"
                )

        if market_value is not None and cost_basis is not None and unrealized_pnl is not None:
            expected_pnl = round(market_value - cost_basis, 2)
            if not _approx_equal(unrealized_pnl, expected_pnl):
                errors.append("portfolio_context.unrealized_pnl is inconsistent with market_value - cost_basis")

        if current_price is not None and avg_cost not in (None, 0) and unrealized_pnl_pct is not None:
            expected_pnl_pct = round((current_price - avg_cost) / avg_cost, 4)
            if not _approx_equal(unrealized_pnl_pct, expected_pnl_pct, tolerance=0.0001):
                errors.append("portfolio_context.unrealized_pnl_pct is inconsistent with current_price and avg_cost")

    raw_support = _get_nested(data, ["dashboard", "data_perspective", "price_position", "support_level"])
    raw_resistance = _get_nested(data, ["dashboard", "data_perspective", "price_position", "resistance_level"])
    support = _to_float(raw_support)
    resistance = _to_float(raw_resistance)

    if raw_support not in (None, "", "N/A") and support is None:
        errors.append("support_level must be a finite JSON number when provided")
    if raw_resistance not in (None, "", "N/A") and resistance is None:
        errors.append("resistance_level must be a finite JSON number when provided")

    if support is not None and resistance is not None and support > resistance:
        errors.append("support_level cannot be above resistance_level")

    confidence_details = data.get("confidence_details", {})
    if not isinstance(confidence_details, dict):
        errors.append("confidence_details must be an object")
        confidence_details = {}
    raw_confidence_score = confidence_details.get("score")
    confidence_score = _to_float(raw_confidence_score)
    if raw_confidence_score not in (None, "", "N/A") and confidence_score is None:
        errors.append("confidence_details.score must be a finite JSON number")
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable JSON contract (JSON is also the default output).",
    )
    args = parser.parse_args()
    try:
        errors = validate_file(args.json_path)
        payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report = {
            "status": "data_error",
            "detail_status": "dashboard_unreadable",
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    warnings = collect_math_warnings(payload)
    if errors:
        report = {
            "status": "invalid",
            "detail_status": "math_contract_invalid",
            "valid": False,
            "errors": errors,
            "warnings": warnings,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    report = {
        "status": "ok",
        "detail_status": "math_contract_valid",
        "valid": True,
        "errors": [],
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
