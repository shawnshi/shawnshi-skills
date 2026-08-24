"""Translate a constructed research portfolio into a non-executable review proposal."""

from __future__ import annotations

import argparse
import json
from typing import Any

from active_research_contract import (
    base_report,
    canonical_sha256,
    fail_report,
    finite_number,
    positive_integer,
    read_json,
)


SCHEMA_VERSION = "pia_rebalance_research_proposal_v1"
POLICY_SCHEMA_VERSION = "pia_rebalance_proposal_policy_v1"
CONSTRUCTION_SCHEMA_VERSION = "pia_active_portfolio_construction_v1"


def _validate_policy(policy: Any) -> list[str]:
    if not isinstance(policy, dict):
        return ["proposal policy root must be an object"]
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"policy.schema_version must equal {POLICY_SCHEMA_VERSION}")
    if policy.get("decision_scope") != "research_only":
        errors.append("policy.decision_scope must equal research_only")
    no_trade_band = finite_number(policy.get("no_trade_band"))
    if no_trade_band is None or not 0 <= no_trade_band <= 1:
        errors.append("policy.no_trade_band must be between 0 and 1")
    minimum_benefit = finite_number(policy.get("minimum_net_expected_benefit"))
    if minimum_benefit is None or minimum_benefit < 0:
        errors.append("policy.minimum_net_expected_benefit must be non-negative and finite")
    if positive_integer(policy.get("review_horizon_days")) is None:
        errors.append("policy.review_horizon_days must be a positive integer")
    return errors


def run_proposal(
    construction: Any,
    policy: Any,
    *,
    construction_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    errors = _validate_policy(policy)
    if not isinstance(construction, dict) or construction.get("schema_version") != CONSTRUCTION_SCHEMA_VERSION:
        errors.append(f"construction report must use {CONSTRUCTION_SCHEMA_VERSION}")
    elif construction.get("status") != "complete" or construction.get("formal_use_allowed") is not True:
        errors.append("construction report must be complete and formal_use_allowed")
    if errors:
        return fail_report(
            SCHEMA_VERSION,
            "proposal_contract_failed",
            errors,
            status="insufficient_evidence" if isinstance(construction, dict) else "invalid_input",
        )

    assert isinstance(construction, dict) and isinstance(policy, dict)
    symbols = construction["symbols"]
    current = construction["current_weights"]
    candidate = construction["active_candidate"]["weights"]
    expected = construction["inputs"]["robust_expected_excess_returns"]
    cost_rate = float(construction["inputs"]["transaction_cost_bps"]) / 10_000.0
    band = float(policy["no_trade_band"])
    horizon_days = int(policy["review_horizon_days"])
    rows: list[dict[str, Any]] = []
    annual_incremental_benefit = 0.0
    estimated_cost = 0.0
    outside_band = 0
    for symbol in symbols:
        current_weight = float(current[symbol])
        candidate_weight = float(candidate[symbol])
        allocation_gap = candidate_weight - current_weight
        annual_contribution = allocation_gap * float(expected[symbol])
        symbol_cost = 0.5 * abs(allocation_gap) * cost_rate
        annual_incremental_benefit += annual_contribution
        estimated_cost += symbol_cost
        within_band = abs(allocation_gap) <= band + 1e-12
        if not within_band:
            outside_band += 1
        rows.append(
            {
                "symbol": symbol,
                "current_weight": round(current_weight, 12),
                "candidate_weight": round(candidate_weight, 12),
                "allocation_gap": round(allocation_gap, 12),
                "absolute_gap": round(abs(allocation_gap), 12),
                "within_no_trade_band": within_band,
                "research_review_status": "inside_no_trade_band" if within_band else "candidate_gap_for_review",
                "estimated_annual_incremental_excess_contribution": round(annual_contribution, 12),
                "estimated_one_time_cost": round(symbol_cost, 12),
                "actionability": "prohibited",
            }
        )
    horizon_gross = annual_incremental_benefit * horizon_days / 365.0
    horizon_net = horizon_gross - estimated_cost
    minimum_benefit = float(policy["minimum_net_expected_benefit"])
    proposal_status = (
        "research_review_candidate"
        if outside_band > 0 and horizon_net >= minimum_benefit
        else "no_active_research_case"
    )
    report = base_report(SCHEMA_VERSION)
    report.update(
        {
            "status": "complete",
            "detail_status": "non_executable_rebalance_research_completed",
            "formal_use_allowed": True,
            "as_of": construction["as_of"],
            "construction_report_sha256": construction_sha256,
            "proposal_policy_sha256": policy_sha256,
            "proposal_status": proposal_status,
            "review_horizon_days": horizon_days,
            "no_trade_band": band,
            "rows": rows,
            "outside_band_count": outside_band,
            "estimated_horizon_gross_benefit": round(horizon_gross, 12),
            "estimated_one_time_transaction_cost": round(estimated_cost, 12),
            "estimated_horizon_net_benefit": round(horizon_net, 12),
            "minimum_net_expected_benefit": minimum_benefit,
            "actionability": "prohibited",
            "fail_closed": {"enforced": True, "triggered": False},
            "limitations": [
                "This proposal is a research comparison only and cannot authorize portfolio changes.",
                "Allocation gaps are not orders, target weights, timing advice, or execution instructions.",
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
    parser.add_argument("construction_report")
    parser.add_argument("--policy-file", required=True)
    args = parser.parse_args()
    try:
        construction = read_json(args.construction_report, "construction_report")
        policy = read_json(args.policy_file, "proposal_policy")
        report = run_proposal(
            construction,
            policy,
            construction_sha256=canonical_sha256(args.construction_report),
            policy_sha256=canonical_sha256(args.policy_file),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = fail_report(SCHEMA_VERSION, "input_read_failed", [str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
