#!/usr/bin/env python3
"""Run-level trigger ledger: record what each run flagged, and check it later.

Why this exists: the skill had decision-journal parts (``advice_journal.py``,
``sync_outcomes.py``, ``calibrate``) but nothing connected a *run* to a later
review.  The advice journal keeps its own advice-record contract, so this ledger is
a separate, append-only file: one record per run (weights, crossed observation
boundaries, statuses, review horizon), with ``due`` listing what has come up for
review and ``close`` recording the review.

Boundaries: append-only; duplicate entries are refused by ``entry_id`` (so a rerun
never double-counts); a run without boundary evidence records ``null`` rather than
an empty list; nothing here writes to the advice journal, places an order, or
mutates the portfolio.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_trigger_ledger_v1"
DECISION_SCOPE = "advisory"
DEFAULT_LEDGER_NAME = "pia_trigger_ledger.jsonl"
DEFAULT_REVIEW_DAYS = 90
LOCK_TIMEOUT_SECONDS = 5.0


class LedgerError(RuntimeError):
    pass


class _LedgerLock:
    """Exclusive lock beside the ledger, mirroring the advice-journal discipline."""

    def __init__(self, path: Path, timeout_seconds: float = LOCK_TIMEOUT_SECONDS):
        self.path = path.with_suffix(path.suffix + ".lock")
        self.timeout_seconds = timeout_seconds
        self.handle = None

    def __enter__(self) -> "_LedgerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        self.handle = self.path.open("a+", encoding="utf-8")
        while True:
            try:
                self._lock()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    raise LedgerError(
                        f"ledger lock busy for more than {self.timeout_seconds}s: {self.path}")
                time.sleep(0.1)

    def _lock(self) -> None:
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc_info: Any) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def read_entries(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def append_lines(ledger: Path, payloads: list[dict[str, Any]]) -> None:
    rendered = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in payloads)
    with _LedgerLock(ledger):
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())


def crossed_from_watchlist(watchlist: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Return crossed boundaries with their observed price, or None when unevaluated."""

    if not isinstance(watchlist, dict):
        return None
    rows: list[dict[str, Any]] = []
    for symbol, entry in sorted(watchlist.items()):
        if not isinstance(entry, dict):
            continue
        categories = entry.get("categories") or {}
        for role in ("downside_boundary_crossed", "upside_boundary_crossed"):
            for boundary_id in categories.get(role) or []:
                rows.append({"symbol": symbol, "boundary_id": boundary_id, "role": role,
                             "observed_price": (entry.get("runtime_quote") or {}).get("current_price")})
    return rows


def build_record(run_dir: Path, review_days: int, now: datetime.datetime) -> dict[str, Any]:
    summary = load_json(run_dir / "out" / "daily_run_summary.json")
    weights = load_json(run_dir / "out" / "weights.json")
    watchlist = load_json(run_dir / "out" / "watchlist_results.json")
    if summary is None and weights is None:
        raise LedgerError(f"run directory has no daily_run_summary.json or weights.json: {run_dir}")
    quote_prices = {row.get("symbol"): (row.get("quote") or {}).get("as_of")
                    for row in (weights or {}).get("current_weights") or []
                    if isinstance(row, dict)}
    price_by_symbol = {row.get("symbol"): row.get("current_price")
                       for row in (weights or {}).get("current_weights") or []
                       if isinstance(row, dict)}
    epoch = (summary or {}).get("evaluation_epoch") or (weights or {}).get("evaluation_epoch")
    generated_at = (summary or {}).get("generated_at") or now.isoformat()
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool):
        base = datetime.datetime.fromtimestamp(float(epoch), datetime.timezone.utc)
    else:
        try:
            base = datetime.datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        except ValueError:
            base = now
    horizon = (base + datetime.timedelta(days=review_days)).date().isoformat()
    entry_id = hashlib.sha256(f"{run_dir.name}|{generated_at}".encode("utf-8")).hexdigest()[:16]
    crossed = crossed_from_watchlist(watchlist)
    if crossed is not None:
        # The watchlist summary carries the crossed boundary ids; the observed price
        # comes from the same run's weight rows so a later review can compare it.
        for row in crossed:
            if row.get("observed_price") is None:
                row["observed_price"] = price_by_symbol.get(row.get("symbol"))
            row["quote_as_of"] = quote_prices.get(row.get("symbol"))
    record = {
        "schema_version": SCHEMA_VERSION,
        "entry_id": entry_id,
        "decision_scope": DECISION_SCOPE,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "recorded_at": now.isoformat(),
        "generated_at": generated_at,
        "evaluation_epoch": epoch,
        "status": (summary or weights or {}).get("status"),
        "detail_status": (summary or weights or {}).get("detail_status"),
        "positions_input_sha256": (summary or {}).get("positions_input_sha256"),
        "weights": {row.get("symbol"): row.get("current_weight")
                    for row in (weights or {}).get("current_weights") or []
                    if isinstance(row, dict) and row.get("symbol")},
        "crossed_boundaries": crossed,
        "boundaries_evaluated": crossed is not None,
        "stage_statuses": {stage.get("stage"): stage.get("status")
                           for stage in (summary or {}).get("stages") or []},
        "review_days": review_days,
        "review_horizon_date": horizon,
        "reviewed_at": None,
        "review_note": None,
    }
    return record


def cmd_append(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    run_dir = Path(args.run_dir).expanduser().resolve()
    ledger = Path(args.ledger).expanduser().resolve() if args.ledger else \
        Path(args.task_root).expanduser().resolve() / DEFAULT_LEDGER_NAME
    now = (datetime.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
           if args.now else datetime.datetime.now(datetime.timezone.utc))
    record = build_record(run_dir, args.review_days, now)
    existing = {entry.get("entry_id") for entry in read_entries(ledger)}
    if record["entry_id"] in existing:
        return 0, {"status": "complete", "detail_status": "already_recorded",
                   "decision_scope": DECISION_SCOPE, "ledger": str(ledger),
                   "entry_id": record["entry_id"], "appended": False}
    append_lines(ledger, [record])
    return 0, {"status": "complete", "detail_status": "entry_appended",
               "decision_scope": DECISION_SCOPE, "ledger": str(ledger),
               "entry_id": record["entry_id"], "appended": True,
               "crossed_boundaries": record["crossed_boundaries"],
               "review_horizon_date": record["review_horizon_date"]}


def load_state(ledger: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (entries, closures) with closure records applied to their target."""

    entries: list[dict[str, Any]] = []
    closures: dict[str, dict[str, Any]] = {}
    for record in read_entries(ledger):
        target = record.get("closes")
        if isinstance(target, str):
            # A later closure wins; keep both so the review history stays auditable.
            closures[target] = record
            continue
        entries.append(record)
    for entry in entries:
        closure = closures.get(str(entry.get("entry_id")))
        if closure:
            entry["reviewed_at"] = closure.get("reviewed_at")
            entry["review_note"] = closure.get("review_note")
            entry["review_outcome"] = closure.get("review_outcome")
    return entries, closures


def cmd_list(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    ledger = Path(args.ledger).expanduser().resolve()
    entries, closures = load_state(ledger)
    if args.symbol:
        symbol = args.symbol.strip().upper()
        entries = [entry for entry in entries
                   if symbol in (entry.get("weights") or {})
                   or any(row.get("symbol", "").upper() == symbol
                          for row in entry.get("crossed_boundaries") or [])]
    entries.sort(key=lambda entry: str(entry.get("generated_at") or ""), reverse=True)
    limited = entries[: max(1, args.limit)]
    return (0 if entries else 2), {
        "status": "complete" if entries else "insufficient_data",
        "detail_status": "entries_listed" if entries else "ledger_empty",
        "decision_scope": DECISION_SCOPE,
        "ledger": str(ledger),
        "entry_count": len(entries),
        "closure_count": len(closures),
        "entries": limited,
    }


def cmd_due(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    ledger = Path(args.ledger).expanduser().resolve()
    as_of = (datetime.date.fromisoformat(args.as_of) if args.as_of
             else datetime.datetime.now(datetime.timezone.utc).date())
    due: list[dict[str, Any]] = []
    for entry in load_state(ledger)[0]:
        if entry.get("reviewed_at"):
            continue
        horizon = entry.get("review_horizon_date")
        if not isinstance(horizon, str):
            continue
        try:
            if datetime.date.fromisoformat(horizon) > as_of:
                continue
        except ValueError:
            continue
        due.append({"entry_id": entry.get("entry_id"), "run_id": entry.get("run_id"),
                    "review_horizon_date": horizon,
                    "status": entry.get("status"),
                    "crossed_boundaries": entry.get("crossed_boundaries"),
                    "positions_input_sha256": entry.get("positions_input_sha256")})
    due.sort(key=lambda item: str(item.get("review_horizon_date")))
    return (0 if due else 2), {
        "status": "complete" if due else "insufficient_data",
        "detail_status": "review_due" if due else "nothing_due",
        "decision_scope": DECISION_SCOPE,
        "ledger": str(ledger),
        "as_of": as_of.isoformat(),
        "due_count": len(due),
        "due": due,
    }


def cmd_close(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    ledger = Path(args.ledger).expanduser().resolve()
    entries, _closures = load_state(ledger)
    target = next((entry for entry in entries if entry.get("entry_id") == args.entry_id), None)
    if target is None:
        return 2, {"status": "insufficient_data", "detail_status": "entry_not_found",
                   "decision_scope": DECISION_SCOPE, "errors": [args.entry_id]}
    if target.get("reviewed_at"):
        return 0, {"status": "complete", "detail_status": "already_closed",
                   "decision_scope": DECISION_SCOPE, "entry_id": args.entry_id,
                   "reviewed_at": target.get("reviewed_at")}
    now = datetime.datetime.now(datetime.timezone.utc)
    closure = {"schema_version": SCHEMA_VERSION, "closes": args.entry_id,
               "reviewed_at": now.isoformat(), "review_note": args.note,
               "review_outcome": args.outcome}
    append_lines(ledger, [closure])
    return 0, {"status": "complete", "detail_status": "entry_closed",
               "decision_scope": DECISION_SCOPE, "entry_id": args.entry_id,
               "reviewed_at": closure["reviewed_at"], "note": args.note,
               "outcome": args.outcome}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run-level trigger ledger.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="Record one run's triggers.")
    append.add_argument("--run-dir", required=True)
    append.add_argument("--task-root")
    append.add_argument("--ledger")
    append.add_argument("--review-days", type=int, default=DEFAULT_REVIEW_DAYS)
    append.add_argument("--now")

    listing = subparsers.add_parser("list", help="List ledger entries (newest first).")
    listing.add_argument("--ledger", required=True)
    listing.add_argument("--symbol")
    listing.add_argument("--limit", type=int, default=20)

    due = subparsers.add_parser("due", help="List entries whose review horizon has arrived.")
    due.add_argument("--ledger", required=True)
    due.add_argument("--as-of")

    close = subparsers.add_parser("close", help="Record the review of one entry.")
    close.add_argument("--ledger", required=True)
    close.add_argument("--entry-id", required=True)
    close.add_argument("--note", required=True)
    close.add_argument("--outcome", choices=("trigger_hit", "trigger_missed", "no_action_taken",
                                             "inconclusive"))

    args = parser.parse_args(argv)
    if args.command == "append" and not (args.task_root or args.ledger):
        print(json.dumps({"status": "failed", "detail_status": "ledger_path_required",
                          "decision_scope": DECISION_SCOPE,
                          "errors": ["pass --task-root or --ledger"]},
                         ensure_ascii=False, indent=2))
        return 3
    handler = {"append": cmd_append, "list": cmd_list, "due": cmd_due, "close": cmd_close}[args.command]
    try:
        code, payload = handler(args)
    except LedgerError as exc:
        print(json.dumps({"status": "failed", "detail_status": "ledger_error",
                          "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                         ensure_ascii=False, indent=2))
        return 3
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
