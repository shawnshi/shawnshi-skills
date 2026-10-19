"""Derive research policies and stress scenarios from goals + portfolio.

Every number here is either (a) a value the user already confirmed in a policy
file or in-session, or (b) the deterministic result of a documented formula over
those values and the current portfolio.  Nothing is a forecast, a probability of
the future, or a validated trading edge.

Derivation rules
----------------
reward_to_risk       = (upside_cost_multiple - 1) / max_single_position_loss
breakeven_hit_rate   = max_loss / ((upside_multiple - 1) + max_loss)
review_horizon_months= ceil(longest position liquidation days / 21) — a review cadence
                       you cannot physically exit faster than is not actionable
min_oos_observations = z95^2*p*(1-p)/(p-breakeven)^2 rounded up to whole review
                       periods, where p is the hit rate of the user's own reviewed
                       advice record
min_net_IR           = round-trip friction (2 * proximity) / annualised volatility
max_drawdown_fraction= user max_single_position_loss
max_annual_turnover  = 12 / review_horizon_months
cost_stress_multiplier = 2 (documented assumption: absorb cost-estimate error)
min_cost_stress_IR   = min_net_IR / cost_stress_multiplier
stress scenarios     = -k * realised volatility over the horizon; k = 1 (mild),
                       2.5 (severe). Mechanical stress, not a prediction.

Missing inputs become explicit gaps.  They are never filled with a silent default.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from statistics import pstdev
from typing import Any

SCHEMA_VERSION = "pia_derived_policy_v1"
Z_95 = 1.96
TRADING_DAYS = 252
STRESS_HORIZON_DAYS = 20
STRESS_SEVERITIES = (("mild", 1.0), ("severe", 2.5))
COST_STRESS_MULTIPLIER = 2.0
DERIVED = "derived_from_goals_and_portfolio"


class DerivationError(ValueError):
    pass


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DerivationError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise DerivationError(f"{label} must be finite")
    return number


def load_goals(positions: dict, risk_policy: dict, goals: dict) -> dict:
    """Combine confirmed policy rules with the user's stated goal inputs."""

    rules = (risk_policy or {}).get("rules") or {}
    try:
        max_weight = _number(rules["max_single_position_weight"]["value"], "max_single_position_weight")
        max_loss = _number(rules["max_single_position_loss"]["value"], "max_single_position_loss")
        upside = _number(rules["upside_cost_multiple"]["value"], "upside_cost_multiple")
    except (KeyError, TypeError) as exc:
        raise DerivationError(f"risk policy is missing a required rule: {exc}") from exc
    proximity = _number(((risk_policy or {}).get("proximity") or {}).get("value"), "proximity.value")
    if not 0 < max_loss < 1 or upside <= 1 or not 0 < max_weight <= 1 or not 0 < proximity < 1:
        raise DerivationError("goal numbers are outside their meaningful range")

    core_cap = _number((goals or {}).get("core_target_cap"), "core_target_cap")
    if not 0 < core_cap < 1:
        raise DerivationError("core_target_cap must be between 0 and 1")

    horizon = (goals or {}).get("review_horizon_months")
    if horizon is not None:
        horizon = _number(horizon, "review_horizon_months")
        if horizon <= 0:
            raise DerivationError("review_horizon_months must be positive")
        horizon_source = "explicit goal input"
    else:
        liquidation = [_number(row.get("days_to_liquidate"), "days_to_liquidate")
                       for row in positions.get("positions") or []
                       if isinstance(row, dict) and row.get("days_to_liquidate") is not None
                       and str(row.get("asset_type")) != "cash"]
        if not liquidation:
            raise DerivationError("no liquidation-day data to ground the review cadence")
        horizon = max(1, math.ceil(max(liquidation) / 21))
        horizon_source = "portfolio liquidation days / 21"

    return {
        "max_single_position_weight": max_weight,
        "max_single_position_loss": max_loss,
        "upside_cost_multiple": upside,
        "proximity": proximity,
        "core_target_cap": core_cap,
        "review_horizon_months": horizon,
        "denominator": (rules.get("max_single_position_weight") or {}).get("denominator"),
        "authority": {
            "risk_policy_confirmed_at": (risk_policy or {}).get("confirmed_at"),
            "risk_policy_locator": (risk_policy or {}).get("source_locator"),
            "core_cap_source": str((goals or {}).get("core_target_cap_source") or "user input"),
            "review_horizon_source": horizon_source,
        },
    }


def derive_bucket_targets(goals: dict, positions: dict) -> dict:
    """core cap from the user; satellite takes the remainder of the same denominator."""

    core = goals["core_target_cap"]
    satellite = round(1.0 - core, 10)
    members: dict[str, list[str]] = {"core": [], "satellite": []}
    cash: list[str] = []
    unassigned: list[str] = []
    for row in positions.get("positions") or []:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        symbol = str(row["symbol"])
        quantity = row.get("quantity")
        if isinstance(quantity, (int, float)) and quantity <= 0:
            continue
        if str(row.get("asset_type")) == "cash":
            cash.append(symbol)
            continue
        bucket = row.get("allocation_bucket")
        if bucket in members:
            members[bucket].append(symbol)
        else:
            unassigned.append(symbol)
    if unassigned:
        raise DerivationError("non-cash positions without a bucket: " + ", ".join(sorted(unassigned)))
    return {
        "schema_version": "pia_inverse_volatility_policy_v1",
        "experiment": "inverse_volatility_allocation",
        "decision_scope": "research_only",
        "bucket_targets": {"core": core, "satellite": satellite},
        "bucket_members": members,
        "denominator": "active_non_cash_market_value",
        "excluded_policy_symbols": cash,
        "authority_status": DERIVED,
        "provenance": {"core_cap": goals["authority"]["core_cap_source"],
                       "rule": "satellite = 1 - core_cap on the declared denominator"},
    }


def derive_alpha_policy(goals: dict, calibration: dict | None, annual_vol: float | None,
                        round_trip_cost_bps: float | None = None) -> dict:
    max_loss = goals["max_single_position_loss"]
    upside = goals["upside_cost_multiple"]
    proximity = goals["proximity"]
    review_months = goals["review_horizon_months"]
    reward_to_risk = (upside - 1) / max_loss
    breakeven = max_loss / ((upside - 1) + max_loss)

    gaps: list[str] = []
    if annual_vol is None or annual_vol <= 0:
        gaps.append("annualised volatility unavailable: information-ratio floors underived")
        min_ir = None
        min_stress_ir = None
    else:
        min_ir = round(2 * proximity / annual_vol, 4)
        min_stress_ir = round(min_ir / COST_STRESS_MULTIPLIER, 4)

    hit_rate = None
    if isinstance(calibration, dict):
        raw_hit = calibration.get("hit_rate")
        if isinstance(raw_hit, (int, float)) and not isinstance(raw_hit, bool):
            hit_rate = float(raw_hit)
    else:
        gaps.append("no reviewed advice record: sample size left underived")

    if hit_rate is None:
        min_obs = None
    elif not (breakeven < hit_rate < 1):
        gaps.append("hit rate at or below break-even: no positive edge to size")
        min_obs = None
    else:
        required = (Z_95 ** 2) * hit_rate * (1 - hit_rate) / ((hit_rate - breakeven) ** 2)
        min_obs = int(math.ceil(required / review_months / 4.0) * 4 * review_months)
        min_obs = max(min_obs, int(review_months * 12))

    promotion = {
        "schema_version": "pia_alpha_promotion_policy_v1",
        "min_oos_observations": min_obs,
        "min_net_information_ratio": min_ir,
        "min_deflated_sharpe_probability": 0.95,
        "max_probability_backtest_overfitting": 0.5,
        "max_drawdown_fraction": max_loss,
        "max_annual_turnover": round(12.0 / review_months, 4),
        "cost_stress_multiplier": COST_STRESS_MULTIPLIER,
        "min_cost_stress_information_ratio": min_stress_ir,
        "pbo_block_count": 16,
        "authority_status": DERIVED,
        "basis": {
            "reward_to_risk": round(reward_to_risk, 4),
            "breakeven_hit_rate": round(breakeven, 6),
            "observed_hit_rate": hit_rate,
            "review_horizon_months": review_months,
            "min_oos_observations": "z95^2*p*(1-p)/(p-breakeven)^2 rounded up to review periods",
            "min_net_information_ratio": "2*proximity/annual_vol",
            "min_deflated_sharpe_probability": "fixed 0.95 confidence convention",
            "max_probability_backtest_overfitting": "fixed 0.5 acceptance convention",
            "max_drawdown_fraction": "user max_single_position_loss",
            "max_annual_turnover": "12/review_horizon_months",
            "cost_stress_multiplier": "documented assumption: double the cost estimate",
            "pbo_block_count": "fixed 16 CSCV block convention",
        },
        "gaps": gaps,
    }
    if round_trip_cost_bps is None:
        minimum_benefit = None
        gaps.append("no cost snapshot: minimum net expected benefit underived "
                    "(a zero-cost assumption would be invented)")
        cost_basis: dict = {"round_trip_cost_bps": None}
    else:
        cost_bps = _number(round_trip_cost_bps, "round_trip_cost_bps")
        if cost_bps < 0:
            raise DerivationError("round_trip_cost_bps cannot be negative")
        minimum_benefit = round(2 * proximity + cost_bps / 10000.0, 6)
        cost_basis = {"round_trip_cost_bps": cost_bps,
                      "formula": "2 * no_trade_band + round_trip_cost_bps/10000"}
    rebalance = {
        "schema_version": "pia_rebalance_proposal_policy_v1",
        "decision_scope": "research_only",
        "no_trade_band": proximity,
        "minimum_net_expected_benefit": minimum_benefit,
        "review_horizon_days": int(round(21 * review_months)),
        "authority_status": DERIVED,
        "basis": {"no_trade_band": "user proximity band", **cost_basis},
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "authority_status": DERIVED,
        "promotion_policy": promotion,
        "rebalance_policy": rebalance,
        "gaps": gaps,
        "limitations": [
            "a derived threshold is not evidence that any signal clears it",
            "derived values encode the user's stated goals, not validated alpha",
        ],
    }


def _log_returns(closes: list) -> list:
    values = [_number(value, "close") for value in closes]
    if len(values) < 30:
        raise DerivationError("at least 30 closes are required for a volatility estimate")
    if any(value <= 0 for value in values):
        raise DerivationError("closes must be positive")
    return [math.log(values[index] / values[index - 1]) for index in range(1, len(values))]


def _annual_vol(closes: list) -> float:
    return pstdev(_log_returns(closes)) * math.sqrt(TRADING_DAYS)


def derive_stress_scenarios(goals: dict, portfolio: dict, series: dict,
                            fx_series: dict | None = None) -> dict:
    horizon_sigma = math.sqrt(STRESS_HORIZON_DAYS)
    fx_series = fx_series or {}
    weights = portfolio.get("weights") or {}
    currency = {str(row.get("symbol")): str(row.get("currency") or "")
                for row in portfolio.get("positions") or [] if isinstance(row, dict)}
    cash = {str(row.get("symbol")) for row in portfolio.get("positions") or []
            if isinstance(row, dict) and str(row.get("asset_type")) == "cash"}
    scenarios = {name: {} for name, _ in STRESS_SEVERITIES}
    gaps: list[str] = []
    for symbol, weight in weights.items():
        if symbol in cash or abs(float(weight)) <= 0:
            continue
        closes = (series.get(symbol) or {}).get("closes")
        if not closes:
            gaps.append(f"{symbol}: no history, scenario return not derived")
            continue
        try:
            local_shock = -_annual_vol(closes) / math.sqrt(TRADING_DAYS) * horizon_sigma
        except DerivationError as exc:
            gaps.append(f"{symbol}: {exc}")
            continue
        fx_shock = 0.0
        if currency.get(symbol) not in ("", "CNY"):
            pair = (series.get(symbol) or {}).get("fx_pair")
            closes_fx = (fx_series.get(pair) or {}).get("closes") if pair else None
            if closes_fx:
                try:
                    fx_shock = -_annual_vol(closes_fx) / math.sqrt(TRADING_DAYS) * horizon_sigma
                except DerivationError as exc:
                    gaps.append(f"{symbol}: FX history unusable ({exc})")
                    fx_shock = 0.0
            else:
                gaps.append(f"{symbol}: no FX history, currency shock not modelled")
        for name, multiple in STRESS_SEVERITIES:
            scenarios[name][symbol] = round(
                (1 + multiple * local_shock) * (1 + multiple * fx_shock) - 1, 6)
    assumptions = {
        "schema_version": "pia_scenario_assumptions_v1",
        "base_currency": portfolio.get("base_currency") or "CNY",
        "horizon_days": STRESS_HORIZON_DAYS,
        "scenarios": [
            {"name": name,
             "assumption_source": (f"mechanical stress: {multiple} x realised annualised "
                                   "volatility over horizon_days; not a forecast"),
             "asset_returns": scenarios[name]}
            for name, multiple in STRESS_SEVERITIES
        ],
    }
    # Per-asset shocks are applied simultaneously, so the weighted sum is already the
    # co-moving case.  The quadrature figure answers a different question: what the
    # same shocks would cost if the correlations were zero.  Reporting only the second
    # number would understate a concentrated, correlated book.
    portfolio_block: dict[str, Any] = {"basis": "weighted sum of covered symbols"}
    for name, multiple in STRESS_SEVERITIES:
        returns = scenarios[name]
        covered = [symbol for symbol in returns if symbol in weights]
        correlated = sum(float(weights[symbol]) * returns[symbol] for symbol in covered)
        diversified = math.sqrt(sum((float(weights[symbol]) * returns[symbol]) ** 2
                                    for symbol in covered)) * (1 if multiple > 0 else 1)
        portfolio_block[f"{name}_correlated_loss"] = round(correlated, 6)
        portfolio_block[f"{name}_diversified_loss"] = round(-diversified, 6)
    portfolio_block["note"] = ("correlated assumes every covered asset realises its shock at "
                               "once; diversified assumes zero correlation. Neither is a "
                               "probability or a maximum loss.")
    portfolio_block["covered_symbols"] = sorted(
        symbol for symbol in weights if symbol in scenarios[STRESS_SEVERITIES[0][0]])
    return {
        "assumptions": assumptions,
        "portfolio": portfolio_block,
        "gaps": gaps,
        "authority_status": DERIVED,
        "limitations": [
            "sigma scaling assumes the recent sample describes the stress; fat tails are not modelled",
            "scenario losses are not maximum losses and carry no probability",
        ],
    }


def derive_all(positions: dict, risk_policy: dict, weights: dict, calibration: dict | None,
               series: dict, fx_series: dict | None = None, goals: dict | None = None) -> dict:
    goals = load_goals(positions, risk_policy, goals or {})
    portfolio = {"weights": weights, "positions": positions.get("positions"),
                 "base_currency": positions.get("base_currency")}
    covered = {symbol: _annual_vol((series.get(symbol) or {}).get("closes"))
               for symbol in weights if (series.get(symbol) or {}).get("closes")}
    total = sum(abs(float(weights[symbol])) for symbol in covered)
    annual_vol = (sum(abs(float(weights[symbol])) * covered[symbol] for symbol in covered) / total
                  if total > 0 else None)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": date.today().isoformat(),
        "authority_status": DERIVED,
        "goals": goals,
        "bucket_policy": derive_bucket_targets(goals, positions),
        "alpha_policy": derive_alpha_policy(goals, calibration, annual_vol),
        "stress": derive_stress_scenarios(goals, portfolio, series, fx_series),
        "not_an_order": "derived policies gate research; they never place or size an order",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive research policies and stress scenarios.")
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--risk-policy", required=True)
    parser.add_argument("--weights-file", required=True)
    parser.add_argument("--series-file", required=True)
    parser.add_argument("--goals-file")
    parser.add_argument("--calibration-file")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    def read(path: str) -> Any:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def weight_map(document: Any) -> dict:
        """Accept the native weights artifact or a plain symbol -> weight map."""
        if isinstance(document, dict) and isinstance(document.get("current_weights"), list):
            return {str(row["symbol"]).upper(): float(row["current_weight"])
                    for row in document["current_weights"]
                    if isinstance(row, dict) and row.get("symbol") is not None
                    and isinstance(row.get("current_weight"), (int, float))}
        if isinstance(document, dict) and isinstance(document.get("weights"), dict):
            return {str(key).upper(): float(value)
                    for key, value in document["weights"].items()}
        if isinstance(document, dict):
            return {str(key).upper(): float(value) for key, value in document.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)}
        raise DerivationError("weights file has an unsupported shape")

    series_document = read(args.series_file)
    result = derive_all(
        read(args.positions_file), read(args.risk_policy),
        weight_map(read(args.weights_file)),
        read(args.calibration_file) if args.calibration_file else None,
        series_document.get("series") or series_document,
        series_document.get("fx"),
        read(args.goals_file) if args.goals_file else None)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    gaps = result["alpha_policy"]["gaps"] + result["stress"]["gaps"]
    print(json.dumps({"status": "derived", "out": args.out, "gaps": gaps,
                      "authority_status": result["authority_status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
