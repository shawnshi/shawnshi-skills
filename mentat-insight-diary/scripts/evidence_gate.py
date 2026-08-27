#!/usr/bin/env python3
"""Deterministically gate Mentat evidence before OODA generation or saving."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SUBSTANTIVE_KINDS = {
    "execution",
    "state_change",
    "failure",
    "decision",
    "measured_result",
}
EXCLUDED_KINDS = {"plan", "journal_meta"}
ALLOWED_KINDS = SUBSTANTIVE_KINDS | EXCLUDED_KINDS
DIMENSIONS = ("facts", "results", "tradeoffs", "friction", "continuity")


def _present(event: dict[str, Any], field: str) -> bool:
    value = event.get(field)
    return isinstance(value, str) and bool(value.strip())


def _validate(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be an array")
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"events[{index}] must be an object")
        kind = event.get("kind")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"events[{index}].kind is invalid: {kind!r}")
        for required in ("summary", "source"):
            if not _present(event, required):
                raise ValueError(f"events[{index}].{required} must be a non-empty string")
    return events


def _dimension_scores(events: list[dict[str, Any]]) -> dict[str, int]:
    if not events:
        return {name: 0 for name in DIMENSIONS}

    facts = 2 if any(_present(event, "artifact_or_state") for event in events) else 1

    results = 0
    if any(_present(event, "result") for event in events):
        results = 1
    if any(
        _present(event, "result") and _present(event, "verification")
        for event in events
    ):
        results = 2

    tradeoffs = 0
    if any(_present(event, "decision") for event in events):
        tradeoffs = 1
    if any(
        _present(event, "decision")
        and _present(event, "rejected_alternative")
        and _present(event, "decision_basis")
        for event in events
    ):
        tradeoffs = 2

    friction = 0
    if any(_present(event, "issue") for event in events):
        friction = 1
    if any(
        _present(event, "issue")
        and _present(event, "effect")
        and _present(event, "resolution")
        for event in events
    ):
        friction = 2

    continuity = 0
    if any(_present(event, "next_trigger") for event in events):
        continuity = 1
    if any(
        _present(event, "next_trigger") and _present(event, "completion_standard")
        for event in events
    ):
        continuity = 2

    return {
        "facts": facts,
        "results": results,
        "tradeoffs": tradeoffs,
        "friction": friction,
        "continuity": continuity,
    }


def evaluate(payload: Any) -> dict[str, Any]:
    events = _validate(payload)
    substantive = [event for event in events if event["kind"] in SUBSTANTIVE_KINDS]
    excluded_count = len(events) - len(substantive)
    scores = _dimension_scores(substantive)
    total = sum(scores.values())

    if not substantive:
        status = "blocked_no_substantive_events"
        mode = "none"
        save_allowed = False
    elif total <= 3:
        status = "blocked_low_density"
        mode = "none"
        save_allowed = False
    elif total <= 6:
        status = "thin"
        mode = "thin"
        save_allowed = True
    else:
        status = "substantive"
        mode = "full"
        save_allowed = True

    missing_dimensions = [name for name, score in scores.items() if score == 0]
    return {
        "schema": "mentat-evidence-gate-v1",
        "status": status,
        "save_allowed": save_allowed,
        "ooda_mode": mode,
        "substantive_event_count": len(substantive),
        "excluded_event_count": excluded_count,
        "scores": scores,
        "total_score": total,
        "missing_dimensions": missing_dimensions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate structured Mentat evidence before OODA generation."
    )
    parser.add_argument("evidence_json", type=Path)
    args = parser.parse_args()

    try:
        payload = json.loads(args.evidence_json.read_text(encoding="utf-8"))
        result = evaluate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema": "mentat-evidence-gate-v1",
                    "status": "invalid_input",
                    "save_allowed": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
