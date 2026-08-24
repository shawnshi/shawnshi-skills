"""Construct read-only ERC and robust active research portfolios offline."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any

import numpy as np

from active_research_contract import (
    base_report,
    canonical_sha256,
    fail_report,
    finite_number,
    parse_aware_iso,
    positive_integer,
    read_json,
    valid_sha256,
    valid_source_locator,
    utc,
)


SCHEMA_VERSION = "pia_active_portfolio_construction_v1"
POLICY_SCHEMA_VERSION = "pia_active_construction_policy_v1"
SCAN_SCHEMA_VERSION = "pia_active_alpha_scan_v1"


def _weight_map(value: Any, symbols: list[str], label: str) -> tuple[dict[str, float], list[str]]:
    errors: list[str] = []
    if not isinstance(value, dict) or set(value) != set(symbols):
        return {}, [f"{label} keys must exactly match scan symbols"]
    parsed: dict[str, float] = {}
    for symbol in symbols:
        number = finite_number(value.get(symbol))
        if number is None:
            errors.append(f"{label}.{symbol} must be finite")
        else:
            parsed[symbol] = number
    return parsed, errors


def _validate_policy(policy: Any, symbols: list[str], as_of: Any) -> list[str]:
    if not isinstance(policy, dict):
        return ["construction policy root must be an object"]
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"policy.schema_version must equal {POLICY_SCHEMA_VERSION}")
    if policy.get("decision_scope") != "research_only":
        errors.append("policy.decision_scope must equal research_only")
    policy_as_of = parse_aware_iso(policy.get("as_of"))
    scan_as_of = parse_aware_iso(as_of)
    if policy_as_of is None:
        errors.append("policy.as_of must be a timezone-aware ISO datetime")
    elif scan_as_of is not None and utc(policy_as_of) != utc(scan_as_of):
        errors.append("policy.as_of must exactly match scan as_of")
    if policy.get("symbols") != symbols:
        errors.append("policy.symbols must exactly match scan ranking order")

    current, current_errors = _weight_map(policy.get("current_weights"), symbols, "current_weights")
    errors.extend(current_errors)
    budgets, budget_errors = _weight_map(policy.get("risk_budgets"), symbols, "risk_budgets")
    errors.extend(budget_errors)
    minimum, minimum_errors = _weight_map(policy.get("minimum_weights"), symbols, "minimum_weights")
    errors.extend(minimum_errors)
    maximum, maximum_errors = _weight_map(policy.get("maximum_weights"), symbols, "maximum_weights")
    errors.extend(maximum_errors)
    if not current_errors:
        if any(value < 0 for value in current.values()) or abs(sum(current.values()) - 1.0) > 1e-8:
            errors.append("current_weights must be non-negative and sum to 1.0")
    if not budget_errors:
        if any(value <= 0 for value in budgets.values()) or abs(sum(budgets.values()) - 1.0) > 1e-8:
            errors.append("risk_budgets must be positive and sum to 1.0")
    if not minimum_errors and not maximum_errors:
        if any(minimum[symbol] < 0 or maximum[symbol] > 1 or minimum[symbol] > maximum[symbol] for symbol in symbols):
            errors.append("minimum_weights and maximum_weights must satisfy 0 <= min <= max <= 1")
        if sum(minimum.values()) > 1.0 + 1e-8 or sum(maximum.values()) < 1.0 - 1e-8:
            errors.append("weight bounds must admit a fully invested portfolio")

    for key, lower, strict in (
        ("risk_aversion", 0.0, True),
        ("step_size", 0.0, True),
        ("tolerance", 0.0, True),
        ("transaction_cost_bps", 0.0, False),
        ("max_one_way_turnover", 0.0, False),
        ("max_trade_weight", 0.0, False),
    ):
        number = finite_number(policy.get(key))
        if number is None or (number <= lower if strict else number < lower):
            errors.append(f"policy.{key} must be {'positive' if strict else 'non-negative'} and finite")
        elif key in {"max_one_way_turnover", "max_trade_weight"} and number > 1:
            errors.append(f"policy.{key} must not exceed 1.0")
    maximum_iterations = positive_integer(policy.get("max_iterations"))
    if maximum_iterations is None or maximum_iterations > 100_000:
        errors.append("policy.max_iterations must be an integer from 1 to 100000")

    covariance = policy.get("covariance")
    if not isinstance(covariance, dict):
        errors.append("policy.covariance must be an object")
    else:
        if covariance.get("symbols") != symbols:
            errors.append("policy.covariance.symbols must exactly match scan ranking order")
        matrix = covariance.get("matrix")
        if not isinstance(matrix, list) or len(matrix) != len(symbols) or any(
            not isinstance(row, list) or len(row) != len(symbols) for row in matrix
        ):
            errors.append("policy.covariance.matrix must be a square symbol-aligned matrix")
        elif any(finite_number(item) is None for row in matrix for item in row):
            errors.append("policy.covariance.matrix must contain only finite numbers")
        if positive_integer(covariance.get("observation_count"), minimum=2) is None:
            errors.append("policy.covariance.observation_count must be an integer >= 2")
        window_start = parse_aware_iso(covariance.get("window_start"))
        window_end = parse_aware_iso(covariance.get("window_end"))
        covariance_as_of = parse_aware_iso(covariance.get("as_of"))
        if window_start is None or window_end is None or covariance_as_of is None:
            errors.append("covariance window_start, window_end, and as_of must be timezone-aware")
        elif not utc(window_start) <= utc(window_end) <= utc(covariance_as_of):
            errors.append("covariance timestamps must satisfy window_start <= window_end <= as_of")
        elif policy_as_of is not None and utc(covariance_as_of) > utc(policy_as_of):
            errors.append("covariance.as_of cannot be after policy.as_of")
        if not valid_source_locator(covariance.get("source_locator")):
            errors.append("covariance.source_locator must be a non-test public or dataset locator")
        if not valid_sha256(covariance.get("content_sha256")):
            errors.append("covariance.content_sha256 must be a lowercase SHA-256")
    cost_evidence = policy.get("cost_evidence")
    if not isinstance(cost_evidence, dict):
        errors.append("policy.cost_evidence must be an object")
    else:
        if not valid_source_locator(cost_evidence.get("source_locator")):
            errors.append("cost_evidence.source_locator must be a non-test public or dataset locator")
        if not valid_sha256(cost_evidence.get("content_sha256")):
            errors.append("cost_evidence.content_sha256 must be a lowercase SHA-256")
        observed_at = parse_aware_iso(cost_evidence.get("observed_at"))
        if observed_at is None:
            errors.append("cost_evidence.observed_at must be timezone-aware")
        elif policy_as_of is not None and utc(observed_at) > utc(policy_as_of):
            errors.append("cost_evidence.observed_at cannot be after policy.as_of")
    return errors


def _bounded_simplex_projection(values: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """Euclidean projection onto sum(w)=1 with component bounds."""

    left = float(np.min(values - upper)) - 1.0
    right = float(np.max(values - lower)) + 1.0
    for _ in range(200):
        midpoint = (left + right) / 2.0
        candidate = np.clip(values - midpoint, lower, upper)
        if float(candidate.sum()) > 1.0:
            left = midpoint
        else:
            right = midpoint
    result = np.clip(values - (left + right) / 2.0, lower, upper)
    residual = 1.0 - float(result.sum())
    if abs(residual) > 1e-10:
        slack = upper - result if residual > 0 else result - lower
        order = np.argsort(-slack)
        for index in order:
            move = math.copysign(min(abs(residual), float(slack[index])), residual)
            result[index] += move
            residual -= move
            if abs(residual) <= 1e-12:
                break
    return result


def _erc_weights(
    covariance: np.ndarray,
    budgets: np.ndarray,
    *,
    tolerance: float,
    max_iterations: int,
) -> tuple[np.ndarray, bool, int, float]:
    """Solve the convex log-barrier risk-budgeting problem by coordinate descent."""

    weights = np.sqrt(budgets / np.diag(covariance))
    maximum_error = math.inf
    for iteration in range(1, max_iterations + 1):
        for index in range(len(weights)):
            cross = float(covariance[index] @ weights - covariance[index, index] * weights[index])
            variance = float(covariance[index, index])
            weights[index] = (-cross + math.sqrt(cross * cross + 4.0 * variance * budgets[index])) / (2.0 * variance)
        normalized = weights / weights.sum()
        marginal = covariance @ normalized
        total_variance = float(normalized @ marginal)
        shares = normalized * marginal / total_variance
        maximum_error = float(np.max(np.abs(shares - budgets)))
        if maximum_error <= tolerance:
            return normalized, True, iteration, maximum_error
    return weights / weights.sum(), False, max_iterations, maximum_error


def _risk_rows(symbols: list[str], weights: np.ndarray, covariance: np.ndarray) -> list[dict[str, float | str]]:
    marginal = covariance @ weights
    variance = float(weights @ marginal)
    return [
        {
            "symbol": symbol,
            "candidate_weight": round(float(weights[index]), 12),
            "variance_contribution_share": round(float(weights[index] * marginal[index] / variance), 12),
        }
        for index, symbol in enumerate(symbols)
    ]


def run_construction(
    scan: Any,
    policy: Any,
    *,
    scan_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(scan, dict) or scan.get("schema_version") != SCAN_SCHEMA_VERSION:
        errors.append(f"scan report must use {SCAN_SCHEMA_VERSION}")
        symbols: list[str] = []
    else:
        if scan.get("status") != "complete" or scan.get("formal_use_allowed") is not True:
            errors.append("scan report must be complete and formal_use_allowed")
        rankings = scan.get("rankings")
        if not isinstance(rankings, list) or not rankings:
            errors.append("scan.rankings must be a non-empty list")
            symbols = []
        else:
            symbols = [str(row.get("symbol", "")).strip().upper() for row in rankings if isinstance(row, dict)]
            if len(symbols) != len(rankings) or any(not symbol for symbol in symbols) or len(symbols) != len(set(symbols)):
                errors.append("scan rankings must contain unique non-empty symbols")
    errors.extend(_validate_policy(policy, symbols, scan.get("as_of") if isinstance(scan, dict) else None))
    if errors:
        return fail_report(SCHEMA_VERSION, "construction_contract_failed", errors)

    assert isinstance(scan, dict) and isinstance(policy, dict)
    rankings = scan["rankings"]
    covariance = np.asarray(policy["covariance"]["matrix"], dtype=float)
    if not np.allclose(covariance, covariance.T, atol=1e-10, rtol=0.0):
        return fail_report(SCHEMA_VERSION, "covariance_not_symmetric", ["covariance matrix must be symmetric"])
    eigenvalues = np.linalg.eigvalsh(covariance)
    if float(eigenvalues.min()) < -1e-10:
        return fail_report(SCHEMA_VERSION, "covariance_not_positive_semidefinite", ["covariance matrix must be positive semidefinite"])
    if np.any(np.diag(covariance) <= 0):
        return fail_report(SCHEMA_VERSION, "covariance_diagonal_invalid", ["covariance diagonal must be strictly positive"])
    covariance = covariance + np.eye(len(symbols)) * max(0.0, 1e-12 - float(eigenvalues.min()))

    current = np.asarray([policy["current_weights"][symbol] for symbol in symbols], dtype=float)
    budgets = np.asarray([policy["risk_budgets"][symbol] for symbol in symbols], dtype=float)
    minimum = np.asarray([policy["minimum_weights"][symbol] for symbol in symbols], dtype=float)
    maximum = np.asarray([policy["maximum_weights"][symbol] for symbol in symbols], dtype=float)
    trade_cap = float(policy["max_trade_weight"])
    effective_lower = np.maximum(minimum, current - trade_cap)
    effective_upper = np.minimum(maximum, current + trade_cap)
    if float(effective_lower.sum()) > 1.0 + 1e-10 or float(effective_upper.sum()) < 1.0 - 1e-10:
        return fail_report(SCHEMA_VERSION, "trade_cap_bounds_infeasible", ["max_trade_weight conflicts with portfolio bounds"])

    tolerance = float(policy["tolerance"])
    max_iterations = int(policy["max_iterations"])
    erc, erc_converged, erc_iterations, erc_error = _erc_weights(
        covariance,
        budgets,
        tolerance=tolerance,
        max_iterations=max_iterations,
    )
    bounded_erc = _bounded_simplex_projection(erc, effective_lower, effective_upper)

    robust_returns = np.asarray(
        [row["robust_expected_excess_return_annualized"] for row in rankings], dtype=float
    )
    risk_aversion = float(policy["risk_aversion"])
    cost_rate = float(policy["transaction_cost_bps"]) / 10_000.0
    step_size = float(policy["step_size"])
    active = bounded_erc.copy()
    active_converged = False
    active_delta = math.inf
    for active_iterations in range(1, max_iterations + 1):
        gradient = robust_returns - risk_aversion * (covariance @ active)
        gradient -= 0.5 * cost_rate * np.sign(active - current)
        candidate = _bounded_simplex_projection(
            active + step_size * gradient,
            effective_lower,
            effective_upper,
        )
        active_delta = float(np.max(np.abs(candidate - active)))
        active = candidate
        if active_delta <= tolerance:
            active_converged = True
            break

    one_way_turnover = 0.5 * float(np.abs(active - current).sum())
    turnover_limit = float(policy["max_one_way_turnover"])
    if one_way_turnover > turnover_limit and one_way_turnover > 0:
        active = current + (active - current) * (turnover_limit / one_way_turnover)
        one_way_turnover = 0.5 * float(np.abs(active - current).sum())
    predicted_volatility = math.sqrt(max(0.0, float(active @ covariance @ active)))
    expected_gross = float(active @ robust_returns)
    estimated_cost = one_way_turnover * cost_rate
    expected_net = expected_gross - estimated_cost
    formal = bool(erc_converged and active_converged)

    report = base_report(SCHEMA_VERSION)
    report.update(
        {
            "status": "complete" if formal else "incomplete",
            "detail_status": "research_portfolios_constructed" if formal else "optimizer_not_converged",
            "formal_use_allowed": formal,
            "as_of": scan["as_of"],
            "scan_report_sha256": scan_sha256,
            "construction_policy_sha256": policy_sha256,
            "symbols": symbols,
            "current_weights": {symbol: round(float(current[index]), 12) for index, symbol in enumerate(symbols)},
            "erc_candidate": {
                "converged": erc_converged,
                "iterations": erc_iterations,
                "max_risk_budget_error": round(erc_error, 12),
                "unbounded_weights": {symbol: round(float(erc[index]), 12) for index, symbol in enumerate(symbols)},
                "bounded_risk_contributions": _risk_rows(symbols, bounded_erc, covariance),
            },
            "active_candidate": {
                "converged": active_converged,
                "iterations": active_iterations,
                "max_weight_change_at_convergence": round(active_delta, 12),
                "weights": {symbol: round(float(active[index]), 12) for index, symbol in enumerate(symbols)},
                "risk_contributions": _risk_rows(symbols, active, covariance),
                "one_way_turnover": round(one_way_turnover, 12),
                "predicted_annualized_volatility": round(predicted_volatility, 12),
                "robust_expected_gross_excess_return_annualized": round(expected_gross, 12),
                "estimated_one_time_transaction_cost": round(estimated_cost, 12),
                "cost_adjusted_research_score": round(expected_net, 12),
            },
            "inputs": {
                "robust_expected_excess_returns": {
                    symbol: round(float(robust_returns[index]), 12) for index, symbol in enumerate(symbols)
                },
                "transaction_cost_bps": float(policy["transaction_cost_bps"]),
                "risk_aversion": risk_aversion,
            },
            "actionability": "prohibited",
            "fail_closed": {"enforced": True, "triggered": not formal},
            "limitations": [
                "Candidate weights are non-executable research outputs, not target weights or orders.",
                "The optimizer depends on supplied covariance, alpha, bounds, and cost assumptions.",
            ],
        }
    )
    return report


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps(fail_report(SCHEMA_VERSION, "argument_error", [message]), indent=2))
        raise SystemExit(2)


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("scan_report")
    parser.add_argument("--policy-file", required=True)
    args = parser.parse_args()
    try:
        scan = read_json(args.scan_report, "scan_report")
        policy = read_json(args.policy_file, "construction_policy")
        report = run_construction(
            scan,
            policy,
            scan_sha256=canonical_sha256(args.scan_report),
            policy_sha256=canonical_sha256(args.policy_file),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = fail_report(SCHEMA_VERSION, "input_read_failed", [str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
