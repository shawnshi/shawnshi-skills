from __future__ import annotations

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
        return float(value)
    except (TypeError, ValueError):
        if isinstance(value, str):
            match = re.search(r"[-+]?\d*\.\d+|\d+", value)
            if match:
                return float(match.group())
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

    current_price = _to_float(_get_nested(data, ["dashboard", "data_perspective", "price_position", "current_price"]))
    support = _to_float(_get_nested(data, ["dashboard", "data_perspective", "price_position", "support_level"]))
    resistance = _to_float(_get_nested(data, ["dashboard", "data_perspective", "price_position", "resistance_level"]))
    stop_loss = _to_float(_get_nested(data, ["dashboard", "battle_plan", "sniper_points", "stop_loss"]))
    take_profit = _to_float(_get_nested(data, ["dashboard", "battle_plan", "sniper_points", "take_profit"]))
    
    override_flags = _get_nested(data, ["dashboard", "override_gate_flags"]) or {}
    allow_trailing_stop = override_flags.get("allow_trailing_stop") is True
    allow_breakout_buy = override_flags.get("allow_breakout_buy") is True

    position_direction = data.get("position_direction", "long")

    if support is not None and resistance is not None and support > resistance:
        errors.append("support_level cannot be above resistance_level")

    if position_direction == "long":
        if current_price is not None and support is not None and support > current_price:
            if not allow_breakout_buy:
                errors.append("support_level cannot be above current_price")
        if current_price is not None and resistance is not None and resistance < current_price:
            errors.append("resistance_level cannot be below current_price")
        if stop_loss is not None and support is not None and stop_loss > support:
            errors.append("stop_loss should not be above support_level")
        
        atr = _to_float(_get_nested(data, ["dashboard", "data_perspective", "atr_14"]))
        if stop_loss is not None and current_price is not None:
            if not allow_trailing_stop:
                if atr is not None:
                    # Dynamic ATR based stop loss (e.g. 1.0 ATR buffer)
                    if stop_loss > current_price - (0.1 * atr):
                        errors.append(f"stop_loss ({stop_loss}) is too close to current_price ({current_price}) relative to ATR ({atr}). Must be at least 0.1 ATR away.")
                elif stop_loss >= current_price:
                    errors.append("stop_loss must be strictly below current_price for long buy/hold/watch decisions")
        if take_profit is not None and resistance is not None and take_profit < resistance:
            errors.append("take_profit should not be below resistance_level")
    else:  # short
        if current_price is not None and resistance is not None and resistance < current_price:
            if not allow_breakout_buy:
                errors.append("resistance_level cannot be below current_price for short")
        if current_price is not None and support is not None and support > current_price:
            errors.append("support_level cannot be above current_price for short")
        if stop_loss is not None and resistance is not None and stop_loss < resistance:
            errors.append("stop_loss should not be below resistance_level for short")
        if stop_loss is not None and current_price is not None and stop_loss <= current_price:
            if not allow_trailing_stop:
                errors.append("stop_loss must be strictly above current_price for short buy/hold/watch decisions")
        if take_profit is not None and support is not None and take_profit > support:
            errors.append("take_profit should not be above support_level for short")

    confidence_score = _to_float(data.get("confidence_details", {}).get("score"))
    if confidence_score is not None and not (0 <= confidence_score <= 100):
        errors.append("confidence_details.score must be between 0 and 100")

    return errors
