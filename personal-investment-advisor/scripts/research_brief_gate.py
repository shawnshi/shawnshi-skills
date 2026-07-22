import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references" / "research_brief_schema.json"
PROFILES_PATH = ROOT / "references" / "method_profiles.json"


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [])


def _valid_iso_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def validate_research_brief(
    payload: dict[str, Any],
    schema: dict[str, Any] | None = None,
    profiles: dict[str, Any] | None = None,
) -> list[str]:
    schema = schema or json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    profiles = profiles or json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    for field in schema["required_top_level"]:
        if not _non_empty(payload.get(field)):
            errors.append(f"missing required field: {field}")

    instrument = payload.get("instrument")
    if not isinstance(instrument, dict):
        errors.append("instrument must be an object")
    else:
        for field in schema["required_instrument_fields"]:
            if not _non_empty(instrument.get(field)):
                errors.append(f"missing instrument.{field}")
        if instrument.get("market") not in schema["enums"]["market"]:
            errors.append("instrument.market is invalid")
        if instrument.get("asset_type") not in schema["enums"]["asset_type"]:
            errors.append("instrument.asset_type is invalid")

    benchmark = payload.get("benchmark")
    if not isinstance(benchmark, dict):
        errors.append("benchmark must be an object")
    else:
        for field in schema["required_benchmark_fields"]:
            if not _non_empty(benchmark.get(field)):
                errors.append(f"missing benchmark.{field}")
        if benchmark.get("market") not in schema["enums"]["market"]:
            errors.append("benchmark.market is invalid")

    if not _valid_iso_date(payload.get("as_of_date")):
        errors.append("as_of_date must be an ISO date")
    try:
        if int(payload.get("investment_horizon_days")) <= 0:
            errors.append("investment_horizon_days must be positive")
    except (TypeError, ValueError):
        errors.append("investment_horizon_days must be an integer")

    method_profile = payload.get("method_profile")
    available_profiles = profiles.get("profiles", {})
    if method_profile not in available_profiles:
        errors.append(f"unknown method_profile: {method_profile}")
    elif isinstance(instrument, dict):
        applicable = available_profiles[method_profile].get("applicable_asset_types", [])
        if instrument.get("asset_type") not in applicable:
            errors.append(
                f"method_profile {method_profile} does not apply to asset_type {instrument.get('asset_type')}"
            )

    for field in ["falsification_conditions", "key_variables"]:
        value = payload.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"{field} must be a non-empty list")
    key_variables = payload.get("key_variables", [])
    if isinstance(key_variables, list):
        limits = schema["key_variable_limits"]
        if not limits["minimum"] <= len(key_variables) <= limits["maximum"]:
            errors.append(
                f"key_variables must contain {limits['minimum']} to {limits['maximum']} items"
            )

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        errors.append("source_policy must be an object")
    else:
        for field in schema["required_source_policy_fields"]:
            if source_policy.get(field) in (None, "", []):
                errors.append(f"missing source_policy.{field}")
        if not _valid_iso_date(source_policy.get("cutoff_date")):
            errors.append("source_policy.cutoff_date must be an ISO date")
        allowed = source_policy.get("allowed_source_tiers", [])
        if not isinstance(allowed, list):
            errors.append("source_policy.allowed_source_tiers must be a list")
        else:
            unknown = sorted(set(allowed) - set(schema["enums"]["source_tier"]))
            if unknown:
                errors.append(f"unknown source tiers: {', '.join(unknown)}")
            primary_tiers = {"company_primary", "regulator", "exchange", "audited_filing"}
            if not primary_tiers.intersection(allowed):
                errors.append("source_policy.allowed_source_tiers must include a primary source tier")
        if source_policy.get("primary_source_required") is not True:
            errors.append("source_policy.primary_source_required must be true")
        if source_policy.get("cutoff_date") != payload.get("as_of_date"):
            errors.append("source_policy.cutoff_date must equal as_of_date")

    output_contract = payload.get("output_contract")
    if not isinstance(output_contract, dict):
        errors.append("output_contract must be an object")
    else:
        for field in schema["required_output_contract_fields"]:
            if output_contract.get(field) in (None, "", []):
                errors.append(f"missing output_contract.{field}")
        if output_contract.get("decision_scope") not in schema["enums"]["decision_scope"]:
            errors.append("output_contract.decision_scope is invalid")
        if output_contract.get("include_counterevidence") is not True:
            errors.append("output_contract.include_counterevidence must be true")
        if output_contract.get("dual_trigger_policy") not in schema["enums"]["dual_trigger_policy"]:
            errors.append("output_contract.dual_trigger_policy is invalid")
        scenarios = output_contract.get("required_scenarios")
        if not isinstance(scenarios, list) or not {"base", "bull", "bear"}.issubset(set(scenarios)):
            errors.append("output_contract.required_scenarios must include base, bull, and bear")
        try:
            if float(output_contract.get("transaction_cost_bps")) < 0:
                errors.append("output_contract.transaction_cost_bps cannot be negative")
        except (TypeError, ValueError):
            errors.append("output_contract.transaction_cost_bps must be numeric")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an investment research brief before research starts.")
    parser.add_argument("brief_json")
    args = parser.parse_args()
    payload = json.loads(Path(args.brief_json).read_text(encoding="utf-8"))
    errors = validate_research_brief(payload)
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
