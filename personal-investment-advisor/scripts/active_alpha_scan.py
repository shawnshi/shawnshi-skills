"""Rank validated alpha signals with evidence-age and confidence decay."""

from __future__ import annotations

import argparse
import json
import math
from typing import Any

from active_research_contract import (
    base_report,
    canonical_sha256,
    fail_report,
    finite_number,
    parse_aware_iso,
    positive_integer,
    read_json,
    utc,
)


SCHEMA_VERSION = "pia_active_alpha_scan_v1"
POLICY_SCHEMA_VERSION = "pia_active_scan_policy_v1"
PACKAGE_SCHEMA_VERSION = "pia_alpha_evidence_v1"
VALIDATION_SCHEMA_VERSION = "pia_alpha_validation_report_v1"


def _validate_policy(policy: Any) -> list[str]:
    if not isinstance(policy, dict):
        return ["scan policy root must be an object"]
    errors: list[str] = []
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"policy.schema_version must equal {POLICY_SCHEMA_VERSION}")
    weights = policy.get("component_weights")
    required = policy.get("required_components")
    if not isinstance(required, list) or not required or any(
        not isinstance(item, str) or not item.strip() for item in required
    ):
        errors.append("policy.required_components must be a non-empty string list")
        required = []
    elif len(required) != len(set(required)):
        errors.append("policy.required_components must be unique")
    if not isinstance(weights, dict) or set(weights) != set(required):
        errors.append("policy.component_weights keys must exactly match required_components")
    else:
        parsed = [finite_number(value) for value in weights.values()]
        if any(value is None or value < 0 for value in parsed):
            errors.append("policy.component_weights values must be non-negative and finite")
        elif abs(sum(float(value) for value in parsed if value is not None) - 1.0) > 1e-9:
            errors.append("policy.component_weights must sum to 1.0")
    max_age = finite_number(policy.get("max_component_age_days"))
    if max_age is None or max_age <= 0:
        errors.append("policy.max_component_age_days must be positive and finite")
    minimum_confidence = finite_number(policy.get("minimum_confidence"))
    if minimum_confidence is None or not 0 <= minimum_confidence <= 1:
        errors.append("policy.minimum_confidence must be between 0 and 1")
    uncertainty = finite_number(policy.get("uncertainty_penalty_multiplier"))
    if uncertainty is None or uncertainty < 0:
        errors.append("policy.uncertainty_penalty_multiplier must be non-negative and finite")
    retain_count = positive_integer(policy.get("retain_count"))
    if retain_count is None:
        errors.append("policy.retain_count must be a positive integer")
    return errors


def run_active_scan(
    package: Any,
    validation: Any,
    policy: Any,
    *,
    package_sha256: str,
    validation_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    errors = _validate_policy(policy)
    if not isinstance(package, dict) or package.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        errors.append(f"alpha package must use {PACKAGE_SCHEMA_VERSION}")
    if not isinstance(validation, dict) or validation.get("schema_version") != VALIDATION_SCHEMA_VERSION:
        errors.append(f"validation report must use {VALIDATION_SCHEMA_VERSION}")
    elif validation.get("status") != "complete":
        errors.append("validation report status must equal complete")
    elif validation.get("promotion_status") != "eligible_for_active_research":
        errors.append("validation report is not eligible_for_active_research")
    elif validation.get("alpha_package_sha256") != package_sha256:
        errors.append("validation report does not bind the supplied alpha package")
    if errors:
        return fail_report(
            SCHEMA_VERSION,
            "active_scan_contract_failed",
            errors,
            status="insufficient_evidence" if validation else "invalid_input",
        )
    assert isinstance(package, dict) and isinstance(policy, dict)
    as_of = parse_aware_iso(package.get("as_of"))
    if as_of is None:
        return fail_report(SCHEMA_VERSION, "alpha_package_as_of_invalid", ["package.as_of is invalid"])
    required = list(policy["required_components"])
    weights = {key: float(value) for key, value in policy["component_weights"].items()}
    minimum_confidence = float(policy["minimum_confidence"])
    max_age = float(policy["max_component_age_days"])
    uncertainty_multiplier = float(policy["uncertainty_penalty_multiplier"])
    rows: list[dict[str, Any]] = []
    scan_errors: list[str] = []
    for signal in package.get("signals", []):
        symbol = signal["symbol"]
        components = {component["name"]: component for component in signal["components"]}
        if set(components) != set(required):
            scan_errors.append(f"{symbol}: component set must exactly match scan policy")
            continue
        contributions: list[dict[str, Any]] = []
        score = 0.0
        for name in required:
            component = components[name]
            available_at = parse_aware_iso(component["evidence"].get("available_at"))
            if available_at is None:
                scan_errors.append(f"{symbol}.{name}: evidence available_at is invalid")
                continue
            age_days = max(0.0, (utc(as_of) - utc(available_at)).total_seconds() / 86_400.0)
            confidence = float(component["confidence"])
            if age_days > max_age:
                scan_errors.append(f"{symbol}.{name}: evidence exceeds max_component_age_days")
            if confidence < minimum_confidence:
                scan_errors.append(f"{symbol}.{name}: confidence is below minimum_confidence")
            decay = math.pow(0.5, age_days / float(component["decay_half_life_days"]))
            contribution = float(component["score"]) * confidence * decay * weights[name]
            score += contribution
            contributions.append(
                {
                    "name": name,
                    "raw_score": float(component["score"]),
                    "confidence": confidence,
                    "evidence_age_days": round(age_days, 10),
                    "decay_multiplier": round(decay, 10),
                    "weighted_contribution": round(contribution, 10),
                }
            )
        expected = float(signal["expected_excess_return_annualized"])
        error = float(signal["expected_return_standard_error"])
        robust_expected = math.copysign(
            max(abs(expected) - uncertainty_multiplier * error, 0.0), expected
        )
        rows.append(
            {
                "symbol": symbol,
                "opportunity_score": round(score, 10),
                "expected_excess_return_annualized": expected,
                "expected_return_standard_error": error,
                "robust_expected_excess_return_annualized": round(robust_expected, 10),
                "component_contributions": contributions,
                "economic_rationale": signal["economic_rationale"],
                "invalidation_condition": signal["invalidation_condition"],
            }
        )
    if scan_errors:
        return fail_report(
            SCHEMA_VERSION,
            "signal_coverage_or_freshness_failed",
            scan_errors,
            status="insufficient_evidence",
        )
    rows.sort(key=lambda item: (-item["opportunity_score"], item["symbol"]))
    retain_count = min(int(policy["retain_count"]), len(rows))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
        row["research_pool"] = "rank_pool" if rank <= retain_count else "yank_review_pool"
        row["actionability"] = "research_candidate_only"
    report = base_report(SCHEMA_VERSION)
    report.update(
        {
            "status": "complete",
            "detail_status": "active_research_ranking_computed",
            "formal_use_allowed": True,
            "as_of": package["as_of"],
            "alpha_package_sha256": package_sha256,
            "validation_report_sha256": validation_sha256,
            "scan_policy_sha256": policy_sha256,
            "rankings": rows,
            "rank_pool_count": retain_count,
            "yank_review_pool_count": len(rows) - retain_count,
            "fail_closed": {"enforced": True, "triggered": False},
            "limitations": [
                "Ranking is not a buy, sell, target-weight, or execution instruction.",
                "Expected excess returns remain estimates and can be wrong or decay abruptly.",
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
    parser.add_argument("alpha_package")
    parser.add_argument("--validation-report", required=True)
    parser.add_argument("--policy-file", required=True)
    args = parser.parse_args()
    try:
        package = read_json(args.alpha_package, "alpha_package")
        validation = read_json(args.validation_report, "validation_report")
        policy = read_json(args.policy_file, "scan_policy")
        report = run_active_scan(
            package,
            validation,
            policy,
            package_sha256=canonical_sha256(args.alpha_package),
            validation_sha256=canonical_sha256(args.validation_report),
            policy_sha256=canonical_sha256(args.policy_file),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = fail_report(SCHEMA_VERSION, "input_read_failed", [str(exc)])
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
