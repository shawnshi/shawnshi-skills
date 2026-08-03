import json
import math
from datetime import date
from pathlib import Path

from dashboard_math_gate import collect_math_warnings, validate_math_consistency
from research_brief_gate import validate_research_brief


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "dashboard_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _get_nested(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _find_forbidden_fields(value, path="root"):
    forbidden = set(SCHEMA.get("forbidden_legacy_fields", []))
    hits = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in forbidden:
                hits.append(child_path)
            hits.extend(_find_forbidden_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            hits.extend(_find_forbidden_fields(child, f"{path}[{index}]"))
    return hits


def _validate_evidence_items(items):
    errors = []
    if not isinstance(items, list) or len(items) == 0:
        return ["evidence_items must be a non-empty list"]
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"evidence_items[{idx}] must be an object")
            continue
        for key in SCHEMA["required_evidence_fields"]:
            if item.get(key) in (None, "", []):
                errors.append(f"missing evidence_items[{idx}].{key}")
        if item.get("source_tier") not in SCHEMA["enums"]["source_tier"]:
            errors.append(f"invalid evidence_items[{idx}].source_tier")
        locator = str(item.get("source_locator", "")).lower()
        if any(token in locator for token in ["example.com", "example.test", ".invalid", "localhost"]):
            errors.append(f"evidence_items[{idx}].source_locator is a reserved test locator")
        for field in ["published_at", "retrieved_at", "as_of_date"]:
            value = item.get(field)
            try:
                date.fromisoformat(str(value))
            except (TypeError, ValueError):
                errors.append(f"evidence_items[{idx}].{field} must be an ISO date")
        count = item.get("independent_source_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            errors.append(f"evidence_items[{idx}].independent_source_count must be an integer >= 1")
        try:
            published = date.fromisoformat(str(item.get("published_at")))
            retrieved = date.fromisoformat(str(item.get("retrieved_at")))
            as_of = date.fromisoformat(str(item.get("as_of_date")))
            if published > retrieved:
                errors.append(f"evidence_items[{idx}] published_at cannot be after retrieved_at")
            if retrieved > as_of:
                errors.append(f"evidence_items[{idx}] retrieved_at cannot be after as_of_date")
        except (TypeError, ValueError):
            pass
    return errors


def _validate_evidence_against_brief(items, research_brief):
    if not isinstance(items, list) or not isinstance(research_brief, dict):
        return []
    source_policy = research_brief.get("source_policy")
    if not isinstance(source_policy, dict):
        return []
    allowed_raw = source_policy.get("allowed_source_tiers")
    allowed = set(allowed_raw) if isinstance(allowed_raw, list) else set()
    try:
        cutoff = date.fromisoformat(str(source_policy.get("cutoff_date")))
    except (TypeError, ValueError):
        cutoff = None

    errors = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        source_tier = item.get("source_tier")
        if allowed and source_tier not in allowed:
            errors.append(
                f"evidence_items[{index}].source_tier is not allowed by "
                "research_brief.source_policy"
            )
        if cutoff is None:
            continue
        for field in ("published_at", "as_of_date"):
            try:
                evidence_date = date.fromisoformat(str(item.get(field)))
            except (TypeError, ValueError):
                continue
            if evidence_date > cutoff:
                errors.append(
                    f"evidence_items[{index}].{field} cannot be after "
                    "research_brief.source_policy.cutoff_date"
                )
    return errors


def _non_empty_string_list(value):
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _validate_scenario_analysis(data, *, required):
    scenarios = data.get("scenario_analysis")
    if scenarios is None:
        return (
            ["scenario_analysis is required by the current strict contract"]
            if required
            else []
        )
    if not isinstance(scenarios, dict):
        return ["scenario_analysis must be an object"]

    errors = []
    for field in SCHEMA.get("required_scenario_analysis_fields", []):
        if scenarios.get(field) in (None, "", []):
            errors.append(f"missing scenario_analysis.{field}")
    if not isinstance(scenarios.get("valuation_method"), str) or not scenarios.get(
        "valuation_method", ""
    ).strip():
        errors.append("scenario_analysis.valuation_method must be a non-empty string")
    if not _non_empty_string_list(scenarios.get("sensitivity")):
        errors.append("scenario_analysis.sensitivity must be a non-empty string list")

    for case_name in ("base", "bull", "bear"):
        case = scenarios.get(case_name)
        prefix = f"scenario_analysis.{case_name}"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in SCHEMA.get("required_scenario_case_fields", []):
            if case.get(field) in (None, "", []):
                errors.append(f"missing {prefix}.{field}")
        if not _non_empty_string_list(case.get("assumptions")):
            errors.append(f"{prefix}.assumptions must be a non-empty string list")
        if not isinstance(case.get("result"), str) or not case.get("result", "").strip():
            errors.append(f"{prefix}.result must be a non-empty string")
        if not _non_empty_string_list(case.get("falsification_conditions")):
            errors.append(
                f"{prefix}.falsification_conditions must be a non-empty string list"
            )
    return errors


def _is_positive_json_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _validate_monitoring_boundaries(data):
    config = data.get("monitoring_boundaries")
    if config is None:
        return []
    if not isinstance(config, dict):
        return ["monitoring_boundaries must be an object when provided"]

    errors = []
    for key in SCHEMA["required_monitoring_boundaries_fields"]:
        if config.get(key) in (None, "", []):
            errors.append(f"missing monitoring_boundaries field: {key}")

    if config.get("decision_scope") not in SCHEMA["enums"]["monitoring_boundary_decision_scope"]:
        errors.append("monitoring_boundaries.decision_scope must be observation_only")
    if config.get("metric") not in SCHEMA["enums"]["monitoring_boundary_metric"]:
        errors.append("monitoring_boundaries.metric must be regular_market_price")

    boundaries = config.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        return errors + ["monitoring_boundaries.boundaries must be a non-empty list"]

    instrument_currency = str(
        _get_nested(data, ["research_brief", "instrument", "currency"], "")
    ).upper()
    research_as_of_raw = _get_nested(data, ["research_brief", "as_of_date"])
    try:
        research_as_of = date.fromisoformat(str(research_as_of_raw))
    except (TypeError, ValueError):
        research_as_of = None

    identifiers = set()
    roles = {}
    for index, boundary in enumerate(boundaries):
        prefix = f"monitoring_boundaries.boundaries[{index}]"
        if not isinstance(boundary, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for key in SCHEMA["required_monitoring_boundary_fields"]:
            if boundary.get(key) in (None, "", []):
                errors.append(f"missing {prefix}.{key}")

        boundary_id = str(boundary.get("boundary_id") or "")
        if boundary_id in identifiers:
            errors.append(f"duplicate monitoring boundary_id: {boundary_id}")
        elif boundary_id:
            identifiers.add(boundary_id)

        role = boundary.get("role")
        operator = boundary.get("operator")
        if role not in SCHEMA["enums"]["monitoring_boundary_role"]:
            errors.append(f"invalid {prefix}.role")
        elif role in roles:
            errors.append(f"duplicate monitoring boundary role: {role}")
        else:
            roles[role] = boundary
        if operator not in SCHEMA["enums"]["monitoring_boundary_operator"]:
            errors.append(f"invalid {prefix}.operator")
        if role == "downside_boundary" and operator != "lte":
            errors.append(f"{prefix}.operator must be lte for downside_boundary")
        if role == "upside_boundary" and operator != "gte":
            errors.append(f"{prefix}.operator must be gte for upside_boundary")

        if not _is_positive_json_number(boundary.get("value")):
            errors.append(f"{prefix}.value must be a positive finite JSON number")

        currency = str(boundary.get("currency") or "").upper()
        if not currency:
            errors.append(f"{prefix}.currency is required")
        elif instrument_currency and currency != instrument_currency:
            errors.append(f"{prefix}.currency must match research_brief.instrument.currency")

        if boundary.get("quote_basis") not in SCHEMA["enums"]["monitoring_boundary_quote_basis"]:
            errors.append(f"invalid {prefix}.quote_basis")
        if boundary.get("authority_status") not in SCHEMA["enums"]["monitoring_boundary_authority_status"]:
            errors.append(f"invalid {prefix}.authority_status")
        if boundary.get("source_tier") != "user_authorized":
            errors.append(f"{prefix}.source_tier must be user_authorized")

        try:
            boundary_as_of = date.fromisoformat(str(boundary.get("as_of_date")))
            if research_as_of and boundary_as_of > research_as_of:
                errors.append(f"{prefix}.as_of_date cannot be after research_brief.as_of_date")
        except (TypeError, ValueError):
            errors.append(f"{prefix}.as_of_date must be an ISO date")

    downside = roles.get("downside_boundary")
    upside = roles.get("upside_boundary")
    if (
        downside
        and upside
        and _is_positive_json_number(downside.get("value"))
        and _is_positive_json_number(upside.get("value"))
        and float(downside["value"]) >= float(upside["value"])
    ):
        errors.append("downside boundary must be below upside boundary")

    current_price = _get_nested(
        data, ["dashboard", "data_perspective", "price_position", "current_price"]
    )
    if not _is_positive_json_number(current_price):
        errors.append(
            "monitoring boundaries require a positive finite "
            "dashboard.data_perspective.price_position.current_price"
        )

    proximity = config.get("proximity_policy")
    if proximity is not None:
        if not isinstance(proximity, dict):
            errors.append("monitoring_boundaries.proximity_policy must be an object")
        else:
            for key in SCHEMA["required_proximity_policy_fields"]:
                if proximity.get(key) in (None, "", []):
                    errors.append(f"missing monitoring_boundaries.proximity_policy.{key}")
            if proximity.get("mode") not in SCHEMA["enums"]["monitoring_proximity_mode"]:
                errors.append(
                    "monitoring_boundaries.proximity_policy.mode must be explicit_relative_pct"
                )
            value = proximity.get("value")
            if (
                not _is_positive_json_number(value)
                or float(value) >= 1
            ):
                errors.append(
                    "monitoring_boundaries.proximity_policy.value must be a "
                    "positive finite JSON number below 1"
                )
            if proximity.get("source_tier") != "user_authorized":
                errors.append(
                    "monitoring_boundaries.proximity_policy.source_tier "
                    "must be user_authorized"
                )
            try:
                proximity_as_of = date.fromisoformat(str(proximity.get("as_of_date")))
                if research_as_of and proximity_as_of > research_as_of:
                    errors.append(
                        "monitoring_boundaries.proximity_policy.as_of_date "
                        "cannot be after research_brief.as_of_date"
                    )
            except (TypeError, ValueError):
                errors.append(
                    "monitoring_boundaries.proximity_policy.as_of_date must be an ISO date"
                )

    return errors


def validate_dashboard(data: dict, *, require_scenarios: bool = False) -> list[str]:
    errors = []
    if not isinstance(data, dict):
        return ["dashboard root must be an object"]

    for key in SCHEMA["required_top_level"]:
        if key not in data:
            errors.append(f"missing top-level field: {key}")
    allowed_top_level = set(SCHEMA["required_top_level"]) | set(
        SCHEMA.get("optional_top_level", [])
    )
    for key in sorted(set(data) - allowed_top_level):
        errors.append(f"unknown top-level field: {key}")

    for path in _find_forbidden_fields(data):
        errors.append(f"legacy trade field is not allowed in research-only output: {path}")

    blind_spot = data.get("blind_spot_warning")
    if blind_spot in (None, "", []):
        errors.append("blind_spot_warning cannot be empty (Adversarial Stress Test failed)")

    market_type = data.get("market_type")
    if market_type not in SCHEMA["enums"]["market_type"]:
        errors.append(f"invalid market_type: {market_type}")

    research_mode = data.get("research_mode")
    if research_mode not in SCHEMA["enums"]["research_mode"]:
        errors.append(f"invalid research_mode: {research_mode}")

    if data.get("confidence_level") not in SCHEMA["enums"]["confidence_level"]:
        errors.append(f"invalid confidence_level: {data.get('confidence_level')}")

    dashboard = data.get("dashboard", {})
    if not isinstance(dashboard, dict):
        errors.append("dashboard must be an object")
        dashboard = {}
    else:
        for key in SCHEMA["required_dashboard_sections"]:
            if key not in dashboard:
                errors.append(f"missing dashboard section: {key}")
        for key in (
            "core_conclusion",
            "qualitative_analysis",
            "data_perspective",
            "intelligence",
        ):
            if key in dashboard and not isinstance(dashboard.get(key), dict):
                errors.append(f"dashboard.{key} must be an object")

    for key in SCHEMA["required_core_conclusion_fields"]:
        if _get_nested(data, ["dashboard", "core_conclusion", key]) in (None, "", []):
            errors.append(f"missing core_conclusion field: {key}")

    research_plan = _get_nested(data, ["dashboard", "research_plan"], {})
    if not isinstance(research_plan, dict):
        errors.append("dashboard.research_plan must be an object")
        research_plan = {}
    for key in SCHEMA["required_research_plan_fields"]:
        value = research_plan.get(key)
        if not isinstance(value, list) or not value:
            errors.append(f"research_plan.{key} must be a non-empty list")

    for key in SCHEMA["required_data_perspective_fields"]:
        if _get_nested(data, ["dashboard", "data_perspective", key]) in (None, "", []):
            errors.append(f"missing data_perspective field: {key}")
    data_perspective = _get_nested(data, ["dashboard", "data_perspective"], {})
    if isinstance(data_perspective, dict):
        for key in ("trend_status", "price_position", "volume_analysis", "chip_structure"):
            if key in data_perspective and not isinstance(data_perspective.get(key), dict):
                errors.append(f"data_perspective.{key} must be an object")

    for key in SCHEMA["required_intelligence_fields"]:
        if _get_nested(data, ["dashboard", "intelligence", key]) in (None, ""):
            errors.append(f"missing intelligence field: {key}")

    if not isinstance(data.get("confidence_details"), dict):
        errors.append("confidence_details must be an object")
    for key in SCHEMA["required_confidence_fields"]:
        if _get_nested(data, ["confidence_details", key]) in (None, "", []):
            errors.append(f"missing confidence_details field: {key}")

    if not isinstance(data.get("freshness_flags"), dict):
        errors.append("freshness_flags must be an object")
    for key in SCHEMA["required_freshness_fields"]:
        if _get_nested(data, ["freshness_flags", key]) in (None, ""):
            errors.append(f"missing freshness_flags field: {key}")

    stale_inputs = _get_nested(data, ["freshness_flags", "stale_inputs"], [])
    if not isinstance(stale_inputs, list):
        errors.append("freshness_flags.stale_inputs must be a list")

    errors.extend(_validate_evidence_items(data.get("evidence_items")))

    data_sources = data.get("data_sources")
    if not isinstance(data_sources, (list, str, dict)):
        errors.append("data_sources must be list, string, or dict")

    data_gaps = data.get("data_gaps")
    if not isinstance(data_gaps, list):
        errors.append("data_gaps must be a list")

    research_brief = data.get("research_brief")
    if not isinstance(research_brief, dict):
        errors.append("research_brief is required for every research-only dashboard")
    else:
        errors.extend(
            f"research_brief: {error}"
            for error in validate_research_brief(research_brief)
        )
        decision_scope = _get_nested(
            research_brief, ["output_contract", "decision_scope"]
        )
        if decision_scope != "research_only":
            errors.append(
                "research_brief.output_contract.decision_scope must be research_only"
            )
        raw_dashboard_symbol = data.get("stock_code")
        raw_brief_symbol = _get_nested(
            research_brief,
            ["instrument", "symbol"],
            "",
        )
        dashboard_symbol = (
            raw_dashboard_symbol.strip().upper()
            if isinstance(raw_dashboard_symbol, str)
            else ""
        )
        brief_symbol = (
            raw_brief_symbol.strip().upper()
            if isinstance(raw_brief_symbol, str)
            else ""
        )
        if not isinstance(raw_dashboard_symbol, str) or not dashboard_symbol:
            errors.append("stock_code must be a non-empty string")
        if not isinstance(raw_brief_symbol, str) or not brief_symbol:
            errors.append(
                "research_brief.instrument.symbol must be a non-empty string"
            )
        elif dashboard_symbol and dashboard_symbol != brief_symbol:
            errors.append(
                "stock_code must match research_brief.instrument.symbol"
            )
        expected_brief_market = {
            "A股": "CN",
            "港股": "HK",
            "美股": "US",
        }.get(market_type)
        brief_market = _get_nested(
            research_brief,
            ["instrument", "market"],
        )
        if (
            expected_brief_market is not None
            and brief_market != expected_brief_market
        ):
            errors.append(
                "market_type must match research_brief.instrument.market"
            )
        expected_asset_types = {
            "A股": {"stock"},
            "港股": {"stock"},
            "美股": {"stock"},
            "ETF": {"etf"},
            "其他": {"fund", "index", "other"},
        }.get(market_type)
        brief_asset_type = _get_nested(
            research_brief,
            ["instrument", "asset_type"],
        )
        if (
            expected_asset_types is not None
            and brief_asset_type not in expected_asset_types
        ):
            errors.append(
                "market_type must match research_brief.instrument.asset_type"
            )

    errors.extend(
        _validate_evidence_against_brief(data.get("evidence_items"), research_brief)
    )
    errors.extend(_validate_scenario_analysis(data, required=require_scenarios))

    errors.extend(_validate_monitoring_boundaries(data))

    feedback_status = data.get("feedback_status")
    if feedback_status is not None and feedback_status not in SCHEMA["enums"]["feedback_status"]:
        errors.append(f"invalid feedback_status: {feedback_status}")

    portfolio_context = data.get("portfolio_context")
    holding_assessment = data.get("holding_assessment")
    portfolio_summary = data.get("portfolio_summary")
    portfolio_risk = data.get("portfolio_risk")
    portfolio_fit = data.get("portfolio_fit")
    if portfolio_context is not None and not isinstance(portfolio_context, dict):
        errors.append("portfolio_context must be an object when provided")
        portfolio_context = {}
    if holding_assessment is not None and not isinstance(holding_assessment, dict):
        errors.append("holding_assessment must be an object when provided")
        holding_assessment = {}

    has_position = False
    if isinstance(portfolio_context, dict):
        has_position = bool(portfolio_context.get("has_position"))
        weight_status = portfolio_context.get("weight_status")
        if weight_status and weight_status not in SCHEMA["enums"]["weight_status"]:
            errors.append(f"invalid portfolio_context.weight_status: {weight_status}")

    if portfolio_summary is not None:
        if not isinstance(portfolio_summary, dict):
            errors.append("portfolio_summary must be an object")
        else:
            for key in SCHEMA["required_portfolio_summary_fields"]:
                if portfolio_summary.get(key) in (None, "", []):
                    errors.append(f"missing portfolio_summary field: {key}")

    if portfolio_risk is not None:
        if not isinstance(portfolio_risk, dict):
            errors.append("portfolio_risk must be an object")
        else:
            for key in SCHEMA["required_portfolio_risk_fields"]:
                if portfolio_risk.get(key) in (None, "", []):
                    errors.append(f"missing portfolio_risk field: {key}")

    if portfolio_fit is not None:
        if not isinstance(portfolio_fit, dict):
            errors.append("portfolio_fit must be an object")
        else:
            for key in SCHEMA["required_portfolio_fit_fields"]:
                if portfolio_fit.get(key) in (None, "", []):
                    errors.append(f"missing portfolio_fit field: {key}")

    if has_position:
        if portfolio_context is None:
            errors.append("portfolio_context is required when user holds this stock")
        else:
            for key in SCHEMA["required_portfolio_context_fields_when_holding"]:
                if portfolio_context.get(key) in (None, "", []):
                    errors.append(f"missing portfolio_context field for holder: {key}")

        if holding_assessment is None:
            errors.append("holding_assessment is required when user holds this stock")
        else:
            for key in SCHEMA["required_holding_assessment_fields_when_holding"]:
                value = holding_assessment.get(key)
                if value in (None, "", []):
                    errors.append(f"missing holding_assessment field for holder: {key}")
            conditions = holding_assessment.get("monitoring_conditions", [])
            if not isinstance(conditions, list) or not conditions:
                errors.append(
                    "holding_assessment.monitoring_conditions must be a non-empty list"
                )

    chip_health = _get_nested(data, ["dashboard", "data_perspective", "chip_structure", "chip_health"])
    rules = SCHEMA["market_rules"].get(market_type)
    if rules:
        if rules["chip_structure_mode"] == "not_applicable":
            if chip_health != rules["chip_health_value"]:
                errors.append(f"chip_structure.chip_health must be '{rules['chip_health_value']}' for {market_type}")
        elif rules["chip_structure_mode"] == "enhanced_or_gap":
            if chip_health in (None, "", []):
                errors.append("A股 output requires chip_structure.chip_health")

    earnings_snapshot = data.get("earnings_snapshot")
    catalyst_map = data.get("catalyst_map")
    if earnings_snapshot is not None:
        if not isinstance(earnings_snapshot, dict):
            errors.append("earnings_snapshot must be an object when provided")
        else:
            for key in SCHEMA["required_earnings_snapshot_fields"]:
                if earnings_snapshot.get(key) in (None, ""):
                    errors.append(f"missing earnings_snapshot field: {key}")
    if catalyst_map is not None:
        if not isinstance(catalyst_map, dict):
            errors.append("catalyst_map must be an object when provided")
        else:
            for key in SCHEMA["required_catalyst_map_fields"]:
                value = catalyst_map.get(key)
                if value is None:
                    errors.append(f"missing catalyst_map field: {key}")
                elif not isinstance(value, list):
                    errors.append(f"catalyst_map.{key} must be a list")

    monitoring_alerts = data.get("monitoring_alerts")
    if monitoring_alerts is not None and not isinstance(monitoring_alerts, list):
        errors.append("monitoring_alerts must be a list when provided")

    claim_tracking = data.get("management_claim_tracking")
    if claim_tracking is not None:
        if not isinstance(claim_tracking, dict):
            errors.append("management_claim_tracking must be an object")
        else:
            for key in SCHEMA.get("required_management_claim_tracking_fields", []):
                if claim_tracking.get(key) in (None, ""):
                    errors.append(f"missing management_claim_tracking field: {key}")
            if claim_tracking.get("assessment_boundary") != "claim fulfillment only; no honesty or fraud inference":
                errors.append("management_claim_tracking assessment boundary is invalid")
            if claim_tracking.get("formal_use_allowed") is not True:
                errors.append("management_claim_tracking is not allowed for formal use")

    errors.extend(validate_math_consistency(data))

    return errors


def collect_dashboard_warnings(data: dict) -> list[str]:
    return collect_math_warnings(data)


def validate_file(path: str, *, require_scenarios: bool = False) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_dashboard(payload, require_scenarios=require_scenarios)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate stock dashboard JSON.")
    parser.add_argument("json_path")
    parser.add_argument(
        "--strict-current-contract",
        action="store_true",
        help="Require scenario_analysis for newly generated dashboards.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the stable JSON contract (JSON is also the default output).",
    )
    args = parser.parse_args()

    try:
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

    try:
        errors = validate_dashboard(
            payload,
            require_scenarios=args.strict_current_contract,
        )
        warnings = collect_dashboard_warnings(payload)
    except Exception as exc:
        report = {
            "status": "data_error",
            "detail_status": "dashboard_validation_error",
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    if errors:
        report = {
            "status": "invalid",
            "detail_status": "dashboard_contract_invalid",
            "valid": False,
            "errors": errors,
            "warnings": warnings,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report = {
        "status": "ok",
        "detail_status": "dashboard_contract_valid",
        "valid": True,
        "errors": [],
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
