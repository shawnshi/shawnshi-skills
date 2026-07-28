import json
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


def validate_dashboard(data: dict) -> list[str]:
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


def validate_file(path: str) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_dashboard(payload)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Validate stock dashboard JSON.")
    parser.add_argument("json_path")
    args = parser.parse_args()

    errors = validate_file(args.json_path)
    payload = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    for warning in collect_dashboard_warnings(payload):
        print(f"[WARN] {warning}")
    if errors:
        print("[FAIL] dashboard gate blocked archive")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

    print("[PASS] dashboard gate passed")
    sys.exit(0)
