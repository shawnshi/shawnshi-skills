#!/usr/bin/env python3
"""Partial portfolio risk diagnostic with an explicit coverage declaration (P1-7).

Why this exists: risk contributions were all-or-nothing — either every active symbol
had a volatility/correlation input (then `risk_diagnostics` computed) or the answer was
`not_calculated`, so a portfolio with two blocked ETF histories produced no risk view
at all.  This tool computes what the *available* histories support, and states exactly
what it covers and what it does not.

Boundaries: it never substitutes a price, never fills a missing symbol with a default
volatility, and never presents the covered-subset result as the portfolio's risk
contribution.  Every excluded symbol carries a reason, and the covered share of
non-cash market value is reported so the reader can size the gap.

Cash is never left as a bare exclusion: base-currency cash is named as carrying no FX
risk, foreign cash is modelled as a separate FX leg when an FX history is supplied, and
otherwise declared unmeasured.  FX is never silently merged into the equity variance —
the code reports the two measured legs and brackets their combination instead.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

DECISION_SCOPE = "advisory"
SCHEMA_VERSION = "pia_partial_risk_diagnostic_v1"
ANNUALIZATION_FACTOR = 252
METHOD_LABELS = ("limited_diagnostic", "not_risk_parity",
                 "not_portfolio_risk_contribution", "coverage_declared")


class RiskError(RuntimeError):
    """An input or coverage failure, optionally carrying per-symbol exclusions."""

    def __init__(self, message: str, exclusions: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.exclusions = exclusions or []


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RiskError(f"{label} not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RiskError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RiskError(f"{label} must be a JSON object")
    return payload


def close_series(path: Path) -> dict[str, float]:
    """Return {date: close} from a yf.py price payload (single record or list)."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else [payload]
    record = next((item for item in records if isinstance(item, dict)
                   and isinstance(item.get("history"), list) and item["history"]), None)
    if record is None:
        raise RiskError(f"history file has no usable records: {path}")
    series: dict[str, float] = {}
    for row in record["history"]:
        if not isinstance(row, dict):
            continue
        day = str(row.get("Date") or "")[:10]
        close = row.get("Close")
        if day and isinstance(close, (int, float)) and not isinstance(close, bool) and close > 0:
            series[day] = float(close)
    if len(series) < 30:
        raise RiskError(f"history file has too few usable closes ({len(series)}): {path}")
    return series


def daily_returns(series: dict[str, float], days: list[str]) -> list[float]:
    values = [series[day] for day in days]
    return [values[index] / values[index - 1] - 1 for index in range(1, len(values))]


def sample_std(values: list[float]) -> float:
    if len(values) < 2:
        raise RiskError("need at least two observations for a volatility")
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def parse_history_arguments(items: list[str]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for item in items:
        symbol, _, raw = item.partition("=")
        symbol = symbol.strip().upper()
        if not symbol or not raw.strip():
            raise RiskError(f"--history expects symbol=path, got {item!r}")
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise RiskError(f"history file not found for {symbol}: {path}")
        mapping[symbol] = path
    return mapping


def parse_fx_arguments(items: list[str]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for item in items:
        pair, _, raw = item.partition("=")
        pair = pair.strip().upper()
        if not pair or not raw.strip():
            raise RiskError(f"--fx-history expects PAIR=path, got {item!r}")
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise RiskError(f"fx history file not found for {pair}: {path}")
        mapping[pair] = path
    return mapping


def cash_currency(row: dict[str, Any]) -> str:
    """Currency of a cash row: the declared one, else the CASH_<CCY> suffix."""

    declared = str(row.get("currency") or "").strip().upper()
    if declared:
        return declared
    return str(row["symbol"]).removeprefix("CASH_").upper()


def compute(weights_payload: dict[str, Any], histories: dict[str, Path],
            *, now: datetime.datetime, fx_histories: dict[str, Path] | None = None,
            base_currency: str = "CNY") -> dict[str, Any]:
    rows = [row for row in weights_payload.get("current_weights") or []
            if isinstance(row, dict) and row.get("symbol")]
    if not rows:
        raise RiskError("weights payload has no current_weights rows")
    market_value = {row["symbol"]: float(row.get("market_value_base") or 0) for row in rows}
    current_weight = {row["symbol"]: float(row.get("current_weight") or 0) for row in rows}
    non_cash = [symbol for symbol in market_value if not symbol.startswith("CASH")]
    non_cash_value = sum(market_value[symbol] for symbol in non_cash)
    if non_cash_value <= 0:
        raise RiskError("non-cash market value is zero; nothing to diagnose")

    excluded: list[dict[str, str]] = []
    series: dict[str, dict[str, float]] = {}
    provenance: list[dict[str, Any]] = []
    for symbol in sorted(non_cash):
        path = histories.get(symbol)
        if path is None:
            excluded.append({"symbol": symbol, "reason": "no_history_supplied"})
            continue
        try:
            series[symbol] = close_series(path)
        except RiskError as exc:
            excluded.append({"symbol": symbol, "reason": f"unusable_history: {exc}"})
            continue
        provenance.append({"symbol": symbol, "file": str(path),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for symbol in sorted(market_value):
        if symbol.startswith("CASH"):
            continue  # classified below, once the base currency is known

    # ---- cash: every row gets a risk treatment, never a bare exclusion -------
    base_currency = (base_currency or "CNY").strip().upper()
    cash_rows = [row for row in rows if str(row["symbol"]).startswith("CASH")]
    fx_series: dict[str, dict[str, float]] = {}
    base_currency_cash: list[dict[str, Any]] = []
    unmeasured_cash: list[dict[str, Any]] = []
    fx_provenance: list[dict[str, Any]] = []
    for row in sorted(cash_rows, key=lambda item: item["symbol"]):
        symbol = str(row["symbol"])
        currency = cash_currency(row)
        value = market_value[symbol]
        entry = {"symbol": symbol, "currency": currency, "value_base": round(value, 2)}
        if currency == base_currency:
            base_currency_cash.append({**entry,
                                       "risk_treatment": "base_currency_cash_carries_no_fx_risk"})
            excluded.append({"symbol": symbol,
                             "reason": "base_currency_cash_excluded_from_equity_risk"})
            continue
        pair = f"{currency}{base_currency}"
        path = (fx_histories or {}).get(pair)
        if path is None:
            unmeasured_cash.append({**entry, "pair": pair,
                                    "reason": f"no_fx_history_supplied_for_{pair}"})
            excluded.append({"symbol": symbol,
                             "reason": f"cash_fx_exposure_unmeasured:{pair}"})
            continue
        try:
            fx_series[symbol] = close_series(path)
        except RiskError as exc:
            unmeasured_cash.append({**entry, "pair": pair,
                                    "reason": f"unusable_fx_history: {exc}"})
            excluded.append({"symbol": symbol,
                             "reason": f"cash_fx_exposure_unmeasured:{pair}"})
            continue
        fx_provenance.append({"symbol": symbol, "pair": pair, "file": str(path),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    covered = sorted(series)
    if len(covered) < 2:
        raise RiskError(f"need at least two usable histories, have {len(covered)}", excluded)
    common_days = sorted(set.intersection(*[set(series[symbol]) for symbol in covered]))
    if len(common_days) < 31:
        raise RiskError(
            f"only {len(common_days)} common observations across the covered set", excluded)

    returns = {symbol: daily_returns(series[symbol], common_days) for symbol in covered}
    annualized_volatility = {symbol: sample_std(returns[symbol]) * math.sqrt(ANNUALIZATION_FACTOR)
                             for symbol in covered}
    correlation: dict[str, dict[str, float]] = {}
    for left in covered:
        correlation[left] = {}
        for right in covered:
            a, b = returns[left], returns[right]
            mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
            covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (len(a) - 1)
            correlation[left][right] = covariance / (sample_std(a) * sample_std(b))

    covered_weight = {symbol: current_weight[symbol] for symbol in covered}
    total_covered_weight = sum(covered_weight.values())
    if total_covered_weight <= 0:
        raise RiskError("covered symbols carry no portfolio weight")
    normalized = {symbol: covered_weight[symbol] / total_covered_weight for symbol in covered}
    covariance_matrix = [[correlation[left][right] * annualized_volatility[left]
                          * annualized_volatility[right] for right in covered] for left in covered]
    marginal = [sum(covariance_matrix[i][j] * normalized[covered[j]] for j in range(len(covered)))
                for i in range(len(covered))]
    portfolio_variance = sum(normalized[covered[i]] * marginal[i] for i in range(len(covered)))
    if portfolio_variance <= 0:
        raise RiskError("covered-subset portfolio variance is not positive")
    contribution = {covered[i]: normalized[covered[i]] * marginal[i] / portfolio_variance
                    for i in range(len(covered))}

    covered_value = sum(market_value[symbol] for symbol in covered)
    total_value = sum(market_value.values())
    cash_value = sum(market_value[str(row["symbol"])] for row in cash_rows)

    # ---- FX legs over the same observation window as the equity subset --------
    fx_legs: list[dict[str, Any]] = []
    for symbol in sorted(fx_series):
        row = next(item for item in cash_rows if str(item["symbol"]) == symbol)
        currency = cash_currency(row)
        pair = f"{currency}{base_currency}"
        value = market_value[symbol]
        shared = [day for day in common_days if day in fx_series[symbol]]
        if len(shared) - 1 < 31:
            unmeasured_cash.append({"symbol": symbol, "currency": currency,
                                    "value_base": round(value, 2), "pair": pair,
                                    "reason": ("fx_window_overlap_too_short: "
                                               f"{len(shared)} shared observations")})
            excluded.append({"symbol": symbol,
                             "reason": f"cash_fx_exposure_unmeasured:{pair}"})
            continue
        fx_returns = daily_returns(fx_series[symbol], shared)
        fx_vol = sample_std(fx_returns) * math.sqrt(ANNUALIZATION_FACTOR)
        share = value / total_value if total_value else 0.0
        fx_legs.append({"symbol": symbol, "currency": currency, "pair": pair,
                        "value_base": round(value, 2),
                        "weight_of_portfolio_value": round(share, 6),
                        "shared_observations": len(shared) - 1,
                        "annualized_fx_volatility": round(fx_vol, 6),
                        "standalone_weighted_volatility": round(share * fx_vol, 6)})
        excluded.append({"symbol": symbol,
                         "reason": "cash_excluded_from_equity_risk_fx_modelled_separately"})

    equity_leg_weight = covered_value / total_value if total_value else 0.0
    equity_leg = equity_leg_weight * math.sqrt(portfolio_variance)
    fx_leg = sum(leg["standalone_weighted_volatility"] for leg in fx_legs)
    measured_uncovered = sorted(set(non_cash) - set(covered))
    combination = {
        "basis": ("only the two measured legs are combined: the covered equity subset "
                  "scaled to its portfolio share, and the sum of the standalone FX legs"),
        "equity_leg": {"weight_of_portfolio_value": round(equity_leg_weight, 6),
                       "annualized_volatility": round(math.sqrt(portfolio_variance), 6),
                       "weighted": round(equity_leg, 6)},
        "fx_leg": {"weighted_sum_of_standalone_legs": round(fx_leg, 6),
                   "leg_count": len(fx_legs)},
        "assumed_zero_correlation_point_estimate": round(
            math.sqrt(equity_leg ** 2 + fx_leg ** 2), 6),
        "correlation_bounds": {"lower": round(abs(equity_leg - fx_leg), 6),
                               "upper": round(equity_leg + fx_leg, 6),
                               "basis": "correlation between the legs in [-1, 1]"},
        "excluded_from_this_combination": measured_uncovered,
        "statement": ("these bounds cover the measured legs only; the uncovered equity "
                      "symbols are not bounded and must not be read as risk-free"),
    }
    equity_covered_share = covered_value / total_value if total_value else 0.0
    equity_uncovered_value = max(non_cash_value - covered_value, 0.0)
    equity_uncovered_share = equity_uncovered_value / total_value if total_value else 0.0
    modelled_cash_value = sum(leg["value_base"] for leg in fx_legs)
    modelled_cash_share = modelled_cash_value / total_value if total_value else 0.0
    base_cash_value = sum(item["value_base"] for item in base_currency_cash)
    base_cash_share = base_cash_value / total_value if total_value else 0.0
    unmeasured_cash_value = sum(item["value_base"] for item in unmeasured_cash)
    unmeasured_cash_share = unmeasured_cash_value / total_value if total_value else 0.0
    # The partition must add up to the whole portfolio: the uncovered equity slice is
    # unmeasured risk, not a silent remainder.
    unmeasured_share = equity_uncovered_share + unmeasured_cash_share
    partition_total = (equity_covered_share + equity_uncovered_share + modelled_cash_share
                       + base_cash_share + unmeasured_cash_share)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "detail_status": "partial_risk_diagnostic_computed",
        "decision_scope": DECISION_SCOPE,
        "generated_at": now.isoformat(),
        "method": {
            "volatility": f"sample standard deviation of daily simple returns x sqrt({ANNUALIZATION_FACTOR})",
            "correlation": "Pearson correlation over the common observation dates",
            "risk_contribution": "component contribution w_i (Sigma w)_i / (w' Sigma w); weights renormalised inside the covered subset",
            "labels": list(METHOD_LABELS),
        },
        "observation_window": {"first": common_days[0], "last": common_days[-1],
                               "common_observations": len(common_days) - 1},
        "coverage": {
            "covered_symbols": covered,
            "covered_count": len(covered),
            "active_non_cash_count": len(non_cash),
            "covered_market_value_base": round(covered_value, 2),
            "non_cash_market_value_base": round(non_cash_value, 2),
            "covered_share_of_non_cash_value": round(covered_value / non_cash_value, 6),
            "excluded_symbols": excluded,
            "statement": ("this is a limited diagnostic over the covered symbols only; it is "
                          "not the portfolio's risk contribution and must not be used as one"),
        },
        "base_currency": base_currency,
        "portfolio_value_base": round(total_value, 2),
        "value_coverage": {
            "equity_covered_share_of_portfolio_value": round(equity_covered_share, 6),
            "equity_uncovered_share_of_portfolio_value": round(equity_uncovered_share, 6),
            "equity_symbols_without_measured_risk": measured_uncovered,
            "fx_modelled_cash_share_of_portfolio_value": round(modelled_cash_share, 6),
            "base_currency_cash_share_of_portfolio_value": round(base_cash_share, 6),
            "unmeasured_cash_share_of_portfolio_value": round(unmeasured_cash_share, 6),
            "unmeasured_share_of_portfolio_value": round(unmeasured_share, 6),
            "partition_total": round(partition_total, 6),
            "statement": ("these shares partition portfolio value into a measured equity "
                          "part, an equity part whose risk is not measured, a modelled FX "
                          "part, base-currency cash, and unmeasured cash"),
        },
        "cash_fx_risk": {
            "legs": fx_legs,
            "base_currency_cash": base_currency_cash,
            "unmeasured_cash": unmeasured_cash,
            "measured_legs_combination": combination,
            "fx_history_provenance": fx_provenance,
            "statement": ("FX risk is reported as separate legs; no joint covariance "
                          "between FX and the equity subset is estimated"),
        },
        "annualized_volatility": {symbol: round(value, 6)
                                  for symbol, value in annualized_volatility.items()},
        "correlation": {left: {right: round(value, 4) for right, value in correlation[left].items()}
                        for left in covered},
        "covered_subset_annualized_volatility": round(math.sqrt(portfolio_variance), 6),
        "risk_contribution_within_subset": {symbol: round(value, 6)
                                            for symbol, value in sorted(contribution.items())},
        "renormalized_weights_within_subset": {symbol: round(value, 6)
                                               for symbol, value in sorted(normalized.items())},
        "history_provenance": provenance,
        "non_executable": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Partial portfolio risk diagnostic with declared coverage.")
    parser.add_argument("--weights-file", required=True)
    parser.add_argument("--history", action="append", default=[],
                        help="symbol=path to a yf.py price payload, repeatable")
    parser.add_argument("--fx-history", action="append", default=[],
                        help="PAIR=path fx payload for foreign-currency cash, e.g. USDCNY=usdcny.json")
    parser.add_argument("--base-currency",
                        help="portfolio base currency; defaults to the weights file's "
                             "base_currency, else CNY")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        weights = load_json(Path(args.weights_file).expanduser().resolve(), "weights file")
        histories = parse_history_arguments(args.history)
        fx_histories = parse_fx_arguments(args.fx_history)
        base_currency = args.base_currency or str(weights.get("base_currency") or "CNY")
        diagnostic = compute(weights, histories, fx_histories=fx_histories,
                             base_currency=base_currency,
                             now=datetime.datetime.now(datetime.timezone.utc))
    except RiskError as exc:
        payload = {"status": "failed", "detail_status": "risk_diagnostic_input_invalid",
                   "decision_scope": DECISION_SCOPE, "errors": [str(exc)]}
        if exc.exclusions:
            # Keep the per-symbol reasons: an empty covered set must still explain itself.
            payload["exclusions"] = exc.exclusions
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3
    if args.out:
        target = Path(args.out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(diagnostic, ensure_ascii=False, indent=2).encode("utf-8")
        target.write_bytes(rendered)
        diagnostic["diagnostic_file"] = str(target)
        diagnostic["diagnostic_sha256"] = hashlib.sha256(rendered).hexdigest()
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
