import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PORTFOLIO_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "portfolio_schema.json"


def _as_float(value: Any, field: str, errors: list[str]) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be numeric")
        return None
    if not math.isfinite(parsed):
        errors.append(f"{field} must be finite")
        return None
    return parsed


def analyze_scenarios(portfolio: dict[str, Any], assumptions: dict[str, Any]) -> dict[str, Any]:
    portfolio_schema = json.loads(PORTFOLIO_SCHEMA_PATH.read_text(encoding="utf-8"))
    positions = portfolio.get("positions")
    scenarios = assumptions.get("scenarios")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(positions, list) or not positions:
        errors.append("portfolio.positions must be a non-empty list")
        positions = []
    for field in portfolio_schema["required_top_level"]:
        if portfolio.get(field) in (None, "", []):
            errors.append(f"portfolio missing required field: {field}")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("assumptions.scenarios must be a non-empty list")
        scenarios = []
    if not assumptions.get("base_currency"):
        errors.append("assumptions.base_currency is required")
    elif portfolio.get("base_currency") and assumptions.get("base_currency") != portfolio.get("base_currency"):
        errors.append("assumptions.base_currency must match portfolio.base_currency")

    weights: dict[str, float] = {}
    seen_symbols: set[str] = set()
    for index, position in enumerate(positions):
        if not isinstance(position, dict):
            errors.append(f"positions[{index}] must be an object")
            continue
        missing_position_fields = [
            field
            for field in portfolio_schema["required_position_fields"]
            if position.get(field) in (None, "")
        ]
        if missing_position_fields:
            errors.append(
                f"positions[{index}] missing portfolio schema fields: {', '.join(missing_position_fields)}"
            )
            continue
        symbol = str(position["symbol"])
        if symbol in seen_symbols:
            errors.append(f"duplicate position symbol: {symbol}")
            continue
        seen_symbols.add(symbol)
        quantity = _as_float(position.get("quantity"), f"positions[{index}].quantity", errors)
        avg_cost = _as_float(position.get("avg_cost"), f"positions[{index}].avg_cost", errors)
        weight = _as_float(position.get("current_weight"), f"positions[{index}].current_weight", errors)
        if quantity is not None and quantity <= 0:
            errors.append(f"positions[{index}].quantity must be positive")
        if avg_cost is not None and avg_cost <= 0:
            errors.append(f"positions[{index}].avg_cost must be positive")
        if weight is not None and not (0 < weight <= 1):
            errors.append(f"positions[{index}].current_weight must be positive and at most 1")
        elif weight is not None:
            weights[symbol] = weight
    weight_sum = sum(weights.values())
    if weights and abs(weight_sum - 1.0) > 0.02:
        warnings.append(f"position weights sum to {weight_sum:.4f}, not 1.0")

    if "transaction_cost_bps" not in assumptions or "assumed_turnover" not in assumptions:
        warnings.append("transaction costs are not modeled without transaction_cost_bps and assumed_turnover")
        transaction_cost = None
    else:
        bps = _as_float(assumptions["transaction_cost_bps"], "transaction_cost_bps", errors)
        turnover = _as_float(assumptions["assumed_turnover"], "assumed_turnover", errors)
        if bps is not None and bps < 0:
            errors.append("transaction_cost_bps cannot be negative")
        if turnover is not None and turnover < 0:
            errors.append("assumed_turnover cannot be negative")
        transaction_cost = (
            round(bps / 10000 * turnover, 6)
            if bps is not None and turnover is not None and bps >= 0 and turnover >= 0
            else None
        )

    scenario_results = []
    scenario_names = {
        scenario.get("name") for scenario in scenarios if isinstance(scenario, dict) and scenario.get("name")
    }
    missing_scenarios = sorted({"base", "bull", "bear"} - scenario_names)
    if missing_scenarios:
        errors.append(f"assumptions.scenarios missing required names: {', '.join(missing_scenarios)}")
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict) or not scenario.get("name"):
            errors.append(f"scenarios[{index}] requires name")
            continue
        if not scenario.get("assumption_source"):
            errors.append(f"scenarios[{index}].assumption_source is required")
            continue
        asset_returns = scenario.get("asset_returns")
        if not isinstance(asset_returns, dict):
            errors.append(f"scenarios[{index}].asset_returns must be an object")
            continue
        missing_symbols = sorted(set(weights) - set(asset_returns))
        if missing_symbols:
            errors.append(
                f"scenarios[{index}] missing explicit returns for: {', '.join(missing_symbols)}"
            )
            continue
        contribution: dict[str, float] = {}
        portfolio_return = 0.0
        scenario_valid = True
        for symbol, weight in weights.items():
            assumed_return = _as_float(
                asset_returns.get(symbol), f"scenarios[{index}].asset_returns.{symbol}", errors
            )
            if assumed_return is None:
                scenario_valid = False
                continue
            impact = weight * assumed_return
            contribution[symbol] = round(impact, 6)
            portfolio_return += impact
        if scenario_valid:
            scenario_results.append(
                {
                    "name": scenario["name"],
                    "portfolio_return_before_cost": round(portfolio_return, 6),
                    "portfolio_return_after_cost": (
                        round(portfolio_return - transaction_cost, 6)
                        if transaction_cost is not None
                        else None
                    ),
                    "position_contributions": contribution,
                    "assumption_source": scenario.get("assumption_source"),
                }
            )

    constraints = assumptions.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append("assumptions.constraints must be an object")
        constraints = {}
    violations = []
    max_single_weight = constraints.get("max_single_weight")
    if max_single_weight is not None:
        threshold = _as_float(max_single_weight, "constraints.max_single_weight", errors)
        if threshold is not None and not (0 < threshold <= 1):
            errors.append("constraints.max_single_weight must be greater than 0 and at most 1")
        elif threshold is not None:
            for symbol, weight in weights.items():
                if weight > threshold:
                    violations.append(
                        {"type": "max_single_weight", "symbol": symbol, "value": weight, "limit": threshold}
                    )

    return {
        "valid": not errors,
        "base_currency": assumptions.get("base_currency"),
        "weight_sum": round(weight_sum, 6),
        "scenario_results": scenario_results,
        "constraint_violations": violations,
        "transaction_cost_estimate": transaction_cost,
        "model_boundary": "user-supplied scenarios only; no return forecast or trade action",
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a portfolio using explicit user-supplied scenario returns and constraints."
    )
    parser.add_argument("portfolio_json")
    parser.add_argument("assumptions_json")
    parser.add_argument("--output")
    args = parser.parse_args()
    portfolio = json.loads(Path(args.portfolio_json).read_text(encoding="utf-8"))
    assumptions = json.loads(Path(args.assumptions_json).read_text(encoding="utf-8"))
    result = analyze_scenarios(portfolio, assumptions)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
