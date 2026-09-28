#!/usr/bin/env python3
"""Versioned ledger of user-confirmed thesis conditions (P1-6).

Why this exists: red teams repeatedly stopped at "the user-confirmed condition
history is missing", because the conditions lived in prose or in a sidecar file
with no confirmation dates.  This ledger stores each confirmed condition set as a
version with its confirmation date and source locator, so a review can ask "what
was effective on date X" instead of re-asking the user.

Boundaries: only user-confirmed entries are appended; a confirmation date and a
source locator are mandatory and backdating is refused.  The ledger does not
evaluate conditions and does not decide that a thesis is safe.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_thesis_ledger_v1"
DECISION_SCOPE = "research_only"
OPERATORS = {"lt", "lte", "gt", "gte", "eq", "qualitative"}
THRESHOLD_FREE_OPERATORS = {"eq", "qualitative"}
RESERVED_LOCATORS = ("example.com", "example.test", ".invalid", "localhost")


class LedgerError(RuntimeError):
    pass


def iso_date(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise LedgerError(f"{label} must be an ISO date, got {value!r}")
    try:
        datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise LedgerError(f"{label} is not a real date: {text}") from exc
    return text


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise LedgerError(f"ledger not found: {path} (run 'init' first)")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise LedgerError(f"ledger is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(f"ledger schema_version must be {SCHEMA_VERSION}")
    if not isinstance(payload.get("symbols"), dict):
        raise LedgerError("ledger.symbols must be an object")
    return payload


def write_ledger(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def validate_conditions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise LedgerError("conditions must be a non-empty list")
    seen: set[str] = set()
    conditions: list[dict[str, Any]] = []
    for index, condition in enumerate(raw):
        prefix = f"conditions[{index}]"
        if not isinstance(condition, dict):
            raise LedgerError(f"{prefix} must be an object")
        condition_id = str(condition.get("id") or "").strip()
        if not condition_id:
            raise LedgerError(f"{prefix}.id is required")
        if condition_id in seen:
            raise LedgerError(f"{prefix}.id is duplicated: {condition_id}")
        seen.add(condition_id)
        metric = str(condition.get("metric") or "").strip()
        if not metric:
            raise LedgerError(f"{prefix}.metric is required")
        operator = str(condition.get("operator") or "").strip()
        if operator not in OPERATORS:
            raise LedgerError(f"{prefix}.operator must be one of {sorted(OPERATORS)}")
        if operator not in THRESHOLD_FREE_OPERATORS:
            threshold = condition.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                raise LedgerError(
                    f"{prefix}.threshold must be a number for operator {operator!r} "
                    "(use operator 'qualitative' for a rule that has no number)")
        due_raw = str(condition.get("due") or "").strip()
        if not due_raw:
            raise LedgerError(f"{prefix}.due is required (an ISO date or '持续')")
        due = due_raw
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_raw):
            due = iso_date(due_raw, f"{prefix}.due")
        channel = str(condition.get("channel") or "").strip()
        if not channel:
            raise LedgerError(f"{prefix}.channel is required (what must be watched)")
        entry = {"id": condition_id, "metric": metric, "operator": operator,
                 "period": condition.get("period"), "due": due, "channel": channel}
        if "threshold" in condition:
            entry["threshold"] = condition["threshold"]
        if condition.get("unit"):
            entry["unit"] = str(condition["unit"]).strip()
        if condition.get("note"):
            entry["note"] = str(condition["note"]).strip()
        conditions.append(entry)
    return conditions


def cmd_init(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    path = Path(args.file).expanduser().resolve()
    if path.exists() and not args.force:
        raise LedgerError(f"{path} already exists; pass --force to reset it")
    write_ledger(path, {"schema_version": SCHEMA_VERSION, "decision_scope": DECISION_SCOPE,
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "symbols": {}})
    return 0, {"status": "complete", "detail_status": "ledger_initialized",
               "decision_scope": DECISION_SCOPE, "ledger": str(path)}


def cmd_append(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    path = Path(args.file).expanduser().resolve()
    ledger = load_ledger(path)
    symbol = str(args.symbol or "").strip().upper()
    if not symbol:
        raise LedgerError("--symbol is required")
    confirmed_at = iso_date(args.confirmed_at, "--confirmed-at")
    locator = str(args.source_locator or "").strip()
    if not locator:
        raise LedgerError("--source-locator is required (where the user's confirmation lives)")
    if any(token in locator.lower() for token in RESERVED_LOCATORS):
        raise LedgerError("--source-locator must not be a reserved test locator")
    conditions_path = Path(args.conditions_file).expanduser().resolve()
    if not conditions_path.is_file():
        raise LedgerError(f"conditions file not found: {conditions_path}")
    try:
        raw_conditions = json.loads(conditions_path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise LedgerError(f"conditions file is not valid JSON: {exc}") from exc
    if isinstance(raw_conditions, dict):
        raw_conditions = raw_conditions.get("conditions")
    conditions = validate_conditions(raw_conditions)

    entry = ledger["symbols"].setdefault(symbol, {"versions": []})
    versions = entry.setdefault("versions", [])
    if versions:
        latest = iso_date(versions[-1].get("confirmed_at"), "latest confirmed_at")
        if confirmed_at < latest:
            raise LedgerError(
                f"confirmed_at {confirmed_at} precedes the latest version ({latest}); "
                "backdating a confirmation is refused")
    version = len(versions) + 1
    record = {"version": version, "confirmed_at": confirmed_at, "source_locator": locator,
              "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "note": str(args.note or "").strip() or None, "conditions": conditions}
    versions.append(record)
    write_ledger(path, ledger)
    return 0, {"status": "complete", "detail_status": "version_appended",
               "decision_scope": DECISION_SCOPE, "ledger": str(path), "symbol": symbol,
               "version": version, "confirmed_at": confirmed_at,
               "condition_count": len(conditions),
               "condition_ids": [condition["id"] for condition in conditions]}


def effective_version(entry: dict[str, Any], as_of: str | None) -> dict[str, Any] | None:
    versions = entry.get("versions") or []
    if not versions:
        return None
    if as_of is None:
        return versions[-1]
    eligible = [version for version in versions
                if str(version.get("confirmed_at") or "") <= as_of]
    return eligible[-1] if eligible else None


def cmd_show(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    path = Path(args.file).expanduser().resolve()
    ledger = load_ledger(path)
    symbol = str(args.symbol or "").strip().upper()
    entry = ledger["symbols"].get(symbol)
    if entry is None:
        return 2, {"status": "insufficient_data", "detail_status": "symbol_not_in_ledger",
                   "decision_scope": DECISION_SCOPE, "symbol": symbol}
    as_of = iso_date(args.as_of, "--as-of") if args.as_of else None
    version = effective_version(entry, as_of)
    if version is None:
        return 2, {"status": "insufficient_data", "detail_status": "no_version_effective",
                   "decision_scope": DECISION_SCOPE, "symbol": symbol, "as_of": as_of,
                   "version_count": len(entry.get("versions") or [])}
    return 0, {"status": "complete", "detail_status": "effective_version_found",
               "decision_scope": DECISION_SCOPE, "symbol": symbol, "as_of": as_of,
               "version": version["version"], "confirmed_at": version["confirmed_at"],
               "source_locator": version["source_locator"],
               "conditions": version["conditions"],
               "version_count": len(entry.get("versions") or [])}


def cmd_list(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    path = Path(args.file).expanduser().resolve()
    ledger = load_ledger(path)
    rows = [{"symbol": symbol, "version_count": len(entry.get("versions") or []),
             "latest_confirmed_at": (entry.get("versions") or [{}])[-1].get("confirmed_at"),
             "condition_count": len((entry.get("versions") or [{}])[-1].get("conditions") or [])}
            for symbol, entry in sorted(ledger["symbols"].items())]
    return (0 if rows else 2), {
        "status": "complete" if rows else "insufficient_data",
        "detail_status": "symbols_listed" if rows else "ledger_empty",
        "decision_scope": DECISION_SCOPE, "ledger": str(path),
        "symbol_count": len(rows), "symbols": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="User-confirmed thesis condition ledger.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="Create an empty ledger.")
    init.add_argument("--file", required=True)
    init.add_argument("--force", action="store_true")
    append = subparsers.add_parser("append", help="Append a confirmed condition version.")
    append.add_argument("--file", required=True)
    append.add_argument("--symbol", required=True)
    append.add_argument("--confirmed-at", required=True)
    append.add_argument("--source-locator", required=True)
    append.add_argument("--conditions-file", required=True)
    append.add_argument("--note")
    show = subparsers.add_parser("show", help="Show the version effective at a date.")
    show.add_argument("--file", required=True)
    show.add_argument("--symbol", required=True)
    show.add_argument("--as-of")
    listing = subparsers.add_parser("list", help="List symbols and version counts.")
    listing.add_argument("--file", required=True)

    args = parser.parse_args(argv)
    handler = {"init": cmd_init, "append": cmd_append, "show": cmd_show, "list": cmd_list}[args.command]
    try:
        code, payload = handler(args)
    except LedgerError as exc:
        print(json.dumps({"status": "failed", "detail_status": "ledger_input_invalid",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
