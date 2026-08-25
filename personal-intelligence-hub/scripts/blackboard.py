from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from hub_utils import BLACKBOARD_PATH, atomic_dump_json, load_json


def now() -> str:
    return datetime.now().isoformat()


def _resolve_blackboard_path(blackboard_path: str | Path | None) -> Path:
    return Path(blackboard_path) if blackboard_path is not None else BLACKBOARD_PATH


def init_blackboard(blackboard_path: str | Path | None = None) -> dict:
    target = _resolve_blackboard_path(blackboard_path)
    state = {
        "initialized_at": now(),
        "phase": "idle",
        "status": "ready",
        "scan_stats": {},
        "signals": [],
        "adversarial_audit": None,
        "final_briefing": None,
    }
    atomic_dump_json(target, state)
    return state


def load_blackboard(blackboard_path: str | Path | None = None) -> dict:
    target = _resolve_blackboard_path(blackboard_path)
    if not target.exists():
        return init_blackboard(blackboard_path=target)
    return load_json(target, {})


def save_blackboard(
    state: dict,
    blackboard_path: str | Path | None = None,
) -> None:
    target = _resolve_blackboard_path(blackboard_path)
    state["updated_at"] = now()
    atomic_dump_json(target, state)


def update_phase(
    phase: str,
    status: str,
    blackboard_path: str | Path | None = None,
) -> dict:
    state = load_blackboard(blackboard_path=blackboard_path)
    state["phase"] = phase
    state["status"] = status
    save_blackboard(state, blackboard_path=blackboard_path)
    return state


def record_scan_stats(
    source_count: int,
    item_count: int,
    blackboard_path: str | Path | None = None,
) -> dict:
    state = load_blackboard(blackboard_path=blackboard_path)
    state["scan_stats"] = {
        "source_count": source_count,
        "item_count": item_count,
        "recorded_at": now(),
    }
    save_blackboard(state, blackboard_path=blackboard_path)
    return state


def append_signal(
    signal: dict,
    blackboard_path: str | Path | None = None,
) -> dict:
    state = load_blackboard(blackboard_path=blackboard_path)
    state.setdefault("signals", []).append(signal)
    save_blackboard(state, blackboard_path=blackboard_path)
    return state


def mark_adversarial_audit(
    audit: dict,
    blackboard_path: str | Path | None = None,
) -> dict:
    state = load_blackboard(blackboard_path=blackboard_path)
    state["adversarial_audit"] = audit
    save_blackboard(state, blackboard_path=blackboard_path)
    return state


def finalize_briefing(
    path: str,
    blackboard_path: str | Path | None = None,
) -> dict:
    state = load_blackboard(blackboard_path=blackboard_path)
    state["final_briefing"] = {"path": path, "finished_at": now()}
    state["phase"] = "done"
    state["status"] = "completed"
    save_blackboard(state, blackboard_path=blackboard_path)
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
