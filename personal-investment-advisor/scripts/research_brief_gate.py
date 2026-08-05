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


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_source_locator(value: Any) -> bool:
    if not _non_empty_string(value):
        return False
    lowered = value.strip().lower()
    return not any(
        token in lowered
        for token in ("example.com", "example.test", ".invalid", "localhost")
    )


def validate_research_brief(
    payload: dict[str, Any],
    schema: dict[str, Any] | None = None,
    profiles: dict[str, Any] | None = None,
    *,
    allow_legacy_archive: bool = False,
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
    ):
        if not _non_empty_string(payload.get(field)):
            errors.append(f"{field} must be a non-empty string")

    market_consensus = payload.get("market_consensus")
    consensus_metric = None
    consensus_value = None
    consensus_unit = None
    consensus_as_of_date = None
    if not isinstance(market_consensus, dict):
        errors.append("market_consensus must be an object")
    else:
        for field in schema["required_market_consensus_fields"]:
            if not _non_empty(market_consensus.get(field)):
                errors.append(f"missing market_consensus.{field}")
        if _non_empty_string(market_consensus.get("metric")):
            consensus_metric = market_consensus["metric"]
        else:
            errors.append("market_consensus.metric must be a non-empty string")
        if _finite_number(market_consensus.get("value")):
            consensus_value = float(market_consensus["value"])
        else:
            errors.append("market_consensus.value must be a finite number")
        if _non_empty_string(market_consensus.get("unit")):
            consensus_unit = market_consensus["unit"]
        else:
            errors.append("market_consensus.unit must be a non-empty string")
        if not _valid_iso_date(market_consensus.get("period_end")):
            errors.append("market_consensus.period_end must be an ISO date")
        if not _valid_source_locator(market_consensus.get("source_locator")):
            errors.append("market_consensus.source_locator must identify a real source")
        if _valid_iso_date(market_consensus.get("as_of_date")):
            consensus_as_of_date = date.fromisoformat(market_consensus["as_of_date"])
        else:
            errors.append("market_consensus.as_of_date must be an ISO date")

    core_hypothesis = payload.get("core_hypothesis")
    hypothesis_metric = None
    hypothesis_deadline = None
    independent_value = None
    expected_gap_value = None
    expected_gap_direction = None
    if not isinstance(core_hypothesis, dict):
        errors.append("core_hypothesis must be an object")
    else:
        for field in schema["required_core_hypothesis_fields"]:
            if not _non_empty(core_hypothesis.get(field)):
                errors.append(f"missing core_hypothesis.{field}")
        if not _non_empty_string(core_hypothesis.get("statement")):
            errors.append("core_hypothesis.statement must be a non-empty string")
        if not _non_empty_string(core_hypothesis.get("metric")):
            errors.append("core_hypothesis.metric must be a non-empty string")
        else:
            hypothesis_metric = core_hypothesis["metric"]

        independent_estimate = core_hypothesis.get("independent_estimate")
        if not isinstance(independent_estimate, dict):
            errors.append("core_hypothesis.independent_estimate must be an object")
        else:
            for field in schema["required_independent_estimate_fields"]:
                if not _non_empty(independent_estimate.get(field)):
                    errors.append(f"missing core_hypothesis.independent_estimate.{field}")
            if _finite_number(independent_estimate.get("value")):
                independent_value = float(independent_estimate["value"])
            else:
                errors.append("core_hypothesis.independent_estimate.value must be a finite number")
            if not _non_empty_string(independent_estimate.get("unit")):
                errors.append("core_hypothesis.independent_estimate.unit must be a non-empty string")
            elif consensus_unit is not None and independent_estimate["unit"] != consensus_unit:
                errors.append("core_hypothesis.independent_estimate.unit must match market_consensus.unit")

        expected_gap = core_hypothesis.get("expected_gap")
        if not isinstance(expected_gap, dict):
            errors.append("core_hypothesis.expected_gap must be an object")
        else:
            for field in schema["required_expected_gap_fields"]:
                if not _non_empty(expected_gap.get(field)):
                    errors.append(f"missing core_hypothesis.expected_gap.{field}")
            if _finite_number(expected_gap.get("absolute")):
                expected_gap_value = float(expected_gap["absolute"])
            else:
                errors.append("core_hypothesis.expected_gap.absolute must be a finite number")
            direction = expected_gap.get("direction")
            if direction in schema["enums"]["expected_gap_direction"]:
                expected_gap_direction = direction
            else:
                errors.append(
                    "core_hypothesis.expected_gap.direction must be one of "
                    f"{schema['enums']['expected_gap_direction']}"
                )

        falsified_when = core_hypothesis.get("falsified_when")
        if not isinstance(falsified_when, dict):
            errors.append("core_hypothesis.falsified_when must be an object")
        else:
            for field in schema["required_hypothesis_falsifier_fields"]:
                if not _non_empty(falsified_when.get(field)):
                    errors.append(f"missing core_hypothesis.falsified_when.{field}")
            operator = falsified_when.get("operator")
            if operator not in schema["enums"]["hypothesis_operator"]:
                errors.append(
                    "core_hypothesis.falsified_when.operator must be one of "
                    f"{schema['enums']['hypothesis_operator']}"
                )
            target = falsified_when.get("target")
            if (
                not isinstance(target, (int, float))
                or isinstance(target, bool)
                or not math.isfinite(float(target))
            ):
                errors.append(
                    "core_hypothesis.falsified_when.target must be a finite number"
                )
            deadline = falsified_when.get("deadline")
            if not _valid_iso_date(deadline):
                errors.append(
                    "core_hypothesis.falsified_when.deadline must be an ISO date"
                )
            else:
                hypothesis_deadline = date.fromisoformat(deadline)

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

    as_of_date = None
    if not _valid_iso_date(payload.get("as_of_date")):
        errors.append("as_of_date must be an ISO date")
    else:
        as_of_date = date.fromisoformat(payload["as_of_date"])
        if as_of_date > date.today():
            errors.append("as_of_date cannot be in the future")
    horizon = payload.get("investment_horizon_days")
    if not isinstance(horizon, int) or isinstance(horizon, bool):
        errors.append("investment_horizon_days must be a positive integer")
    elif horizon <= 0:
        errors.append("investment_horizon_days must be a positive integer")
    if hypothesis_deadline is not None and as_of_date is not None:
        if hypothesis_deadline < as_of_date:
            errors.append(
                "core_hypothesis.falsified_when.deadline cannot be before as_of_date"
            )
        elif (
            isinstance(horizon, int)
            and not isinstance(horizon, bool)
            and horizon > 0
            and (hypothesis_deadline - as_of_date).days > horizon
        ):
            errors.append(
                "core_hypothesis.falsified_when.deadline cannot be after the investment horizon"
            )
    if consensus_as_of_date is not None and as_of_date is not None and consensus_as_of_date > as_of_date:
        errors.append("market_consensus.as_of_date cannot be after as_of_date")
    if consensus_metric is not None and hypothesis_metric is not None and consensus_metric != hypothesis_metric:
        errors.append("market_consensus.metric must match core_hypothesis.metric")
    if consensus_value is not None and independent_value is not None and expected_gap_value is not None:
        calculated_gap = independent_value - consensus_value
        if not math.isclose(expected_gap_value, calculated_gap, rel_tol=1e-9, abs_tol=1e-12):
            errors.append(
                "core_hypothesis.expected_gap.absolute must equal independent estimate minus consensus"
            )
        calculated_direction = "above" if calculated_gap > 0 else "below" if calculated_gap < 0 else "equal"
        if expected_gap_direction is not None and expected_gap_direction != calculated_direction:
            errors.append("core_hypothesis.expected_gap.direction is inconsistent with the numeric gap")

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
        if (
            hypothesis_metric is not None
            and _string_list(key_variables)
            and hypothesis_metric not in key_variables
        ):
            errors.append(
                "core_hypothesis.metric must reference an item in key_variables"
            )
        if (
            consensus_metric is not None
            and _string_list(key_variables)
            and consensus_metric not in key_variables
        ):
            errors.append("market_consensus.metric must reference an item in key_variables")

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        errors.append("source_policy must be an object")
    else:
        for field in schema["required_source_policy_fields"]:
            if source_policy.get(field) in (None, "", []):
                errors.append(f"missing source_policy.{field}")
        cutoff_date = source_policy.get("cutoff_date")
        if not _valid_iso_date(cutoff_date):
            errors.append("source_policy.cutoff_date must be an ISO date")
        elif date.fromisoformat(cutoff_date) > date.today():
            errors.append("source_policy.cutoff_date cannot be in the future")
        allowed = source_policy.get("allowed_source_tiers", [])
        if not _string_list(allowed):
            errors.append(
                "source_policy.allowed_source_tiers must be a non-empty list of non-empty strings"
            )
        else:
            unknown = sorted(set(allowed) - set(schema["enums"]["source_tier"]))
            if unknown:
                errors.append(f"unknown source tiers: {', '.join(unknown)}")
            legacy_tiers = set(schema.get("legacy_archive_source_tiers", []))
            legacy_used = sorted(set(allowed).intersection(legacy_tiers))
            if legacy_used and not allow_legacy_archive:
                errors.append(
                    "archive-only source tiers are prohibited for a current research brief: "
                    + ", ".join(legacy_used)
                )
            primary_tiers = set(schema.get("primary_source_tiers", []))
            if allow_legacy_archive:
                primary_tiers.update(legacy_tiers)
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
