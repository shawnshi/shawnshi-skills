#!/usr/bin/env python3
"""Validate interpretive labels against the published vocabulary (P1-4).

Why this exists: labels such as ``deteriorating`` / ``watch`` / ``stable`` and
``intact_with_risks`` / ``materially_weakened`` were free prose, so the same evidence
could be labelled differently between runs and label drift was unmeasurable.

Boundaries: this is a vocabulary and consistency check, not a judgement engine.  It
never derives a label, never overrides a machine gate status, and refuses an
assignment whose strength is not backed by evidence.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
VOCAB_PATH = SKILL_DIR / "references" / "interpretive_labels.json"
DECISION_SCOPE = "advisory"
ASSIGNMENT_SCHEMA = "pia_label_assignment_v1"


class LabelError(RuntimeError):
    pass


def load_vocabulary(path: Path | None = None) -> dict[str, Any]:
    target = path or VOCAB_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LabelError(f"vocabulary unreadable: {target}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("axes"), dict):
        raise LabelError("vocabulary must contain an 'axes' object")
    return payload


def axis_labels(vocabulary: dict[str, Any], axis: str) -> dict[str, Any]:
    axes = vocabulary.get("axes") or {}
    if axis not in axes:
        raise LabelError(f"unknown axis {axis!r}; available: {', '.join(sorted(axes))}")
    labels = (axes[axis] or {}).get("labels")
    if not isinstance(labels, dict) or not labels:
        raise LabelError(f"axis {axis!r} declares no labels")
    return labels


def validate_assignments(payload: Any, vocabulary: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise LabelError("assignment file must be a JSON object")
    axis = str(payload.get("axis") or "").strip()
    labels = axis_labels(vocabulary, axis)
    as_of = str(payload.get("as_of") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        errors.append("as_of must be an ISO date")
    else:
        try:
            datetime.date.fromisoformat(as_of)
        except ValueError:
            errors.append("as_of is not a real date")
    assignments = payload.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        errors.append("assignments must be a non-empty list")
        assignments = []
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for index, assignment in enumerate(assignments):
        prefix = f"assignments[{index}]"
        if not isinstance(assignment, dict):
            errors.append(f"{prefix} must be an object")
            continue
        symbol = str(assignment.get("symbol") or "").strip().upper()
        if not symbol:
            errors.append(f"{prefix}.symbol is required")
            continue
        if symbol in seen:
            errors.append(f"{prefix}.symbol is duplicated: {symbol}")
        seen.add(symbol)
        label = str(assignment.get("label") or "").strip()
        rule = labels.get(label)
        if rule is None:
            errors.append(
                f"{prefix}.label {label!r} is not in the {axis} vocabulary: "
                f"{', '.join(sorted(labels))}")
            continue
        counts[label] = counts.get(label, 0) + 1
        if not str(assignment.get("rationale") or "").strip():
            errors.append(f"{prefix}.rationale is required")
        evidence_ids = assignment.get("evidence_ids")
        if rule.get("requires_evidence_ids"):
            if (not isinstance(evidence_ids, list) or not evidence_ids
                    or not all(isinstance(item, str) and item.strip() for item in evidence_ids)):
                errors.append(
                    f"{prefix}.evidence_ids is required for label {label!r}")
        elif evidence_ids not in (None, []):
            # insufficient_evidence may cite what was checked, but must not imply support.
            if not all(isinstance(item, str) for item in evidence_ids or []):
                errors.append(f"{prefix}.evidence_ids must be a list of strings")
        if rule.get("requires_trigger_evidence"):
            trigger = assignment.get("trigger_evidence")
            if not isinstance(trigger, list) or not trigger:
                errors.append(
                    f"{prefix}.trigger_evidence is required for the strong label {label!r}")
    summary = {"axis": axis, "as_of": as_of, "assignment_count": len(seen),
               "label_counts": counts,
               "vocabulary": {label: labels[label]["definition"] for label in sorted(labels)}}
    return errors, summary


def compute_drift(previous: Any, current: Any) -> dict[str, Any]:
    def mapping(payload: Any) -> dict[str, str]:
        rows = (payload or {}).get("assignments") if isinstance(payload, dict) else None
        return {str(row.get("symbol")).upper(): str(row.get("label"))
                for row in rows or [] if isinstance(row, dict) and row.get("symbol")}

    before, after = mapping(previous), mapping(current)
    changed = {symbol: {"from": before[symbol], "to": after[symbol]}
               for symbol in sorted(set(before) & set(after)) if before[symbol] != after[symbol]}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    return {"changed": changed, "added": added, "removed": removed,
            "compared": len(set(before) & set(after))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interpretive label vocabulary checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    vocab = subparsers.add_parser("vocab", help="Print the allowed labels for an axis.")
    vocab.add_argument("--axis", required=True)
    vocab.add_argument("--vocabulary-file")
    check = subparsers.add_parser("check", help="Validate a label assignment file.")
    check.add_argument("--file", required=True)
    check.add_argument("--previous", help="Optional earlier assignment file for drift.")
    check.add_argument("--vocabulary-file")
    args = parser.parse_args(argv)
    try:
        vocabulary = load_vocabulary(Path(args.vocabulary_file).expanduser().resolve()
                                     if getattr(args, "vocabulary_file", None) else None)
        if args.command == "vocab":
            labels = axis_labels(vocabulary, args.axis)
            print(json.dumps({"status": "complete", "detail_status": "vocabulary_listed",
                              "decision_scope": DECISION_SCOPE, "axis": args.axis,
                              "labels": labels}, ensure_ascii=False, indent=2))
            return 0
        payload = json.loads(Path(args.file).expanduser().resolve().read_text(encoding="utf-8"))
        errors, summary = validate_assignments(payload, vocabulary)
        drift = None
        if args.previous:
            previous = json.loads(Path(args.previous).expanduser().resolve()
                                  .read_text(encoding="utf-8"))
            drift = compute_drift(previous, payload)
        report = {
            "status": "failed" if errors else "complete",
            "detail_status": "label_assignment_invalid" if errors else "label_assignment_valid",
            "decision_scope": DECISION_SCOPE,
            "schema_version": ASSIGNMENT_SCHEMA,
            "errors": errors,
            **summary,
        }
        if drift is not None:
            report["label_drift"] = drift
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 3 if errors else 0
    except (LabelError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "detail_status": "label_check_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
