from __future__ import annotations

import argparse
from datetime import datetime

from hub_utils import BLACKBOARD_PATH, dump_json, ensure_runtime_dirs, load_json


def now() -> str:
    return datetime.now().isoformat()


def init_blackboard() -> dict:
    ensure_runtime_dirs()
    state = {
        "initialized_at": now(),
        "phase": "idle",
        "status": "ready",
        "scan_stats": {},
        "signals": [],
        "adversarial_audit": None,
        "final_briefing": None,
    }
    dump_json(BLACKBOARD_PATH, state)
    return state


def load_blackboard() -> dict:
    return load_json(BLACKBOARD_PATH, init_blackboard())


def save_blackboard(state: dict) -> None:
    state["updated_at"] = now()
    dump_json(BLACKBOARD_PATH, state)


def update_phase(phase: str, status: str) -> dict:
    state = load_blackboard()
    state["phase"] = phase
    state["status"] = status
    save_blackboard(state)
    return state


def record_scan_stats(source_count: int, item_count: int) -> dict:
    state = load_blackboard()
    state["scan_stats"] = {
        "source_count": source_count,
        "item_count": item_count,
        "recorded_at": now(),
    }
    save_blackboard(state)
    return state


def append_signal(signal: dict) -> dict:
    state = load_blackboard()
    state.setdefault("signals", []).append(signal)
    save_blackboard(state)
    return state


def mark_adversarial_audit(audit: dict) -> dict:
    state = load_blackboard()
    state["adversarial_audit"] = audit
    save_blackboard(state)
    return state


def finalize_briefing(path: str) -> dict:
    state = load_blackboard()
    state["final_briefing"] = {"path": path, "finished_at": now()}
    state["phase"] = "done"
    state["status"] = "completed"
    save_blackboard(state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage intelligence hub blackboard.")
    parser.add_argument("action", choices=["init", "show", "phase"])
    parser.add_argument("--phase")
    parser.add_argument("--status")
    args = parser.parse_args()

    if args.action == "init":
        init_blackboard()
        print(f"[OK] initialized {BLACKBOARD_PATH}")
        return 0
    if args.action == "show":
        print(load_blackboard())
        return 0
    if args.action == "phase":
        update_phase(args.phase or "unknown", args.status or "running")
        print(f"[OK] phase={args.phase} status={args.status}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
