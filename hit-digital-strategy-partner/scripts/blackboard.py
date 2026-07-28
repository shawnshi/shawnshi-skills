import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

BLACKBOARD_RELATIVE = Path("tmp") / "strategy_blackboard.json"
ASSUMPTION_FIELDS = {
    "name",
    "value",
    "unit",
    "source",
    "as_of",
    "region",
    "status",
}


def blackboard_path(workspace_root: Path) -> Path:
    return workspace_root / BLACKBOARD_RELATIVE


def default_state(topic: str, mode: str) -> dict:
    return {
        "metadata": {
            "schema_version": 1,
            "updated_at": datetime.now().isoformat(),
            "status": "draft",
            "topic": topic,
            "mode": mode,
        },
        "alignment": {
            "decision": "",
            "audience": "",
            "time_horizon": "",
            "budget": "",
            "success_metrics": [],
            "constraints": [],
            "mode": mode,
        },
        "evidence": {
            "facts": [],
            "policy": [],
            "market": [],
            "vendor": [],
            "clinical": [],
        },
        "logic_mesh": {
            "alternatives": [],
            "conflicts": [],
            "core_judgment": "",
            "counter_evidence": [],
        },
        "decisions": {
            "recommendation": "",
            "action_levers": [],
            "quantitative_model": {
                "assumptions": [],
                "scenarios": [],
            },
            "residual_risks": [],
            "roadmap": [],
        },
        "deliverables": {
            "project_path": "",
            "implementation_plan": "",
            "outline": "",
            "final_report": "",
        },
    }


def load_state(workspace_root: Path) -> tuple[Path, dict]:
    path = blackboard_path(workspace_root)
    if not path.exists():
        return path, default_state("Untitled", "deep-dive")
    with path.open("r", encoding="utf-8") as handle:
        return path, json.load(handle)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.setdefault("metadata", {})["updated_at"] = datetime.now().isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def validate_state(state: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(state, dict):
        return {
            "status": "invalid",
            "ready": False,
            "errors": ["blackboard root must be a JSON object"],
            "warnings": [],
        }

    for section in ("metadata", "alignment", "evidence", "logic_mesh", "decisions"):
        if not isinstance(state.get(section), dict):
            errors.append(f"{section} must be a JSON object")

    if errors:
        return {
            "status": "invalid",
            "ready": False,
            "errors": errors,
            "warnings": warnings,
        }

    schema_version = state["metadata"].get("schema_version")
    if schema_version != 1:
        errors.append("metadata.schema_version must equal 1")

    assumptions = (
        state["decisions"].get("quantitative_model", {}).get("assumptions", [])
        if isinstance(state["decisions"].get("quantitative_model", {}), dict)
        else None
    )
    if not isinstance(assumptions, list):
        errors.append("decisions.quantitative_model.assumptions must be a list")
    else:
        for index, assumption in enumerate(assumptions):
            if not isinstance(assumption, dict):
                errors.append(f"assumptions[{index}] must be an object")
                continue
            missing_fields = sorted(ASSUMPTION_FIELDS - set(assumption))
            if missing_fields:
                errors.append(
                    f"assumptions[{index}] missing fields: {', '.join(missing_fields)}"
                )
                continue
            if assumption["status"] not in {"sourced", "needs_input"}:
                errors.append(
                    f"assumptions[{index}].status must be sourced or needs_input"
                )
            if assumption["status"] == "sourced":
                for field in ("value", "unit", "source", "as_of", "region"):
                    if assumption.get(field) in (None, ""):
                        errors.append(
                            f"assumptions[{index}].{field} is required when status=sourced"
                        )
            elif assumption.get("value") not in (None, ""):
                errors.append(
                    f"assumptions[{index}].value must be null when status=needs_input"
                )

    alignment = state["alignment"]
    for field in ("decision", "audience", "time_horizon", "budget", "mode"):
        if not str(alignment.get(field, "")).strip():
            warnings.append(f"alignment.{field} is not filled")
    if not alignment.get("success_metrics"):
        warnings.append("alignment.success_metrics is empty")
    if not any(state["evidence"].get(key) for key in ("facts", "policy", "market", "vendor", "clinical")):
        warnings.append("evidence contains no reviewed source records")
    if not str(state["logic_mesh"].get("core_judgment", "")).strip():
        warnings.append("logic_mesh.core_judgment is empty")
    if not str(state["decisions"].get("recommendation", "")).strip():
        warnings.append("decisions.recommendation is empty")
    if not state["decisions"].get("residual_risks"):
        warnings.append("decisions.residual_risks is empty")

    ready = not errors and not warnings
    return {
        "status": "ready" if ready else ("invalid" if errors else "draft"),
        "ready": ready,
        "errors": errors,
        "warnings": warnings,
    }


def update_section(state: dict, section: str, key: str | None, value, action: str) -> dict:
    if section not in state:
        state[section] = {}
    target = state[section]
    if key:
        if action == "append":
            target.setdefault(key, [])
            if not isinstance(target[key], list):
                raise ValueError(f"{section}.{key} is not a list")
            target[key].append(value)
        else:
            target[key] = value
    else:
        if not isinstance(value, dict):
            raise ValueError("Section-level updates require a JSON object")
        if not isinstance(target, dict):
            raise ValueError(f"{section} is not an object")
        target.update(value)
    return state


def cmd_init(args):
    path = blackboard_path(args.workspace_root)
    state = default_state(args.topic, args.mode)
    save_state(path, state)
    print(json.dumps({"status": "initialized", "path": str(path), "mode": args.mode, "topic": args.topic}, ensure_ascii=False, indent=2))


def cmd_update(args):
    path, state = load_state(args.workspace_root)
    state = update_section(state, args.section, args.key, parse_value(args.value), args.action)
    state.setdefault("metadata", {})["status"] = "draft"
    save_state(path, state)
    print(json.dumps({"status": "updated", "path": str(path), "section": args.section, "key": args.key}, ensure_ascii=False, indent=2))


def cmd_status(args):
    path, state = load_state(args.workspace_root)
    print(json.dumps({"path": str(path), "state": state}, ensure_ascii=False, indent=2))


def cmd_validate(args):
    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and report["errors"]:
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Strategy Blackboard State Machine")
    parser.add_argument("--workspace-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--topic", required=True)
    p_init.add_argument("--mode", default="deep-dive", choices=["brief", "deep-dive", "board-memo"])
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update")
    p_update.add_argument("--section", required=True, choices=["metadata", "alignment", "evidence", "logic_mesh", "decisions", "deliverables"])
    p_update.add_argument("--key")
    p_update.add_argument("--value", required=True)
    p_update.add_argument("--action", choices=["set", "append"], default="set")
    p_update.set_defaults(func=cmd_update)

    p_status = sub.add_parser("status")
    p_status.set_defaults(func=cmd_status)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--strict", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    p_ready = sub.add_parser("ready")
    p_ready.add_argument("--strict", action="store_true")
    p_ready.set_defaults(func=cmd_validate)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
