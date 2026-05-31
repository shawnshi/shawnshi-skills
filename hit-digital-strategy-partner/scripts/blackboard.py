import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

DEFAULT_WORKSPACE_ROOT = Path(r"C:/Users/shich/.gemini")
BLACKBOARD_RELATIVE = Path("tmp") / "strategy_blackboard.json"


def blackboard_path(workspace_root: Path) -> Path:
    return workspace_root / BLACKBOARD_RELATIVE


def default_state(topic: str, mode: str) -> dict:
    return {
        "metadata": {
            "version": "V18.0",
            "timestamp": datetime.now().isoformat(),
            "status": "INIT",
            "topic": topic,
            "mode": mode,
        },
        "alignment": {
            "audience": "",
            "budget": "",
            "attack_focus": "",
            "target_words": "",
            "mode": mode,
        },
        "evidence": {
            "policy": [],
            "market": [],
            "competitor": [],
            "clinical": [],
        },
        "logic_mesh": {
            "conflicts": [],
            "connections": [],
            "core_judgment": "",
            "second_hop_inferences": [],
        },
        "decisions": {
            "action_levers": [],
            "pessimistic_roi": {},
            "residual_risks": [],
            "approved_outline": [],
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
    state.setdefault("metadata", {})["timestamp"] = datetime.now().isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def validate_state(state: dict) -> dict:
    checks = {
        "alignment_complete": all(
            str(state.get("alignment", {}).get(key, "")).strip()
            for key in ("audience", "budget", "attack_focus", "target_words", "mode")
        ),
        "policy_evidence": bool(state.get("evidence", {}).get("policy")),
        "market_evidence": bool(state.get("evidence", {}).get("market")),
        "competitor_evidence": bool(state.get("evidence", {}).get("competitor")),
        "core_judgment": bool(str(state.get("logic_mesh", {}).get("core_judgment", "")).strip()),
        "second_hop_inference": bool(state.get("logic_mesh", {}).get("second_hop_inferences")),
        "action_levers": bool(state.get("decisions", {}).get("action_levers")),
        "pessimistic_roi": bool(state.get("decisions", {}).get("pessimistic_roi")),
        "residual_risks": bool(state.get("decisions", {}).get("residual_risks")),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "status": "ready" if not missing else "blocked",
        "ready": not missing,
        "checks": checks,
        "missing": missing,
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
    state.setdefault("metadata", {})["status"] = "UPDATED"
    save_state(path, state)
    print(json.dumps({"status": "updated", "path": str(path), "section": args.section, "key": args.key}, ensure_ascii=False, indent=2))


def cmd_status(args):
    path, state = load_state(args.workspace_root)
    print(json.dumps({"path": str(path), "state": state}, ensure_ascii=False, indent=2))


def cmd_validate(args):
    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    if report["ready"]:
        state.setdefault("metadata", {})["status"] = "READY_FOR_DRAFT"
        save_state(path, state)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["ready"]:
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(description="Strategy Blackboard State Machine")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
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
