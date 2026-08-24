from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


TERMINAL_FAILURE_STATES = {
    "cancelled",
    "completed",
    "error",
    "exited",
    "failed",
    "interrupted",
}
MAX_GROWTH_CHECKS_WITHOUT_MILESTONE = 15


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("last_event_at must be timezone-aware")
    return parsed


def validate_fingerprint(value: dict[str, Any]) -> dict[str, Any]:
    ordinal = int(value["event_ordinal"])
    tool_calls = int(value["tool_call_count"])
    milestone_seq = int(value.get("milestone_seq", 0) or 0)
    last_event = _timestamp(value["last_event_at"])
    if ordinal < 0 or tool_calls < 0 or milestone_seq < 0:
        raise ValueError("fingerprint counters must be non-negative")
    return {
        "event_ordinal": ordinal,
        "last_event_at": last_event.isoformat(),
        "tool_call_count": tool_calls,
        "milestone_seq": milestone_seq,
    }


def evaluate_progress(
    state: dict[str, Any] | None,
    fingerprint: dict[str, Any],
    agent_status: str,
) -> tuple[dict[str, Any], str]:
    current = validate_fingerprint(fingerprint)
    status = str(agent_status).strip().lower()
    previous_state = state if isinstance(state, dict) else {}
    next_state = {
        "previous_fingerprint": current,
        "reminder_sent": bool(previous_state.get("reminder_sent", False)),
        "unchanged_after_reminder": int(
            previous_state.get("unchanged_after_reminder", 0) or 0
        ),
        "growth_checks_without_milestone": int(
            previous_state.get("growth_checks_without_milestone", 0) or 0
        ),
    }
    if status == "artifact_ready":
        return next_state, "verify_artifact"
    if status in TERMINAL_FAILURE_STATES:
        return next_state, "declare_lost"
    if status != "running":
        raise ValueError("agent_status must be running, artifact_ready, or terminal")

    raw_previous = previous_state.get("previous_fingerprint")
    if not isinstance(raw_previous, dict):
        next_state.update(
            reminder_sent=False,
            unchanged_after_reminder=0,
            growth_checks_without_milestone=0,
        )
        return next_state, "continue_wait"
    previous = validate_fingerprint(raw_previous)
    previous_time = _timestamp(previous["last_event_at"])
    current_time = _timestamp(current["last_event_at"])
    if (
        current["event_ordinal"] < previous["event_ordinal"]
        or current["tool_call_count"] < previous["tool_call_count"]
        or current["milestone_seq"] < previous["milestone_seq"]
        or current_time < previous_time
    ):
        raise ValueError("progress fingerprint cannot regress")
    changed = (
        current["event_ordinal"] > previous["event_ordinal"]
        or current["tool_call_count"] > previous["tool_call_count"]
        or current_time > previous_time
    )
    milestone_changed = current["milestone_seq"] > previous["milestone_seq"]
    if milestone_changed:
        next_state.update(
            reminder_sent=False,
            unchanged_after_reminder=0,
            growth_checks_without_milestone=0,
        )
        return next_state, "continue_wait"
    if changed:
        if next_state["reminder_sent"]:
            next_state["unchanged_after_reminder"] += 1
            if next_state["unchanged_after_reminder"] >= 3:
                return next_state, "declare_lost"
            return next_state, "continue_wait"
        next_state["growth_checks_without_milestone"] += 1
        if (
            next_state["growth_checks_without_milestone"]
            >= MAX_GROWTH_CHECKS_WITHOUT_MILESTONE
        ):
            next_state.update(reminder_sent=True, unchanged_after_reminder=0)
            return next_state, "send_reminder"
        return next_state, "continue_wait"
    if not next_state["reminder_sent"]:
        next_state.update(reminder_sent=True, unchanged_after_reminder=0)
        return next_state, "send_reminder"
    next_state["unchanged_after_reminder"] += 1
    if next_state["unchanged_after_reminder"] >= 3:
        return next_state, "declare_lost"
    return next_state, "continue_wait"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Persist and classify an independent review agent progress fingerprint."
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--agent-status", required=True)
    parser.add_argument("--event-ordinal", type=int, required=True)
    parser.add_argument("--last-event-at", required=True)
    parser.add_argument("--tool-call-count", type=int, required=True)
    parser.add_argument("--milestone-seq", type=int, default=0)
    args = parser.parse_args()
    try:
        state = (
            json.loads(args.state.read_text(encoding="utf-8"))
            if args.state.exists()
            else None
        )
        next_state, decision = evaluate_progress(
            state,
            {
                "event_ordinal": args.event_ordinal,
                "last_event_at": args.last_event_at,
                "tool_call_count": args.tool_call_count,
                "milestone_seq": args.milestone_seq,
            },
            args.agent_status,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    atomic_write_json(args.state, next_state)
    print(
        json.dumps(
            {"decision": decision, "state": next_state},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 4 if decision == "declare_lost" else 0


if __name__ == "__main__":
    raise SystemExit(main())
