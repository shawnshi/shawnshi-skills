#!/usr/bin/env python3
"""Cross-run registry and delta for Personal Investment Advisor task directories.

Why this exists: "what changed since the last run" was assembled by hand every
time (reading old scratch directories), so the one insight monitoring depends on
could not be automated.

Boundaries: the index is read-only unless ``--write`` is given; the diff never writes
anything.  Every comparison section is ``computed``, ``not_requested`` or
``not_comparable``, and a section that could not be compared reports ``null`` rather
than an empty map, because an empty map reads as "no change".

Tolerance is evidence-based, not convenience-based: a missing section the run itself
declared as never-run (``run_inventory.stages_not_run``) becomes a warning, every
other absence stays a blocking gap, and ``--strict`` disables the downgrade entirely.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "pia_run_registry_v1"
DECISION_SCOPE = "advisory"
ARTIFACTS = {
    "daily_run_summary": "out/daily_run_summary.json",
    "weights": "out/weights.json",
    "watchlist": "out/watchlist_results.json",
    "daily_sync": "out/daily_sync.json",
    "scenario": "out/scenario_result.json",
}
# The three comparison sections, and how loud each one is allowed to be when it
# cannot be compared.  ``weights`` is the diff's own payload, so its absence is
# never softened; the others can be declared-absent without breaking the diff.
SECTIONS = ("weights", "boundaries", "quotes")
BLOCKING_SECTIONS = ("weights",)
# Reasons a run may give for a stage it never ran.  Only a reason produced by the run
# itself counts as a declared absence; a file that merely vanished stays blocking.
DECLARED_ABSENCE_PREFIXES = ("skipped_by_flag:", "not_reached_due_to_upstream_incomplete")


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def order_key(run_id: str, summary: dict[str, Any] | None,
              weights: dict[str, Any] | None, run_dir: Path) -> tuple[str, float]:
    """Return (basis, value) for chronological ordering, most explicit first."""

    for payload, basis in ((summary, "daily_run_summary.evaluation_epoch"),
                           (weights, "weights.evaluation_epoch")):
        value = (payload or {}).get("evaluation_epoch")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return basis, float(value)
    for payload, basis in ((summary, "daily_run_summary.generated_at"),
                           (weights, "weights.generated_at")):
        value = (payload or {}).get("generated_at")
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return basis, parsed.timestamp()
    try:
        return "directory_mtime", run_dir.stat().st_mtime
    except OSError:
        return "unknown", 0.0


def crossed_from_watchlist(watchlist: dict[str, Any] | None) -> list[str]:
    crossed: list[str] = []
    for entry in (watchlist or {}).values():
        categories = (entry or {}).get("categories") or {}
        crossed.extend(categories.get("downside_boundary_crossed") or [])
        crossed.extend(categories.get("upside_boundary_crossed") or [])
    return sorted(set(crossed))


def boundary_status(watchlist: dict[str, Any] | None) -> dict[str, str]:
    return {symbol: str((entry or {}).get("status"))
            for symbol, entry in (watchlist or {}).items()}


def declared_absent(run: dict[str, Any], stage: str) -> bool:
    """True only when the run itself declared that this stage never ran.

    Tolerance has to be evidence-based: an absence the run named in
    ``run_inventory.stages_not_run`` is a known configuration difference, while an
    artifact that simply vanished is a broken comparison and still fails closed.
    """

    reason = (run.get("unrun_stages") or {}).get(stage)
    return bool(reason) and str(reason).startswith(DECLARED_ABSENCE_PREFIXES)


def classify_section(name: str, missing: list[str], *, requested: tuple[str, ...],
                     declared: bool, strict: bool,
                     upstream_blocking: bool) -> dict[str, Any]:
    """Decide how loud a missing comparison section is allowed to be."""

    if name not in requested:
        return {"state": "not_requested", "severity": "none", "reason": None,
                "missing_on": [], "declared_by_run": False}
    if not missing:
        return {"state": "computed", "severity": "none", "reason": None,
                "missing_on": [], "declared_by_run": False}
    if name in BLOCKING_SECTIONS:
        severity = "blocking"
    elif upstream_blocking:
        # The same absent artifact is already reported by a blocking section, so a
        # second gap for it would double-count one missing file.
        severity = "none"
    elif declared and not strict:
        severity = "warning"
    else:
        severity = "blocking"
    return {"state": "not_comparable", "severity": severity,
            "reason": "missing_on_" + "_and_".join(missing),
            "missing_on": list(missing), "declared_by_run": bool(declared)}


def candidate_run_dirs(task_root: Path, depth: int) -> list[Path]:
    """Return run directories up to ``depth`` levels below the task root.

    Runs are normally one level down, but an optimization or audit task may hold
    several runs of its own one level deeper, so the depth is bounded and explicit
    instead of being silently fixed at one.
    """

    found: list[Path] = []

    def walk(directory: Path, remaining: int) -> None:
        if remaining <= 0:
            return
        for child in sorted(path for path in directory.iterdir() if path.is_dir()):
            if any((child / relative).is_file() for relative in ARTIFACTS.values()):
                found.append(child)
            elif remaining > 1:
                walk(child, remaining - 1)

    walk(task_root, max(1, depth))
    return sorted(set(found))


def index_runs(task_root: Path, depth: int = 1) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    if not task_root.is_dir():
        return {"schema_version": SCHEMA_VERSION, "task_root": str(task_root),
                "status": "insufficient_data", "detail_status": "task_root_missing",
                "runs": [], "errors": [f"task root not found: {task_root}"]}
    for run_dir in candidate_run_dirs(task_root, depth):
        payloads: dict[str, dict[str, Any] | None] = {}
        artifacts: dict[str, dict[str, str | None]] = {}
        for key, relative in ARTIFACTS.items():
            path = run_dir / relative
            if path.is_file():
                payloads[key] = load_json(path)
                artifacts[key] = {"path": str(path), "sha256": sha256_file(path)}
        if not artifacts:
            continue
        summary, weights = payloads.get("daily_run_summary"), payloads.get("weights")
        basis, value = order_key(run_dir.name, summary, weights, run_dir)
        weight_rows = {row.get("symbol"): row
                       for row in (weights or {}).get("current_weights") or []
                       if isinstance(row, dict) and row.get("symbol")}
        watchlist = payloads.get("watchlist")
        if watchlist is None and summary:
            watch_stage = next((stage for stage in summary.get("stages") or []
                                if stage.get("stage") == "watchlist"), None)
            # A stage that ran but recorded no crossing list is unknown, not empty:
            # absence of the field is not evidence that no boundary was crossed.
            crossed = (sorted(watch_stage.get("crossed_boundaries") or [])
                       if watch_stage is not None and "crossed_boundaries" in watch_stage
                       else None)
        elif watchlist is None:
            crossed = None
        else:
            crossed = crossed_from_watchlist(watchlist)
        stages = {stage.get("stage"): {"status": stage.get("status"),
                                      "detail_status": stage.get("detail_status")}
                  for stage in (summary or {}).get("stages") or []}
        inventory = (summary or {}).get("run_inventory") or {}
        # A stage the run itself said it never ran is a declared absence; it is the only
        # evidence that lets a consumer soften a missing artifact without going blind.
        unrun = {str(row["stage"]): str(row.get("reason") or "")
                 for row in inventory.get("stages_not_run") or []
                 if isinstance(row, dict) and row.get("stage")}
        runs.append({
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "order_basis": basis,
            "order_value": value,
            "status": (summary or weights or {}).get("status"),
            "detail_status": (summary or weights or {}).get("detail_status"),
            "positions_input_sha256": (summary or {}).get("positions_input_sha256"),
            "stages": stages,
            "weights": {symbol: row.get("current_weight") for symbol, row in weight_rows.items()},
            "quotes_as_of": {symbol: ((row.get("quote") or {}).get("as_of"))
                             for symbol, row in weight_rows.items()},
            "boundary_status": boundary_status(watchlist),
            "crossed_boundaries": crossed,
            "unrun_stages": unrun,
            "artifacts": artifacts,
        })
    runs.sort(key=lambda run: (run["order_value"], run["run_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "task_root": str(task_root),
        "depth": max(1, depth),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "complete" if runs else "insufficient_data",
        "detail_status": "runs_indexed" if runs else "no_runs_found",
        "run_count": len(runs),
        "runs": runs,
        "errors": [],
    }


def numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def diff_runs(registry: dict[str, Any], run_from: str | None, run_to: str | None,
              sections: tuple[str, ...] | None = None,
              strict: bool = False) -> dict[str, Any]:
    """Compare two indexed runs, section by section.

    A section that cannot be compared never falls back to an empty result: an empty
    map reads as "no change", which is the opposite of "not known".  How loud a
    missing section is depends on evidence rather than convenience, so a section the
    run itself declared as never-run is a warning while anything else stays blocking.
    """

    requested = tuple(SECTIONS if not sections else sections)
    unknown = sorted({name for name in requested if name not in SECTIONS})
    if unknown:
        return {"schema_version": SCHEMA_VERSION, "status": "failed",
                "detail_status": "unknown_section", "decision_scope": DECISION_SCOPE,
                "requested_sections": list(requested),
                "errors": [f"unknown section(s): {', '.join(unknown)}; available: "
                           + ", ".join(SECTIONS)]}

    runs = registry.get("runs") or []
    if len(runs) < 2 and not (run_from and run_to):
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "insufficient_data",
            "detail_status": "fewer_than_two_runs",
            "decision_scope": DECISION_SCOPE,
            "run_count": len(runs),
            "requested_sections": list(requested),
            "errors": ["a diff needs at least two indexed runs, or an explicit --from/--to pair"],
        }
    by_id = {run["run_id"]: run for run in runs}
    if run_from or run_to:
        missing = [name for name in (run_from, run_to) if name and name not in by_id]
        if missing:
            return {"schema_version": SCHEMA_VERSION, "status": "insufficient_data",
                    "detail_status": "run_not_found", "decision_scope": DECISION_SCOPE,
                    "requested_sections": list(requested),
                    "errors": [f"run not in registry: {', '.join(missing)}"]}
        older = by_id[run_from] if run_from else runs[-2]
        newer = by_id[run_to] if run_to else runs[-1]
    else:
        older, newer = runs[-2], runs[-1]

    # ---- weights section: the diff's own payload ------------------------------
    weights_from, weights_to = older.get("weights") or {}, newer.get("weights") or {}
    weights_missing = [side for side, payload in (("from", weights_from), ("to", weights_to))
                       if not payload]
    weights_state = classify_section(
        "weights", weights_missing, requested=requested,
        declared=all(declared_absent(run, "weights") for side, run in
                     (("from", older), ("to", newer)) if side in weights_missing),
        strict=strict, upstream_blocking=False)
    weight_delta: dict[str, dict[str, Any]] | None = None
    symbols_added: list[str] | None = None
    symbols_removed: list[str] | None = None
    if weights_state["state"] == "computed":
        weight_delta = {}
        for symbol in sorted(set(weights_from) | set(weights_to)):
            before, after = numeric(weights_from.get(symbol)), numeric(weights_to.get(symbol))
            if before is None or after is None:
                weight_delta[symbol] = {"from": before, "to": after, "delta_pp": None,
                                        "note": "symbol present in only one run"}
                continue
            weight_delta[symbol] = {"from": before, "to": after,
                                    "delta_pp": round((after - before) * 100, 6)}
        symbols_added = sorted(set(weights_to) - set(weights_from))
        symbols_removed = sorted(set(weights_from) - set(weights_to))

    # ---- observation-boundary section ----------------------------------------
    status_from, status_to = (older.get("boundary_status") or {},
                              newer.get("boundary_status") or {})
    crossed_from_raw, crossed_to_raw = (older.get("crossed_boundaries"),
                                        newer.get("crossed_boundaries"))
    boundary_missing = list(dict.fromkeys(
        [side for side, payload in (("from", status_from), ("to", status_to)) if not payload]
        + [side for side, payload in (("from", crossed_from_raw), ("to", crossed_to_raw))
           if payload is None]))
    boundary_state = classify_section(
        "boundaries", boundary_missing, requested=requested,
        declared=all(declared_absent(run, "watchlist") for side, run in
                     (("from", older), ("to", newer)) if side in boundary_missing),
        strict=strict, upstream_blocking=False)
    boundary_transitions: dict[str, dict[str, Any]] | None = None
    crossed_added: list[str] | None = None
    crossed_cleared: list[str] | None = None
    if boundary_state["state"] == "computed":
        boundary_transitions = {}
        for symbol in sorted(set(status_from) | set(status_to)):
            before, after = status_from.get(symbol), status_to.get(symbol)
            if before != after:
                boundary_transitions[symbol] = {"from_status": before, "to_status": after}
        crossed_added = sorted(set(crossed_to_raw or []) - set(crossed_from_raw or []))
        crossed_cleared = sorted(set(crossed_from_raw or []) - set(crossed_to_raw or []))

    # ---- quote timestamp section --------------------------------------------
    quotes_from, quotes_to = older.get("quotes_as_of") or {}, newer.get("quotes_as_of") or {}
    quotes_missing = [side for side, payload in (("from", quotes_from), ("to", quotes_to))
                      if not payload]
    quotes_state = classify_section(
        "quotes", quotes_missing, requested=requested,
        declared=all(declared_absent(run, "weights") for side, run in
                     (("from", older), ("to", newer)) if side in quotes_missing),
        strict=strict, upstream_blocking=weights_state["severity"] == "blocking")
    quote_changes: dict[str, dict[str, Any]] | None = None
    if quotes_state["state"] == "computed":
        quote_changes = {}
        for symbol in sorted(set(quotes_from) | set(quotes_to)):
            before, after = quotes_from.get(symbol), quotes_to.get(symbol)
            if before != after:
                quote_changes[symbol] = {"from": before, "to": after}

    section_report = {"weights": weights_state, "boundaries": boundary_state,
                      "quotes": quotes_state}
    gaps = [f"{name} section not comparable ({state['reason']}) "
            f"({older['run_id']} / {newer['run_id']})"
            for name, state in section_report.items() if state["severity"] == "blocking"]
    warnings = [f"{name} section skipped: absent on {','.join(state['missing_on'])} and "
                f"declared not run by the run ({older['run_id']} / {newer['run_id']})"
                for name, state in section_report.items() if state["severity"] == "warning"]
    for side, run in (("from", older), ("to", newer)):
        if not (run.get("artifacts") or {}).get("daily_run_summary"):
            # A run directory may legitimately hold only weights (a rebalance task
            # output); that side then has no stage, scope or ordering evidence, which
            # narrows what the diff can say without making it a broken comparison.
            warnings.append(
                f"run summary missing on {side} ({run['run_id']}): stage transitions, "
                "decision scope and order basis fall back to weaker evidence")

    stage_from = {k: v.get("status") for k, v in (older.get("stages") or {}).items()}
    stage_to = {k: v.get("status") for k, v in (newer.get("stages") or {}).items()}
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "decision_scope": DECISION_SCOPE,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requested_sections": list(requested),
        "strict": bool(strict),
        "sections": section_report,
        "comparable_section_count": sum(1 for state in section_report.values()
                                        if state["state"] == "computed"),
        "from_run": {"run_id": older["run_id"], "status": older.get("status"),
                     "order_basis": older.get("order_basis"),
                     "order_value": older.get("order_value")},
        "to_run": {"run_id": newer["run_id"], "status": newer.get("status"),
                   "order_basis": newer.get("order_basis"),
                   "order_value": newer.get("order_value")},
        "run_status_transition": {"from": older.get("status"), "to": newer.get("status")},
        "stage_status_transitions": {stage: {"from": stage_from.get(stage),
                                             "to": stage_to.get(stage)}
                                     for stage in sorted(set(stage_from) | set(stage_to))
                                     if stage_from.get(stage) != stage_to.get(stage)},
        "weight_delta_pp": weight_delta,
        "boundary_transitions": boundary_transitions,
        "boundary_crossed_added": crossed_added,
        "boundary_crossed_cleared": crossed_cleared,
        "quote_as_of_changes": quote_changes,
        "symbols_added": symbols_added,
        "symbols_removed": symbols_removed,
        "gaps": gaps,
        "warnings": warnings,
    }
    requested_states = [section_report[name] for name in requested]
    if requested_states and all(state["state"] == "not_comparable"
                                for state in requested_states):
        # Tolerating declared absences must not degenerate into a cheerful empty
        # diff: when nothing requested could be compared, that *is* the answer.
        report["status"] = "insufficient_data"
        report["detail_status"] = "nothing_comparable"
        report["errors"] = ["no requested section could be compared"]
        return report
    if gaps:
        report["status"], report["detail_status"] = "insufficient_data", "diff_partial"
    elif warnings:
        report["status"], report["detail_status"] = ("complete_with_warnings",
                                                     "diff_computed_with_warnings")
    else:
        report["status"], report["detail_status"] = "complete", "diff_computed"
    return report

def summarize_diff(report: dict[str, Any]) -> list[str]:
    # An early return (unknown run, too few runs) also reaches --summary, so every
    # field is read defensively rather than assumed to exist.
    from_run = report.get("from_run") or {}
    to_run = report.get("to_run") or {}
    lines = [f"from {from_run.get('run_id')} -> {to_run.get('run_id')}"
             f" ({from_run.get('status')} -> {to_run.get('status')})"]
    moved = [(symbol, entry) for symbol, entry in (report.get("weight_delta_pp") or {}).items()
             if entry.get("delta_pp")]
    if moved:
        ranked = sorted(moved, key=lambda item: abs(item[1]["delta_pp"]), reverse=True)[:6]
        lines.append("weight moves (pp): " + ", ".join(
            f"{symbol} {entry['delta_pp']:+.2f}" for symbol, entry in ranked))
    if report.get("boundary_crossed_added"):
        lines.append("newly crossed: " + ", ".join(report["boundary_crossed_added"]))
    if report.get("boundary_crossed_cleared"):
        lines.append("no longer crossed: " + ", ".join(report["boundary_crossed_cleared"]))
    if report.get("boundary_transitions"):
        lines.append("boundary status changes: " + ", ".join(
            f"{symbol} {entry['from_status']}->{entry['to_status']}"
            for symbol, entry in report["boundary_transitions"].items()))
    if report.get("stage_status_transitions"):
        lines.append("stage changes: " + ", ".join(
            f"{stage} {entry['from']}->{entry['to']}"
            for stage, entry in report["stage_status_transitions"].items()))
    states = report.get("sections") or {}
    if states:
        lines.append("sections: " + ", ".join(
            str(name) + "=" + str(state.get("state"))
            + (f"({state['reason']})" if state.get("state") == "not_comparable" else "")
            for name, state in states.items()))
    for warning in report.get("warnings") or []:
        lines.append(f"warn: {warning}")
    for gap in report.get("gaps") or []:
        lines.append(f"gap: {gap}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Index PIA task runs and diff them.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    index = subparsers.add_parser("index", help="Index the artifacts of every run directory.")
    index.add_argument("--task-root", required=True)
    index.add_argument("--depth", type=int, default=1)
    index.add_argument("--write", action="store_true")
    index.add_argument("--output")
    diff = subparsers.add_parser("diff", help="Diff two indexed runs (default: the last two).")
    diff.add_argument("--task-root", required=True)
    diff.add_argument("--depth", type=int, default=1)
    diff.add_argument("--registry")
    diff.add_argument("--from", dest="run_from")
    diff.add_argument("--to", dest="run_to")
    diff.add_argument("--summary", action="store_true", help="Print a short human summary as well.")
    diff.add_argument(
        "--sections",
        help=("Comma-separated sections this comparison must be able to make "
              f"({','.join(SECTIONS)}). A section that was not requested is reported "
              "as not_requested instead of blocking."),
    )
    diff.add_argument(
        "--strict", action="store_true",
        help=("Keep every missing section blocking, even one the run declared it "
              "never ran."),
    )
    args = parser.parse_args(argv)

    if args.command == "index":
        registry = index_runs(Path(args.task_root).expanduser().resolve(), args.depth)
        if args.write:
            target = (Path(args.output).expanduser().resolve() if args.output
                      else Path(args.task_root).expanduser().resolve() / "pia_run_registry.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(json.dumps(registry, ensure_ascii=False, indent=2).encode("utf-8"))
            registry["registry_file"] = str(target)
        print(json.dumps(registry, ensure_ascii=False, indent=2))
        return 0 if registry.get("status") == "complete" else 2

    if args.registry:
        registry = load_json(Path(args.registry).expanduser().resolve())
        if registry is None:
            print(json.dumps({"status": "failed", "detail_status": "registry_unreadable",
                              "decision_scope": DECISION_SCOPE,
                              "errors": [str(args.registry)]}, ensure_ascii=False, indent=2))
            return 3
    else:
        registry = index_runs(Path(args.task_root).expanduser().resolve(), args.depth)
    if args.command == "diff" and args.sections is not None:
        sections = tuple(part.strip() for part in args.sections.split(",") if part.strip())
        if not sections:
            # An empty request would otherwise mean "every section", which is the
            # opposite of what the caller asked for.
            print(json.dumps({"status": "failed", "detail_status": "no_sections_requested",
                              "decision_scope": DECISION_SCOPE,
                              "errors": ["--sections was given but named no section"]},
                             ensure_ascii=False, indent=2))
            return 3
    else:
        sections = None
    report = diff_runs(registry, args.run_from, args.run_to, sections=sections,
                       strict=args.strict)
    if args.summary:
        report["summary_lines"] = summarize_diff(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("status") == "failed":
        return 3
    return 0 if report.get("status") in ("complete", "complete_with_warnings") else 2


if __name__ == "__main__":
    raise SystemExit(main())
