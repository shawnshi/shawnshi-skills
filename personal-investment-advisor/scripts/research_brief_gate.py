import argparse
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references" / "research_brief_schema.json"
PROFILES_PATH = ROOT / "references" / "method_profiles.json"


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [])


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_non_empty_string(item) for item in value)
    )


def _valid_iso_date(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    try:
        date.fromisoformat(value)
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
    if not isinstance(payload, dict):
        return ["research brief payload must be an object"]

    for field in schema["required_top_level"]:
        if not _non_empty(payload.get(field)):
            errors.append(f"missing required field: {field}")

    for field in (
        "research_id",
        "method_profile",
        "research_question",
        "market_consensus",
        "core_hypothesis",
    ):
        if not _non_empty_string(payload.get(field)):
            errors.append(f"{field} must be a non-empty string")

    instrument = payload.get("instrument")
    if not isinstance(instrument, dict):
        errors.append("instrument must be an object")
    else:
        for field in schema["required_instrument_fields"]:
            if not _non_empty_string(instrument.get(field)):
                errors.append(f"instrument.{field} must be a non-empty string")
        if instrument.get("market") not in schema["enums"]["market"]:
            errors.append("instrument.market is invalid")
        if instrument.get("asset_type") not in schema["enums"]["asset_type"]:
            errors.append("instrument.asset_type is invalid")
        currency = instrument.get("currency")
        if not _non_empty_string(currency) or not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append("instrument.currency must be a three-letter uppercase currency code")
        expected_currency = schema.get("market_currency", {}).get(instrument.get("market"))
        if expected_currency and currency != expected_currency:
            errors.append(
                f"instrument.currency must be {expected_currency} for market {instrument.get('market')}"
            )
        if "industry_type" in instrument:
            if not _non_empty_string(instrument.get("industry_type")):
                errors.append("instrument.industry_type must be a non-empty string")
            elif instrument.get("industry_type") not in schema["enums"].get("industry_type", []):
                errors.append("instrument.industry_type is invalid")

    benchmark = payload.get("benchmark")
    if not isinstance(benchmark, dict):
        errors.append("benchmark must be an object")
    else:
        for field in schema["required_benchmark_fields"]:
            if not _non_empty_string(benchmark.get(field)):
                errors.append(f"benchmark.{field} must be a non-empty string")
        if benchmark.get("market") not in schema["enums"]["market"]:
            errors.append("benchmark.market is invalid")
        currency = benchmark.get("currency")
        if not _non_empty_string(currency) or not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append("benchmark.currency must be a three-letter uppercase currency code")
        expected_currency = schema.get("market_currency", {}).get(benchmark.get("market"))
        if expected_currency and currency != expected_currency:
            errors.append(
                f"benchmark.currency must be {expected_currency} for market {benchmark.get('market')}"
            )

    if not _valid_iso_date(payload.get("as_of_date")):
        errors.append("as_of_date must be an ISO date")
    horizon = payload.get("investment_horizon_days")
    if not isinstance(horizon, int) or isinstance(horizon, bool):
        errors.append("investment_horizon_days must be a positive integer")
    elif horizon <= 0:
        errors.append("investment_horizon_days must be a positive integer")

    method_profile = payload.get("method_profile")
    available_profiles = profiles.get("profiles", {})
    if not _non_empty_string(method_profile):
        pass
    elif method_profile not in available_profiles:
        errors.append(f"unknown method_profile: {method_profile}")
    elif isinstance(instrument, dict):
        selected_profile = available_profiles[method_profile]
        applicable_assets = selected_profile.get("applicable_asset_types", [])
        applicable_markets = selected_profile.get("applicable_markets", [])
        applicable_industries = selected_profile.get("applicable_industry_types")
        if instrument.get("asset_type") not in applicable_assets:
            errors.append(
                f"method_profile {method_profile} does not apply to asset_type {instrument.get('asset_type')}"
            )
        if instrument.get("market") not in applicable_markets:
            errors.append(
                f"method_profile {method_profile} does not apply to market {instrument.get('market')}"
            )
        if applicable_industries is not None:
            industry_type = instrument.get("industry_type")
            if industry_type not in applicable_industries:
                errors.append(
                    f"method_profile {method_profile} requires instrument.industry_type in "
                    f"{', '.join(applicable_industries)}"
                )

    for field in ["falsification_conditions", "key_variables"]:
        value = payload.get(field)
        if not _string_list(value):
            errors.append(f"{field} must be a non-empty list of non-empty strings")
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
        if not _string_list(allowed):
            errors.append(
                "source_policy.allowed_source_tiers must be a non-empty list of non-empty strings"
            )
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
        if output_contract.get("decision_scope") != "research_only":
            errors.append("output_contract.decision_scope must be research_only")
        if output_contract.get("include_counterevidence") is not True:
            errors.append("output_contract.include_counterevidence must be true")
        if output_contract.get("dual_trigger_policy") not in schema["enums"]["dual_trigger_policy"]:
            errors.append("output_contract.dual_trigger_policy is invalid")
        scenarios = output_contract.get("required_scenarios")
        if not _string_list(scenarios) or set(scenarios) != {"base", "bull", "bear"}:
            errors.append("output_contract.required_scenarios must include base, bull, and bear")
        transaction_cost = output_contract.get("transaction_cost_bps")
        if (
            not isinstance(transaction_cost, (int, float))
            or isinstance(transaction_cost, bool)
            or not math.isfinite(float(transaction_cost))
        ):
            errors.append("output_contract.transaction_cost_bps must be numeric")
        elif float(transaction_cost) < 0:
            errors.append("output_contract.transaction_cost_bps cannot be negative")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an investment research brief before research starts.")
    parser.add_argument("brief_json")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable JSON contract (JSON is also the default output).",
    )
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.brief_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "status": "data_error",
            "detail_status": "research_brief_unreadable",
            "valid": False,
            "errors": [str(exc)],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    try:
        errors = validate_research_brief(payload)
    except Exception as exc:
        result = {
            "status": "data_error",
            "detail_status": "research_brief_validation_error",
            "valid": False,
            "errors": [str(exc)],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result = {
        "status": "ok" if not errors else "invalid",
        "detail_status": "research_brief_valid" if not errors else "research_brief_invalid",
        "valid": not errors,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
