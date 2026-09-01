from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from run_contract import load_review_progress_state, update_review_progress


TERMINAL_FAILURE_STATES = {
    "cancelled",
    "error",
    "exited",
    "failed",
    "interrupted",
}
TIMEOUT_STATES = {"timed_out", "timeout"}
MAX_GROWTH_CHECKS_WITHOUT_MILESTONE = 15
REVIEW_MILESTONE_LIMITS = {
    "semantic": 2,
    "red_team": 1,
    "supplement": 2,
}


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("last_event_at must be timezone-aware")
    return parsed


def _milestone_limit(review_kind: str | None) -> tuple[str | None, int]:
    if review_kind is None:
        return None, 2
    normalized = str(review_kind).strip().lower()
    if normalized not in REVIEW_MILESTONE_LIMITS:
        raise ValueError("review_kind must be semantic, red_team, or supplement")
    return normalized, REVIEW_MILESTONE_LIMITS[normalized]


def _validated_milestone_seq(value: Any, review_kind: str | None) -> int:
    milestone_seq = 0 if value is None else value
    if not isinstance(milestone_seq, int) or isinstance(milestone_seq, bool):
        raise ValueError("milestone_seq must be an integer")
    normalized_kind, maximum = _milestone_limit(review_kind)
    if milestone_seq < 0:
        raise ValueError("fingerprint counters must be non-negative")
    if milestone_seq > maximum:
        if normalized_kind is None:
            raise ValueError(f"milestone_seq must be at most {maximum}")
        raise ValueError(
            f"{normalized_kind} review milestone_seq must be at most {maximum}"
        )
    return milestone_seq


def validate_fingerprint(
    value: dict[str, Any],
    *,
    review_kind: str | None = None,
) -> dict[str, Any]:
    ordinal = value["event_ordinal"]
    tool_calls = value["tool_call_count"]
    if (
        not isinstance(ordinal, int)
        or isinstance(ordinal, bool)
        or not isinstance(tool_calls, int)
        or isinstance(tool_calls, bool)
    ):
        raise ValueError("fingerprint counters must be integers")
    milestone_seq = _validated_milestone_seq(
        value.get("milestone_seq", 0),
        review_kind,
    )
    last_event = _timestamp(value["last_event_at"])
    if ordinal < 0 or tool_calls < 0:
        raise ValueError("fingerprint counters must be non-negative")
    normalized = {
        "event_ordinal": ordinal,
        "last_event_at": last_event.isoformat(),
        "tool_call_count": tool_calls,
        "milestone_seq": milestone_seq,
    }
    watched = str(value.get("watched_artifacts_sha256") or "")
    if watched:
        if len(watched) != 64 or any(character not in "0123456789abcdef" for character in watched):
            raise ValueError("watched_artifacts_sha256 must be a lowercase SHA-256")
        normalized["watched_artifacts_sha256"] = watched
    if "watched_artifacts_ready" in value:
        ready = value["watched_artifacts_ready"]
        if not isinstance(ready, bool):
            raise ValueError("watched_artifacts_ready must be a boolean")
        normalized["watched_artifacts_ready"] = ready
    return normalized


def watched_artifacts_sha256(paths: list[Path]) -> str:
    observations = []
    for path in sorted((value.resolve() for value in paths), key=str):
        try:
            stat = path.stat()
        except FileNotFoundError:
            observations.append({"path": str(path), "exists": False})
            continue
        observations.append(
            {
                "path": str(path),
                "exists": True,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    encoded = json.dumps(
        observations,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def watched_artifacts_are_valid_json(paths: list[Path]) -> bool:
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            return False
        if not raw:
            return False
        try:
            json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
    return True


def derive_watch_fingerprint(
    state: dict[str, Any] | None,
    paths: list[Path],
    milestone_seq: int,
    *,
    observed_at: datetime | None = None,
    review_kind: str | None = None,
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one watch path is required")
    current_time = observed_at or datetime.now().astimezone()
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    previous_state = state if isinstance(state, dict) else {}
    previous_raw = previous_state.get("previous_fingerprint")
    previous = (
        validate_fingerprint(previous_raw, review_kind=review_kind)
        if isinstance(previous_raw, dict)
        else None
    )
    milestone_seq = _validated_milestone_seq(milestone_seq, review_kind)
    signature = watched_artifacts_sha256(paths)
    changed = signature != str(previous_state.get("watched_artifacts_sha256") or "")
    return {
        "event_ordinal": (previous["event_ordinal"] if previous else 0) + int(changed),
        "last_event_at": (
            current_time.isoformat()
            if changed or previous is None
            else previous["last_event_at"]
        ),
        "tool_call_count": previous["tool_call_count"] if previous else 0,
        "milestone_seq": milestone_seq,
        "watched_artifacts_sha256": signature,
        "watched_artifacts_ready": watched_artifacts_are_valid_json(paths),
    }


def evaluate_progress(
    state: dict[str, Any] | None,
    fingerprint: dict[str, Any],
    agent_status: str,
    *,
    review_kind: str | None = None,
    progress_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    current = validate_fingerprint(fingerprint, review_kind=review_kind)
    status = str(agent_status).strip().lower()
    normalized_kind, _ = _milestone_limit(review_kind)
    normalized_progress_id = str(progress_id or "").strip()
    if normalized_kind == "supplement" and not normalized_progress_id:
        raise ValueError("supplement progress requires progress_id")
    previous_state = state if isinstance(state, dict) else {}
    previous_progress_id = str(previous_state.get("progress_id") or "").strip()
    if previous_progress_id and normalized_progress_id != previous_progress_id:
        raise ValueError("progress identity changed")
    next_state = {
        "previous_fingerprint": current,
        "watched_artifacts_sha256": current.get("watched_artifacts_sha256"),
        "reminder_sent": bool(previous_state.get("reminder_sent", False)),
        "reminder_reason": previous_state.get("reminder_reason"),
        "unchanged_after_reminder": int(
            previous_state.get("unchanged_after_reminder", 0) or 0
        ),
        "growth_checks_without_milestone": int(
            previous_state.get("growth_checks_without_milestone", 0) or 0
        ),
    }
    if normalized_progress_id:
        next_state["progress_id"] = normalized_progress_id
    if "watched_artifacts_ready" in current:
        next_state["watched_artifacts_ready"] = current["watched_artifacts_ready"]
    if status == "artifact_ready":
        return next_state, "verify_artifact"
    if status == "completed":
        if current.get("watched_artifacts_ready") is True:
            return next_state, "verify_artifact"
        return next_state, "declare_lost"
    if status in TIMEOUT_STATES:
        return next_state, "degraded_timeout"
    if status in TERMINAL_FAILURE_STATES:
        return next_state, "declare_lost"
    if status != "running":
        raise ValueError(
            "agent_status must be running, artifact_ready, completed, timed_out, or terminal"
        )

    raw_previous = previous_state.get("previous_fingerprint")
    if not isinstance(raw_previous, dict):
        next_state.update(
            reminder_sent=False,
            reminder_reason=None,
            unchanged_after_reminder=0,
            growth_checks_without_milestone=0,
        )
        return next_state, "continue_wait"
    previous = validate_fingerprint(raw_previous, review_kind=review_kind)
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
        or current.get("watched_artifacts_sha256")
        != previous.get("watched_artifacts_sha256")
    )
    milestone_changed = current["milestone_seq"] > previous["milestone_seq"]
    if milestone_changed:
        next_state.update(
            reminder_sent=False,
            reminder_reason=None,
            unchanged_after_reminder=0,
            growth_checks_without_milestone=0,
        )
        return next_state, "continue_wait"
    if changed:
        if next_state["reminder_sent"]:
            reminder_reason = next_state.get("reminder_reason")
            if reminder_reason is None:
                reminder_reason = (
                    "growth_limit"
                    if next_state["growth_checks_without_milestone"]
                    >= MAX_GROWTH_CHECKS_WITHOUT_MILESTONE
                    else "stalled"
                )
            if reminder_reason == "growth_limit":
                next_state["unchanged_after_reminder"] += 1
                if next_state["unchanged_after_reminder"] >= 3:
                    return next_state, "declare_lost"
                return next_state, "continue_wait"
            next_state.update(
                reminder_sent=False,
                reminder_reason=None,
                unchanged_after_reminder=0,
                growth_checks_without_milestone=1,
            )
            return next_state, "continue_wait"
        next_state["growth_checks_without_milestone"] += 1
        if (
            next_state["growth_checks_without_milestone"]
            >= MAX_GROWTH_CHECKS_WITHOUT_MILESTONE
        ):
            next_state.update(
                reminder_sent=True,
                reminder_reason="growth_limit",
                unchanged_after_reminder=0,
            )
            return next_state, "send_reminder"
        return next_state, "continue_wait"
    if not next_state["reminder_sent"]:
        next_state.update(
            reminder_sent=True,
            reminder_reason="stalled",
            unchanged_after_reminder=0,
        )
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
    parser.add_argument("--event-ordinal", type=int)
    parser.add_argument("--last-event-at")
    parser.add_argument("--tool-call-count", type=int)
    parser.add_argument("--milestone-seq", type=int, default=0)
    parser.add_argument("--review-kind", choices=sorted(REVIEW_MILESTONE_LIMITS))
    parser.add_argument("--progress-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--invocation-id")
    parser.add_argument("--request-sha256")
    parser.add_argument("--watch-path", action="append", type=Path, default=[])
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    try:
        if args.manifest is not None:
            if args.review_kind == "supplement":
                raise ValueError("supplement progress uses an isolated state file without --manifest")
            if (
                args.review_kind is None
                or not str(args.invocation_id or "").strip()
                or not str(args.request_sha256 or "").strip()
            ):
                raise ValueError(
                    "--manifest requires --review-kind, --invocation-id and --request-sha256"
                )
            state = load_review_progress_state(
                args.manifest,
                args.review_kind,
                args.invocation_id,
                args.request_sha256,
            )
        else:
            state = (
                json.loads(args.state.read_text(encoding="utf-8"))
                if args.state.exists()
                else None
            )
        if args.watch_path:
            observed_at = _timestamp(args.observed_at) if args.observed_at else None
            fingerprint = derive_watch_fingerprint(
                state,
                args.watch_path,
                args.milestone_seq,
                observed_at=observed_at,
                review_kind=args.review_kind,
            )
        else:
            if (
                args.event_ordinal is None
                or args.last_event_at is None
                or args.tool_call_count is None
            ):
                raise ValueError(
                    "event telemetry or at least one --watch-path is required"
                )
            fingerprint = {
                "event_ordinal": args.event_ordinal,
                "last_event_at": args.last_event_at,
                "tool_call_count": args.tool_call_count,
                "milestone_seq": args.milestone_seq,
            }
        if args.manifest is not None:
            next_state, decision = update_review_progress(
                args.manifest,
                args.review_kind,
                args.invocation_id,
                args.request_sha256,
                args.state,
                fingerprint,
                args.agent_status,
                evaluate_progress,
            )
        else:
            next_state, decision = evaluate_progress(
                state,
                fingerprint,
                args.agent_status,
                review_kind=args.review_kind,
                progress_id=args.progress_id,
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))
    if args.manifest is None:
        next_state["last_decision"] = decision
        if decision in {"degraded_timeout", "declare_lost"}:
            next_state["terminal_status"] = decision
            next_state["recorded_at"] = fingerprint["last_event_at"]
    mirror_error = None
    try:
        atomic_write_json(args.state, next_state)
    except OSError as exc:
        if args.manifest is None:
            parser.error(str(exc))
        mirror_error = f"{type(exc).__name__}: {exc}"
    result = {"decision": decision, "state": next_state}
    if mirror_error is not None:
        result["state_mirror_error"] = mirror_error
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if decision == "declare_lost":
        return 4
    if decision == "degraded_timeout":
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
