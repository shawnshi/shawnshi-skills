import json
from pathlib import Path

from dashboard_math_gate import validate_math_consistency


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "resources" / "dashboard_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _get_nested(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


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
    return errors


def validate_dashboard(data: dict) -> list[str]:
    errors = []

    for key in SCHEMA["required_top_level"]:
        if key not in data:
            errors.append(f"missing top-level field: {key}")

    market_type = data.get("market_type")
    if market_type not in SCHEMA["enums"]["market_type"]:
        errors.append(f"invalid market_type: {market_type}")

    research_mode = data.get("research_mode")
    if research_mode not in SCHEMA["enums"]["research_mode"]:
        errors.append(f"invalid research_mode: {research_mode}")

    for key in ["decision_type", "confidence_level", "operation_advice", "trend_prediction"]:
        if data.get(key) not in SCHEMA["enums"][key]:
            errors.append(f"invalid {key}: {data.get(key)}")

    dashboard = data.get("dashboard", {})
    for key in SCHEMA["required_dashboard_sections"]:
        if key not in dashboard:
            errors.append(f"missing dashboard section: {key}")

    for key in SCHEMA["required_core_conclusion_fields"]:
        if _get_nested(data, ["dashboard", "core_conclusion", key]) in (None, "", []):
            errors.append(f"missing core_conclusion field: {key}")

    for key in SCHEMA["required_battle_plan_fields"]:
        if _get_nested(data, ["dashboard", "battle_plan", key]) in (None, "", []):
            errors.append(f"missing battle_plan field: {key}")

    for key in SCHEMA["required_data_perspective_fields"]:
        if _get_nested(data, ["dashboard", "data_perspective", key]) in (None, "", []):
            errors.append(f"missing data_perspective field: {key}")

    for key in SCHEMA["required_confidence_fields"]:
        if _get_nested(data, ["confidence_details", key]) in (None, "", []):
            errors.append(f"missing confidence_details field: {key}")

    for key in SCHEMA["required_freshness_fields"]:
        if _get_nested(data, ["freshness_flags", key]) in (None, ""):
            errors.append(f"missing freshness_flags field: {key}")

    stale_inputs = _get_nested(data, ["freshness_flags", "stale_inputs"], [])
    if not isinstance(stale_inputs, list):
        errors.append("freshness_flags.stale_inputs must be a list")

    errors.extend(_validate_evidence_items(data.get("evidence_items")))

    if not _get_nested(data, ["dashboard", "core_conclusion", "one_sentence"]):
        errors.append("core_conclusion.one_sentence cannot be empty")

    checklist = _get_nested(data, ["dashboard", "battle_plan", "action_checklist"], [])
    if not isinstance(checklist, list) or len(checklist) == 0:
        errors.append("battle_plan.action_checklist must be a non-empty list")

    data_sources = data.get("data_sources")
    if not isinstance(data_sources, (list, str, dict)):
        errors.append("data_sources must be list, string, or dict")

    data_gaps = data.get("data_gaps")
    if not isinstance(data_gaps, list):
        errors.append("data_gaps must be a list")

    feedback_status = data.get("feedback_status")
    if feedback_status is not None and feedback_status not in SCHEMA["enums"]["feedback_status"]:
        errors.append(f"invalid feedback_status: {feedback_status}")

    portfolio_context = data.get("portfolio_context")
    position_advice = data.get("position_advice")
    portfolio_summary = data.get("portfolio_summary")
    portfolio_risk = data.get("portfolio_risk")
    portfolio_fit = data.get("portfolio_fit")
    if portfolio_context is not None and not isinstance(portfolio_context, dict):
        errors.append("portfolio_context must be an object when provided")
        portfolio_context = {}
    if position_advice is not None and not isinstance(position_advice, dict):
        errors.append("position_advice must be an object when provided")
        position_advice = {}

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

        if position_advice is None:
            errors.append("position_advice is required when user holds this stock")
        else:
            for key in SCHEMA["required_position_advice_fields_when_holding"]:
                if position_advice.get(key) in (None, "", []):
                    errors.append(f"missing position_advice field for holder: {key}")
            triggers = position_advice.get("next_action_trigger", [])
            if not isinstance(triggers, list) or len(triggers) == 0:
                errors.append("position_advice.next_action_trigger must be a non-empty list")

        holder_summary = _get_nested(data, ["dashboard", "core_conclusion", "position_advice", "has_position"])
        if holder_summary in (None, "", []):
            errors.append("dashboard.core_conclusion.position_advice.has_position is required when user holds this stock")

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
    if research_mode == "thesis_mode":
        if not isinstance(earnings_snapshot, dict):
            errors.append("earnings_snapshot is required in thesis_mode")
        else:
            for key in SCHEMA["required_earnings_snapshot_fields"]:
                if earnings_snapshot.get(key) in (None, ""):
                    errors.append(f"missing earnings_snapshot field: {key}")
        if not isinstance(catalyst_map, dict):
            errors.append("catalyst_map is required in thesis_mode")
        else:
            for key in SCHEMA["required_catalyst_map_fields"]:
                value = catalyst_map.get(key)
                if value is None:
                    errors.append(f"missing catalyst_map field: {key}")
                elif not isinstance(value, list):
                    errors.append(f"catalyst_map.{key} must be a list")

    watchlist_alerts = data.get("watchlist_alerts")
    if watchlist_alerts is not None and not isinstance(watchlist_alerts, list):
        errors.append("watchlist_alerts must be a list when provided")

    errors.extend(validate_math_consistency(data))

    return errors


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
    if errors:
        print("[FAIL] dashboard gate blocked archive")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

    print("[PASS] dashboard gate passed")
    sys.exit(0)
