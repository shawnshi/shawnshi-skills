from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from ordinary_equity_contract import validate_ordinary_equity


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


def _materially_equal(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(0.01, abs(right) * 1e-9)
    return abs(left - right) <= tolerance


def _validate_etf_math(data: dict) -> list[str]:
    block = data.get("etf_research")
    scenarios = data.get("scenario_analysis")
    if not isinstance(block, dict) or not isinstance(scenarios, dict):
        return ["ETF math requires etf_research and scenario_analysis objects"]
    errors = []
    items = data.get("evidence_items")
    items = items if isinstance(items, list) else []

    def item(index):
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(items) and isinstance(items[index], dict):
            return items[index]
        return {}

    nav_link = block.get("nav")
    nav_item = item(nav_link.get("evidence_index") if isinstance(nav_link, dict) else None)
    nav = _to_float(_get_nested(nav_item, ["etf_observation", "value"]))
    price = _to_float(item(block.get("quote_evidence_index")).get("price"))
    premium = _to_float(block.get("premium_discount"))
    if nav is None or nav <= 0 or price is None or price <= 0 or premium is None:
        errors.append("ETF premium math requires positive NAV/price and finite premium_discount")
    elif not math.isclose(premium, price / nav - 1, rel_tol=1e-9, abs_tol=1e-8):
        errors.append("ETF premium_discount must equal market price / NAV - 1 (ratio)")
    values = {}
    case_assumptions = {}
    for name in ("base", "bull", "bear"):
        case = scenarios.get(name)
        if not isinstance(case, dict):
            errors.append(f"ETF {name} scenario is required")
            continue
        reference = _to_float(case.get("nav_per_unit"))
        result = _to_float(case.get("per_share_value"))
        assumptions = case.get("assumptions")
        assumptions = assumptions if isinstance(assumptions, list) else []
        named = {a.get("name"): a for a in assumptions if isinstance(a, dict) and isinstance(a.get("name"), str)}
        if len(named) != 2 or len(assumptions) != 2 or set(named) != {"index_return", "currency_return"}:
            errors.append(f"ETF {name} requires exactly index_return and currency_return assumptions")
        index_return = _to_float(named.get("index_return", {}).get("value"))
        currency_return = _to_float(named.get("currency_return", {}).get("value"))
        if index_return is None or currency_return is None or index_return <= -1 or currency_return <= -1 or any(a.get("unit") != "ratio" for a in named.values()):
            errors.append(f"ETF {name} return assumptions require finite ratios > -1")
            continue
        if nav is None or reference is None or reference <= 0 or not math.isclose(reference, nav, rel_tol=1e-9, abs_tol=1e-8):
            errors.append(f"ETF {name}.nav_per_unit must equal bound NAV")
            continue
        expected = reference * (1 + index_return) * (1 + currency_return)
        if result is None or not math.isclose(result, expected, rel_tol=1e-9, abs_tol=1e-8):
            errors.append(f"ETF {name}.per_share_value must equal NAV * (1 + index_return) * (1 + currency_return)")
        else:
            values[name] = result
        case_assumptions[name] = named
    if len(values) == 3 and not values["bear"] <= values["base"] <= values["bull"]:
        errors.append("ETF scenario values must satisfy bear <= base <= bull")
    sensitivity = scenarios.get("sensitivity")
    if not isinstance(sensitivity, list) or not sensitivity:
        errors.append("ETF sensitivity is required")
    else:
        for s in sensitivity:
            if not isinstance(s, dict):
                errors.append("ETF sensitivity must be an object")
                continue
            low, base, high = [_to_float(s.get(key)) for key in ("low", "base", "high")]
            parameter = s.get("parameter")
            reference = _to_float(case_assumptions.get("base", {}).get(parameter, {}).get("value")) if isinstance(parameter, str) else None
            if low is None or base is None or high is None or reference is None or s.get("unit") != "ratio" or not low <= base <= high or base != reference:
                errors.append("ETF sensitivity must bracket the base return assumption in ratio units")
    return errors


def _validate_valuation_math(data: dict) -> list[str]:
    scenarios = data.get("scenario_analysis")
    if not isinstance(scenarios, dict) or scenarios.get("valuation_contract_version") not in ("2.0", "3.0"):
        return []

    errors: list[str] = []
    per_share_values: dict[str, float] = {}
    for case_name in ("base", "bull", "bear"):
        case = scenarios.get(case_name)
        if not isinstance(case, dict):
            continue
        prefix = f"scenario_analysis.{case_name}"
        enterprise_value = _to_float(case.get("enterprise_value"))
        net_debt = _to_float(case.get("net_debt"))
        equity_value = _to_float(case.get("equity_value"))
        diluted_shares = _to_float(case.get("diluted_shares"))
        per_share_value = _to_float(case.get("per_share_value"))

        if scenarios.get("valuation_contract_version") == "2.0" and enterprise_value is not None and net_debt is not None and equity_value is not None:
            expected_equity = enterprise_value - net_debt
            if not _materially_equal(equity_value, expected_equity):
                errors.append(
                    f"{prefix}.equity_value is inconsistent with enterprise_value - net_debt"
                )
        if (
            equity_value is not None
            and diluted_shares is not None
            and diluted_shares > 0
            and per_share_value is not None
        ):
            expected_per_share = equity_value / diluted_shares
            if not _materially_equal(per_share_value, expected_per_share):
                errors.append(
                    f"{prefix}.per_share_value is inconsistent with equity_value / diluted_shares"
                )
        if per_share_value is not None:
            per_share_values[case_name] = per_share_value

    if all(name in per_share_values for name in ("bull", "base", "bear")):
        if not (
            per_share_values["bull"] >= per_share_values["base"]
            and per_share_values["base"] >= per_share_values["bear"]
        ):
            errors.append(
                "scenario per_share_value must be monotonic: bull >= base >= bear"
            )

    sensitivity = scenarios.get("sensitivity")
    if isinstance(sensitivity, list):
        for index, item in enumerate(sensitivity):
            if not isinstance(item, dict):
                continue
            low = _to_float(item.get("low"))
            base = _to_float(item.get("base"))
            high = _to_float(item.get("high"))
            if None not in (low, base, high) and not (low <= base <= high):
                errors.append(
                    f"scenario_analysis.sensitivity[{index}] must satisfy low <= base <= high"
                )
    return errors


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

    etf_requested = (
        "etf_research" in data
        or _get_nested(data, ["scenario_analysis", "valuation_contract_version"]) in ("etf_nav1.0", "etf_nav1.1")
    )
    if etf_requested:
        errors.extend(_validate_etf_math(data))
    else:
        errors.extend(_validate_valuation_math(data))
        errors.extend(validate_ordinary_equity(data))
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
