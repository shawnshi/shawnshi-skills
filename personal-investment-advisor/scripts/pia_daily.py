#!/usr/bin/env python3
"""One-command Daily Sync orchestrator.

Why this exists: a real Daily Sync needed FX refresh, a quote batch, an offline
replay, current weights and observation-boundary checks, each with its own
freshness window (15 minutes for weights, 72 hours for FX, market-state based for
quotes).  Running them by hand forced repeated re-runs whenever a step stalled.
This orchestrator pins ONE evaluation epoch, runs the stages in order, stops any
dependent stage when its upstream is not ``complete``, and emits a single
envelope with a ``stages`` list that the status contract already aggregates.

Boundaries: never modifies the positions input, never invents FX or quotes, no
downstream stage runs from an incomplete upstream, and nothing here places,
routes or simulates an order.
"""

from __future__ import annotations

import argparse
import contextlib
import os

import instrument_labels
import datetime
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_readiness  # noqa: E402
import pia_refresh  # noqa: E402
import pia_risk_diagnostic  # noqa: E402
from quote_evidence_contract import (  # noqa: E402
    MAX_QUOTE_AGE_SECONDS,
    QUOTE_FRESHNESS_POLICY_VERSION,
    QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE,
    build_portfolio_snapshot_binding,
)
from status_contract import (  # noqa: E402
    exit_code_for,
    status_from_payload,
    status_from_stages,
    status_rank,
)

SCHEMA_VERSION = "pia_daily_run_v1"
REPLAY_HISTORY_FILENAME = "run_replay_history.jsonl"
DECISION_SCOPE = "advisory"
QUOTE_TIMEOUT_SECONDS = 900
TERMINAL_COMPLETE = {"complete"}


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def run_module(main: Callable[..., Any], argv: list[str]) -> tuple[int, dict]:
    """Call a sibling script's ``main`` and capture its JSON envelope.

    Sibling scripts differ: some accept an argv list, others parse ``sys.argv``
    directly and communicate their exit code by raising ``SystemExit``.  Both are
    supported here so the orchestrator can stay in-process and share one epoch.
    """

    import inspect

    accepts_argv = bool(inspect.signature(main).parameters)
    previous_argv = sys.argv
    buffer = io.StringIO()
    sys.argv = ["pia-stage", *argv]
    try:
        with contextlib.redirect_stdout(buffer):
            result = main(argv) if accepts_argv else main()
        code = 0 if result is None else int(result)
    except SystemExit as exc:
        code = int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - recorded as a failed stage
        return 3, {"status": "failed", "detail_status": "stage_crashed",
                   "errors": [f"{type(exc).__name__}: {exc}"]}
    finally:
        sys.argv = previous_argv
    raw = buffer.getvalue().strip()
    if not raw:
        return code, {"status": "failed" if code else "incomplete",
                      "detail_status": "stage_emitted_no_json"}
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, {"status": "failed", "detail_status": "stage_json_unparseable",
                      "errors": [raw[:300]]}


def run_quotes(positions_file: Path, cache_dir: Path, symbols: list[str],
               task_dir: Path, holiday_calendar: Path | None = None,
               ) -> tuple[int, dict, Path | None]:
    """Run the documented quote batch and capture it as ``out/quotes.json``."""

    command = [sys.executable, "-B", str(SCRIPT_DIR / "yf.py"), *symbols,
               "--daily-sync", "--positions-file", str(positions_file),
               "--cache-dir", str(cache_dir)]
    if holiday_calendar is not None:
        command.extend(["--holiday-calendar-file", str(holiday_calendar)])
    try:
        completed = subprocess.run(command, capture_output=True,
                                   timeout=QUOTE_TIMEOUT_SECONDS, check=False)
    except subprocess.SubprocessError as exc:
        return 3, {"status": "failed", "detail_status": "quote_batch_unavailable",
                   "errors": [f"{type(exc).__name__}: {exc}"]}, None
    quotes_path = task_dir / "out" / "quotes.json"
    quotes_path.parent.mkdir(parents=True, exist_ok=True)
    quotes_path.write_bytes(completed.stdout)
    payload = None
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeError, ValueError):
        payload = None
    if completed.returncode != 0 or not isinstance(payload, dict):
        stderr = completed.stderr.decode("utf-8", "replace").strip()[:300]
        return (completed.returncode or 3), {
            "status": "failed",
            "detail_status": "quote_batch_failed",
            "errors": [stderr or "quote batch did not return a JSON object"],
        }, quotes_path
    audit = payload.get("portfolio_batch_audit") or {}
    complete = bool(audit.get("complete")) and bool(audit.get("coverage_complete"))
    return (0 if complete else 1), {
        "status": "complete" if complete else "insufficient_data",
        "detail_status": "quote_batch_captured" if complete else "quote_batch_incomplete",
        "coverage_complete": bool(audit.get("coverage_complete")),
        "matched": audit.get("portfolio_matched_count"),
        "expected": len(audit.get("expected_active_symbols") or []),
        "errors": [] if complete else ["quote batch coverage is incomplete"],
    }, quotes_path


def reusable_quote_batch(quotes_path: Path,
                         positions: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Decide whether an existing quote batch may stand in for a fresh fetch.

    Only deterministic identity and coverage facts are checked here.  Quote freshness
    and the per-record evidence contract deliberately stay with the replay stage,
    which re-derives them from the same file; a batch that cannot prove it belongs to
    this exact positions snapshot is never reused, because a stale or foreign batch
    read as this run's evidence would be fabricated evidence.
    """
    checks: dict[str, Any] = {"exists": quotes_path.is_file()}
    if not checks["exists"]:
        return False, {**checks, "reason": "quotes_file_missing"}
    try:
        payload = json.loads(quotes_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        return False, {**checks, "reason": f"quotes_file_unreadable: {type(exc).__name__}: {exc}"}
    audit = payload.get("portfolio_batch_audit") if isinstance(payload, dict) else None
    checks["coverage_complete"] = bool(isinstance(audit, dict)
                                       and audit.get("coverage_complete"))
    checks["snapshot_binding_matches"] = bool(
        isinstance(audit, dict)
        and audit.get("portfolio_snapshot_binding") == build_portfolio_snapshot_binding(positions))
    checks["record_count"] = (len(payload.get("records") or [])
                             if isinstance(payload, dict) else 0)
    return all(checks[key] for key in
               ("exists", "coverage_complete", "snapshot_binding_matches")), checks


def build_residual_unknowns(stages: list[dict[str, Any]], *,
                            run_status: Any = None,
                            run_detail: Any = None) -> list[dict[str, Any]]:
    """List what this run did *not* establish, from stage evidence only.

    A run is never a full verification of trade readiness: quotes and stages can all
    be complete while account-level rules, cost models and deferred thesis conditions
    remain unproven.  Recording them turns silence into named unknowns so an
    ``actionable`` reading cannot pass for a verified one.
    """
    unknowns: list[dict[str, Any]] = []
    if run_status is not None and run_status != "complete":
        # A run-level verdict that its stages look clean still means the run's own
        # deliverable is not established; that must be a named unknown too.
        unknowns.append({
            "kind": "run_not_complete",
            "stage": None,
            "detail": str(run_detail or run_status),
            "statement": "本轮整体未完成；其未覆盖内容不得读作已验证",
        })
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        name = str(stage.get("stage") or "unknown_stage")
        native_status = stage.get("status")
        if native_status not in (None, "complete", "ok"):
            unknowns.append({
                "kind": "stage_not_complete",
                "stage": name,
                "detail": str(stage.get("detail_status") or native_status),
                "statement": f"阶段 {name} 未完成，其覆盖的内容本轮未建立",
            })
        for item in stage.get("unproven_probes") or []:
            unknowns.append({
                "kind": "coverage_probe_unproven",
                "stage": name,
                "detail": str(item),
                "statement": "披露通道未证明；不得读作该通道无事件",
            })
        for error in stage.get("errors") or []:
            unknowns.append({
                "kind": "stage_error",
                "stage": name,
                "detail": str(error),
                "statement": f"阶段 {name} 报错，对应结论本轮无证据支撑",
            })
        for symbol in stage.get("boundaries_undefined") or []:
            unknowns.append({
                "kind": "watchlist_thresholds_undefined",
                "stage": name,
                "detail": str(symbol),
                "statement": "该标的观察阀值未定义，本轮无法判定是否越界",
            })
    unknowns.extend([
        {
            "kind": "account_rules_not_verified",
            "stage": None,
            "detail": "pia never connects to a broker",
            "statement": "交易规则、可卖数量与当日限额均未经券商渠道核验",
        },
        {
            "kind": "cost_model_not_sourced",
            "stage": None,
            "detail": "commission/spread/impact/sell_tax require caller-supplied snapshots",
            "statement": "成本与冲击均未经一手来源核验，只在 actionability gate 显式提供时参与计算",
        },
    ])
    return unknowns


def finalize_run_summary(
    summary: dict[str, Any],
    *,
    plan: list[str],
    stages: list[dict[str, Any]],
    evaluation_epoch: float,
    skip_watchlist: bool = False,
) -> dict[str, Any]:
    """Attach scope, freshness and unrun-stage inventory to every exit path.

    Aborted runs need this most: a run that stopped after two stages must still be
    able to say which stages never ran, and until when its evidence is valid.
    """
    summary.setdefault("decision_scope", DECISION_SCOPE)
    summary.setdefault("evaluation_epoch", evaluation_epoch)
    summary["stages"] = stages
    for stage in stages:
        stage["status"] = status_from_payload(stage, 0)
    summary["status"] = status_from_payload(summary, 0)
    summary["run_inventory"] = build_run_inventory(
        plan=plan,
        stages=stages,
        decision_scope=summary["decision_scope"],
        evaluation_epoch=evaluation_epoch,
        flag_skipped={"watchlist": "--skip-watchlist"} if skip_watchlist else {},
    )
    # The parent may be stricter than its stages (an explicit business verdict such
    # as ``insufficient_evidence`` outranks plain incompleteness), but a parent that
    # is *softer* than a failed stage is a contract violation, not a rounding error.
    derived_status = status_from_stages(stages)
    summary["residual_unknowns"] = build_residual_unknowns(
        stages,
        run_status=summary.get("status"),
        run_detail=summary.get("detail_status"),
    )
    summary["status_consistency"] = {
        "top_level_status": summary["status"],
        "stage_derived_status": derived_status,
        "consistent": status_rank(summary["status"]) >= status_rank(derived_status),
    }
    return summary


def active_symbols(positions: dict[str, Any]) -> list[str]:
    return [str(item.get("symbol")) for item in positions.get("positions", [])
            if isinstance(item, dict) and float(item.get("quantity") or 0) > 0
            and str(item.get("market") or "").upper() != "CASH"
            and str(item.get("asset_type") or "").lower() != "cash"]


def _epoch_to_iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(
        epoch, datetime.timezone.utc).isoformat()


def build_run_inventory(
    *,
    plan: list[str],
    stages: list[dict[str, Any]],
    decision_scope: str,
    evaluation_epoch: float,
    flag_skipped: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Describe what this run actually did, and what it did not do.

    A stage that never ran must never look like a stage that produced an empty
    result, so every planned-but-absent stage carries an explicit reason.  The
    freshness window is derived from the quote evidence contract rather than being
    hand-typed, and the conservative (shortest) bound is exposed as ``valid_until``
    so a consumer that reads only that field fails closed.
    """
    flag_skipped = flag_skipped or {}
    stages_run = [str(stage.get("stage")) for stage in stages]
    ran = set(stages_run)
    # A stage the caller explicitly turned off never enters ``plan``, yet it is
    # precisely the stage a reader must not mistake for an empty result.
    considered = list(plan) + [stage for stage in flag_skipped if stage not in plan]
    not_run: list[dict[str, str]] = []
    for stage in considered:
        if stage in ran:
            continue
        reason = (f"skipped_by_flag:{flag_skipped[stage]}" if stage in flag_skipped
                  else "not_reached_due_to_upstream_incomplete")
        not_run.append({"stage": stage, "reason": reason})
    windows = dict(QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE)
    earliest = evaluation_epoch + min(windows.values())
    latest = evaluation_epoch + max(windows.values())
    return {
        "decision_scope": decision_scope,
        "requested_stages": list(plan),
        "stages_run": stages_run,
        "stages_not_run": not_run,
        "stage_scopes": {stage: decision_scope for stage in stages_run},
        "evaluation_epoch": evaluation_epoch,
        "freshness": {
            "policy_version": QUOTE_FRESHNESS_POLICY_VERSION,
            "reference_epoch": evaluation_epoch,
            "window_seconds_by_market_state": windows,
            "earliest_valid_until": _epoch_to_iso(earliest),
            "latest_valid_until": _epoch_to_iso(latest),
        },
        "valid_until": _epoch_to_iso(earliest),
        "valid_until_basis": "conservative_shortest_quote_window",
        "max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS,
    }


def load_coverage_probes(path: Path) -> list[dict[str, Any]]:
    """Validate the optional coverage-probe specification before any stage starts.

    A malformed spec is an input error: it must stop the run up front rather than be
    discovered halfway through as a mysterious stage failure.
    """

    if not path.is_file():
        raise ValueError(f"coverage probe spec not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"coverage probe spec is not valid JSON: {exc}") from exc
    if (not isinstance(payload, dict) or not isinstance(payload.get("probes"), list)
            or not payload["probes"]):
        raise ValueError("coverage probe spec must contain a non-empty 'probes' list")
    probes: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, probe in enumerate(payload["probes"]):
        prefix = f"probes[{index}]"
        if not isinstance(probe, dict):
            raise ValueError(f"{prefix} must be an object")
        for field in ("channel", "target", "control", "target_class", "control_class",
                      "channel_scope"):
            if not isinstance(probe.get(field), str) or not probe[field].strip():
                raise ValueError(f"{prefix}.{field} must be a non-empty string")
        for field in ("target_class", "control_class"):
            if probe[field].strip().lower() not in {"stock", "etf"}:
                raise ValueError(f"{prefix}.{field} must be stock or etf")
        key = (probe["channel"].strip().lower(), probe["target"].strip().upper(),
               probe["control"].strip().upper())
        if key in seen:
            raise ValueError(f"{prefix} duplicates an earlier probe: {key}")
        seen.add(key)
        window_days = probe.get("window_days", 400)
        if not isinstance(window_days, int) or isinstance(window_days, bool) or window_days < 1:
            raise ValueError(f"{prefix}.window_days must be a positive integer")
        probes.append({"channel": key[0], "target": probe["target"].strip(),
                       "control": probe["control"].strip(),
                       "target_class": probe["target_class"].strip().lower(),
                       "control_class": probe["control_class"].strip().lower(),
                       "channel_scope": probe["channel_scope"].strip(),
                       "window_days": window_days})
    return probes


def parse_risk_histories(items: list[str], task_dir: Path) -> list[dict[str, str]]:
    """Validate ``symbol=path`` history arguments before any stage starts.

    Only the syntax is checked here (a plan-only run must not require the files to
    exist yet); existence is enforced by the diagnostic itself, which fails closed and
    reports the reason.
    """

    histories: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        symbol, _, raw = item.partition("=")
        symbol = symbol.strip().upper()
        path = raw.strip()
        if not symbol or not path:
            raise ValueError(f"--risk-history expects symbol=path, got {item!r}")
        if symbol in seen:
            raise ValueError(f"--risk-history repeats the symbol {symbol}")
        seen.add(symbol)
        candidate = Path(path)
        resolved = candidate if candidate.is_absolute() else (task_dir / candidate)
        histories.append({"symbol": symbol, "path": str(resolved)})
    return histories


def parse_fx_histories(items: list[str], task_dir: Path) -> list[dict[str, str]]:
    """Validate ``PAIR=path`` FX history arguments (syntax only, like the equity ones)."""

    pairs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        pair, _, raw = item.partition("=")
        pair = pair.strip().upper()
        path = raw.strip()
        if not pair or not path:
            raise ValueError(f"--risk-fx-history expects PAIR=path, got {item!r}")
        if pair in seen:
            raise ValueError(f"--risk-fx-history repeats the pair {pair}")
        seen.add(pair)
        candidate = Path(path)
        resolved = candidate if candidate.is_absolute() else (task_dir / candidate)
        pairs.append({"pair": pair, "path": str(resolved)})
    return pairs


def capture_previous_run(task_dir: Path) -> dict[str, Any] | None:
    """Identify the run this invocation is about to overwrite, before it does.

    Re-running the pinned workflow in an existing task directory rewrites that
    directory's own artifacts.  That is a legitimate repeat, not a silent one: the
    previous run has to stay identifiable after its files are gone.
    """

    path = task_dir / "out" / "daily_run_summary.json"
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {"summary_sha256": None, "unreadable": True, "path": str(path)}
    return {"summary_sha256": hashlib.sha256(raw).hexdigest(),
            "generated_at": payload.get("generated_at"),
            "status": payload.get("status"),
            "detail_status": payload.get("detail_status")}


def append_replay_history(task_dir: Path, previous_run: dict[str, Any],
                          summary: dict[str, Any]) -> None:
    """Append one line naming the run this invocation replaced (single writer).

    The chain is verifiable: each line carries the replaced summary's sha256, so a
    later reader can tell a first run from a repeat and follow the sequence.
    """

    path = task_dir / "out" / REPLAY_HISTORY_FILENAME
    entry = {
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "overwrote_summary_sha256": previous_run.get("summary_sha256"),
        "overwrote_generated_at": previous_run.get("generated_at"),
        "overwrote_status": previous_run.get("status"),
        "decision_scope": summary.get("decision_scope"),
        "reused_artifacts": [row.get("stage") for row in
                             summary.get("reused_artifacts") or []],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_run_summary(task_dir: Path, summary: dict[str, Any],
                      previous_run: dict[str, Any] | None = None) -> None:
    """Write the run summary, naming any run it replaced exactly once.

    The caller passes ``previous_run`` only for the first write of an invocation;
    later rewrites of the same summary must not append a second history line.
    """

    if previous_run is not None:
        summary["previous_run"] = previous_run
    path = task_dir / "out" / "daily_run_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if previous_run is not None:
        append_replay_history(task_dir, previous_run, summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pinned-epoch Daily Sync pipeline.")
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--thesis-evidence-file")
    parser.add_argument("--scenario-assumptions")
    parser.add_argument("--scenario-portfolio")
    parser.add_argument("--dashboard-root")
    parser.add_argument(
        "--risk-bounds-policy",
        help=("User-confirmed risk bounds policy (pia_risk_bounds_policy_v1). "
              "Defaults to <dashboard-root>/risk_bounds_policy.json or PIA_RISK_BOUNDS_POLICY."),
    )
    parser.add_argument("--skip-watchlist", action="store_true")
    parser.add_argument("--holiday-calendar-file")
    parser.add_argument("--coverage-probe-file")
    parser.add_argument("--risk-history", action="append", default=[],
                        help="symbol=path history for the optional risk diagnostic stage")
    parser.add_argument("--risk-fx-history", action="append", default=[],
                        help="PAIR=path fx history (e.g. USDCNY=…) for foreign-currency cash")
    parser.add_argument("--risk-base-currency")
    parser.add_argument("--risk-diagnostic-out")
    parser.add_argument(
        "--decision-scope",
        choices=("research_only", "advisory", "actionable"),
        default="advisory",
        help="Output contract for this run; defaults to advisory and propagates to the offline replay and thesis stages.",
    )
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--now-epoch", type=float)
    parser.add_argument(
        "--actionability-assessment",
        help=("Optional A-share terms snapshot (pia_cn_actionability_v1). Supplying it "
              "makes one command deliver the readiness verdict: the gate judges the "
              "supplied terms, its verdict is written to out/actionability_assessment.json "
              "and the actionable-readiness roll-up is appended to this summary."),
    )
    parser.add_argument(
        "--reuse-artifacts",
        action="store_true",
        help=("Reuse this task directory's own refresh/quotes artifacts instead of "
              "re-fetching, when they still prove they belong to this positions "
              "snapshot. Refuses loudly rather than reusing anything unverifiable."),
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Append this run to the append-only trigger ledger (idempotent per entry id).",
    )
    parser.add_argument("--ledger", help="Ledger path; defaults to the run's parent directory.")
    parser.add_argument(
        "--force",
        action="store_true",
        help=("Allow the refresh stage to overwrite an existing derived FX snapshot "
              "when re-running in the same task directory."),
    )
    args = parser.parse_args(argv)

    global DECISION_SCOPE
    DECISION_SCOPE = args.decision_scope

    positions_path = Path(args.positions_file).expanduser().resolve()
    task_dir = Path(args.task_dir).expanduser().resolve()
    # Read the run this invocation may replace *before* anything overwrites it.
    previous_run_pending = capture_previous_run(task_dir)
    cache_dir = (Path(args.cache_dir).expanduser().resolve() if args.cache_dir
                 else task_dir / "cache")
    holiday_calendar = (Path(args.holiday_calendar_file).expanduser().resolve()
                        if args.holiday_calendar_file else None)
    coverage_probes: list[dict[str, Any]] = []
    if args.coverage_probe_file:
        try:
            coverage_probes = load_coverage_probes(
                Path(args.coverage_probe_file).expanduser().resolve())
        except ValueError as exc:
            print(json.dumps({"status": "failed",
                              "detail_status": "coverage_probe_spec_invalid",
                              "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                             ensure_ascii=False, indent=2))
            return 3
    evaluation_epoch = args.now_epoch or datetime.datetime.now(datetime.timezone.utc).timestamp()
    stages: list[dict[str, Any]] = []
    risk_histories: list[dict[str, str]] = []
    risk_fx_histories: list[dict[str, str]] = []
    if args.risk_history or args.risk_fx_history:
        try:
            risk_histories = parse_risk_histories(args.risk_history, task_dir)
            risk_fx_histories = parse_fx_histories(args.risk_fx_history, task_dir)
        except ValueError as exc:
            print(json.dumps({"status": "failed",
                              "detail_status": "risk_history_spec_invalid",
                              "decision_scope": DECISION_SCOPE, "errors": [str(exc)]},
                             ensure_ascii=False, indent=2))
            return 3

    plan = ["refresh", "quotes", "daily_sync", "weights"]
    if not args.skip_watchlist:
        plan.append("watchlist")
    if coverage_probes:
        plan.append("coverage-probe")
    if risk_histories:
        plan.append("risk-diagnostic")
    if args.thesis_evidence_file:
        plan.append("daily_sync_with_thesis")
    if args.scenario_assumptions and args.scenario_portfolio:
        plan.append("scenario")
    if args.actionability_assessment:
        plan.append("actionability-gate")
    if args.plan_only:
        print(json.dumps({
            "status": "complete",
            "detail_status": "plan_only",
            "decision_scope": DECISION_SCOPE,
            "evaluation_epoch": evaluation_epoch,
            "plan": plan,
        }, ensure_ascii=False, indent=2))
        return 0

    if not positions_path.is_file():
        print(json.dumps({"status": "failed", "detail_status": "positions_file_missing",
                          "decision_scope": DECISION_SCOPE,
                          "errors": [str(positions_path)]}, ensure_ascii=False, indent=2))
        return 3

    def record(stage: str, code: int, payload: dict, artifacts: list[str] | None = None) -> bool:
        stages.append({
            "stage": stage,
            "status": status_from_payload(payload, code),
            "detail_status": payload.get("detail_status"),
            "decision_scope": payload.get("decision_scope") or DECISION_SCOPE,
            "exit_code": code,
            "artifacts": artifacts or [],
            "errors": payload.get("errors") or [],
            **{key: payload[key] for key in ("valid", "completeness") if key in payload},
        })
        return stages[-1]["status"] == "complete"

    # ---- stage 1: isolated FX refresh (writes a derived snapshot) -------------
    # ``--reuse-artifacts`` is opt-in and never silent: a reused stage says so in its
    # own record, because "this run read a snapshot" and "this run derived one now"
    # are different claims about the same file.
    reused_artifacts: list[dict[str, Any]] = []
    snapshot_path = task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
    if args.reuse_artifacts and snapshot_path.is_file():
        stages.append({
            "stage": "refresh",
            "status": "complete",
            "detail_status": "reused_derived_snapshot",
            "decision_scope": DECISION_SCOPE,
            "exit_code": 0,
            "artifacts": [str(snapshot_path)],
            "errors": [],
            "reused": True,
        })
        reused_artifacts.append({"stage": "refresh", "path": str(snapshot_path),
                                 "detail_status": "reused_derived_snapshot"})
    else:
        refresh_argv = ["--positions-file", str(positions_path), "--task-dir", str(task_dir),
                        "--cache-dir", str(cache_dir)]
        if args.force:
            # Re-running the pinned workflow in the same task dir must be an explicit
            # choice: the derived FX snapshot is a pipeline artifact, not user input.
            refresh_argv.append("--force")
        code, payload = run_module(pia_refresh.main, refresh_argv)
        if payload.get("status") in TERMINAL_COMPLETE and not snapshot_path.is_file():
            # A stage may not declare success without leaving the artifact the next
            # stages read; that would otherwise surface as a crash two stages later.
            payload = {**payload, "status": "failed",
                       "detail_status": "derived_snapshot_missing",
                       "errors": [f"refresh reported success but {snapshot_path} does not exist"],
                       "resolved": payload.get("resolved")}
            code = 3
        ok = record("refresh", code, payload, [str(snapshot_path)])
        if not ok:
            summary = finalize_run_summary(
                {"status": "insufficient_evidence", "detail_status": "refresh_stage_failed",
                 "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch,
                 "errors": payload.get("errors") or []},
                plan=plan, stages=stages, evaluation_epoch=evaluation_epoch,
                skip_watchlist=bool(args.skip_watchlist))
            write_run_summary(task_dir, summary, previous_run_pending)
            previous_run_pending = None
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return exit_code_for(summary["status"])

    positions = json.loads(snapshot_path.read_text(encoding="utf-8"))
    symbols = active_symbols(positions)

    # ---- stage 2: quote batch ------------------------------------------------
    if args.reuse_artifacts:
        reuse_ok, reuse_checks = reusable_quote_batch(task_dir / "out" / "quotes.json",
                                                     positions)
        if not reuse_ok:
            record("quotes", 3, {"status": "failed",
                                 "detail_status": "reuse_artifacts_unusable",
                                 "errors": [f"existing quote batch is not reusable: {reuse_checks}"]},
                   [])
            summary = finalize_run_summary(
                {"status": "insufficient_evidence", "detail_status": "reuse_artifacts_unusable",
                 "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch,
                 "errors": ["drop --reuse-artifacts to fetch a fresh quote batch"]},
                plan=plan, stages=stages, evaluation_epoch=evaluation_epoch,
                skip_watchlist=bool(args.skip_watchlist))
            write_run_summary(task_dir, summary, previous_run_pending)
            previous_run_pending = None
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return exit_code_for(summary["status"])
        quotes_path = task_dir / "out" / "quotes.json"
        stages.append({
            "stage": "quotes",
            "status": "complete",
            "detail_status": "reused_existing_quote_batch",
            "decision_scope": DECISION_SCOPE,
            "exit_code": 0,
            "artifacts": [str(quotes_path)],
            "errors": [],
            "reused": True,
            "reuse_checks": reuse_checks,
        })
        reused_artifacts.append({"stage": "quotes", "path": str(quotes_path),
                                 "detail_status": "reused_existing_quote_batch",
                                 "checks": reuse_checks})
    else:
        code, payload, quotes_path = run_quotes(snapshot_path, cache_dir, symbols, task_dir,
                                                holiday_calendar)
        ok = record("quotes", code, payload, [str(quotes_path)] if quotes_path else [])
        if not ok:
            summary = finalize_run_summary(
                {"status": "insufficient_evidence", "detail_status": "quote_stage_incomplete",
                 "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch},
                plan=plan, stages=stages, evaluation_epoch=evaluation_epoch,
                skip_watchlist=bool(args.skip_watchlist))
            write_run_summary(task_dir, summary, previous_run_pending)
            previous_run_pending = None
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return exit_code_for(summary["status"])

    # ---- stage 3: offline replay --------------------------------------------
    import daily_sync  # noqa: E402  (imported here: heavy module, only needed after quotes)
    replay_argv = ["--positions-file", str(snapshot_path), "--quotes-file", str(quotes_path),
                   "--now-epoch", str(evaluation_epoch), "--decision-scope", DECISION_SCOPE]
    if holiday_calendar is not None:
        replay_argv.extend(["--holiday-calendar-file", str(holiday_calendar)])
    pack = Path(args.thesis_evidence_file).expanduser().resolve() if args.thesis_evidence_file else None
    if pack is not None and pack.is_file():
        replay_argv.extend(["--thesis-evidence-file", str(pack)])
    code, payload = run_module(daily_sync.main, replay_argv)
    replay_code, replay_payload = code, payload
    replay_path = task_dir / "out" / "daily_sync.json"
    replay_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    quotes_complete = (payload.get("completeness") or {}).get("complete") is True
    record("daily_sync", code, payload, [str(replay_path)])
    if not quotes_complete or stages[-1]["status"] not in {"complete", "incomplete"}:
        summary = finalize_run_summary(
            {"status": "insufficient_evidence", "detail_status": "replay_stage_incomplete",
             "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch},
            plan=plan, stages=stages, evaluation_epoch=evaluation_epoch,
            skip_watchlist=bool(args.skip_watchlist))
        write_run_summary(task_dir, summary, previous_run_pending)
        previous_run_pending = None
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return exit_code_for(summary["status"])

    # ---- stage 4: current weights (15-minute freshness window) --------------
    import rebalance_weights  # noqa: E402
    # No --as-of-epoch here: that flag labels the output as a point-in-time replay,
    # and this stage must stay a *current* weight calculation.  The pinned epoch is
    # carried by the replay stage above and recorded in the run summary.
    weights_argv = ["--filepath", str(snapshot_path), "--quotes-file", str(replay_path)]
    if holiday_calendar is not None:
        weights_argv.extend(["--holiday-calendar-file", str(holiday_calendar)])
    code, payload = run_module(rebalance_weights.main, weights_argv)
    # Every row the user reads carries the code *and* the name from the same
    # authorized positions file, so tables never separate the two.
    weight_names = instrument_labels.symbol_name_map(positions)
    instrument_labels.annotate_rows(payload.get("current_weights"), weight_names)
    weights_path = task_dir / "out" / "weights.json"
    weights_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    weights_ok = record("weights", code, payload, [str(weights_path)])

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if weights_ok else "insufficient_evidence",
        "detail_status": "daily_run_complete" if weights_ok else "weights_stage_incomplete",
        "decision_scope": DECISION_SCOPE,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "evaluation_epoch": evaluation_epoch,
        "positions_input": str(positions_path),
        "positions_input_sha256": sha256_file(positions_path),
        "derived_snapshot": str(snapshot_path),
        "derived_snapshot_sha256": sha256_file(snapshot_path),
        "stages": stages,
        "non_executable": True,
    }
    if reused_artifacts:
        # Provenance of a reused run must survive into the summary, so a later reader
        # can tell which artifacts were derived now and which were carried over.
        summary["reused_artifacts"] = reused_artifacts

    # ---- optional stage: observation boundaries ------------------------------
    if weights_ok and not args.skip_watchlist:
        import dashboard_catalog  # noqa: E402
        import watchlist_gate  # noqa: E402
        # Dashboards live under the same holdings root as the positions file
        # (raw/stocks/<symbol>/generations/...); the caller may override it.
        dashboard_root = (Path(args.dashboard_root).expanduser().resolve()
                          if args.dashboard_root else positions_path.parent)
        catalog_argv = ["--root", str(dashboard_root), "--symbols", *symbols]
        code, catalog = run_module(dashboard_catalog.main, catalog_argv)
        (task_dir / "out" / "dashboard_catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

        # Policy-derived position limits (user thresholds -> bounds, never hand-typed).
        import position_limits  # noqa: E402
        policy_path = (Path(args.risk_bounds_policy).expanduser().resolve()
                       if args.risk_bounds_policy
                       else Path(os.environ.get("PIA_RISK_BOUNDS_POLICY")
                                 or dashboard_root / "risk_bounds_policy.json"))
        derived_path = None
        derived_block: dict[str, Any] = {"status": "not_supplied", "policy": str(policy_path)}
        if policy_path.is_file():
            try:
                policy = position_limits.load_policy(policy_path)
                derived_payload = position_limits.build(
                    payload, json.loads(positions_path.read_text(encoding="utf-8")),
                    policy=policy, policy_path=str(policy_path))
            except (position_limits.PolicyError, OSError, ValueError) as exc:
                derived_block = {"status": "invalid", "policy": str(policy_path),
                                 "errors": [f"{type(exc).__name__}: {exc}"]}
            else:
                derived_path = task_dir / "out" / "position_limits.json"
                derived_path.write_text(json.dumps(derived_payload, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                derived_block = {"status": "applied", "policy": str(policy_path),
                                 "path": str(derived_path),
                                 "policy_sha256": derived_payload["generated_from"]["policy_sha256"],
                                 "rules": derived_payload["rules"],
                                 "positions": len(derived_payload["positions"])}
        quote_rows = {row["symbol"]: row for row in
                      (payload.get("current_weights") or []) if row.get("symbol")}
        results: dict[str, Any] = {}
        crossed: list[str] = []
        evaluated: set[str] = set()
        for entry in catalog.get("entries") or []:
            symbol = entry.get("symbol")
            row = quote_rows.get(symbol)
            if row is None:
                results[symbol] = {"status": "insufficient_data", "reason": "quote_missing"}
                continue
            runtime = {"symbol": symbol, "current_price": row.get("current_price"),
                       "currency": row.get("currency"),
                       "as_of": (row.get("quote") or {}).get("as_of"),
                       "source": (row.get("quote") or {}).get("source"),
                       "market_state": (row.get("quote") or {}).get("market_state")}
            runtime_path = task_dir / "out" / f"runtime_quote_{symbol}.json"
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            # This limit was recomputed by the weight consumer from the verified
            # calendar and bound source quote; never trust a producer-declared age.
            age_limit = ((row.get("quote") or {}).get("freshness_policy") or {}).get("applied_max_age_seconds")
            freshness_argv = (["--max-age-seconds", str(age_limit)]
                              if holiday_calendar is not None and age_limit is not None else [])
            code, boundary = run_module(
                watchlist_gate.main,
                [entry["json_path"], "--quote-snapshot", str(runtime_path)]
                + freshness_argv
                + (["--derived-limits", str(derived_path)] if derived_path else []))
            (task_dir / "out" / f"watchlist_{symbol}.json").write_text(
                json.dumps(boundary, ensure_ascii=False, indent=2), encoding="utf-8")
            categories = boundary.get("categories") or {}
            results[symbol] = {"status": boundary.get("status"),
                               "detail_status": boundary.get("detail_status"),
                               "categories": categories}
            evaluated.add(symbol)
            crossed.extend((categories.get("downside_boundary_crossed") or [])
                           + (categories.get("upside_boundary_crossed") or []))
        (task_dir / "out" / "watchlist_results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        missing_boundaries = sorted(set(symbols) - evaluated)
        boundary_status = "complete" if not missing_boundaries else "insufficient_evidence"
        boundary_errors: list[str] = (
            [f"no gate-valid Dashboard found for: {', '.join(missing_boundaries)}"]
            if missing_boundaries else [])
        if derived_block["status"] == "invalid":
            boundary_status = "insufficient_evidence"
            boundary_errors.append(
                "risk bounds policy invalid: " + "; ".join(derived_block.get("errors") or []))
        stages.append({
            "stage": "watchlist",
            "status": boundary_status,
            "detail_status": (
                "derived_limits_policy_invalid" if derived_block["status"] == "invalid"
                else "boundaries_evaluated" if not missing_boundaries
                else "dashboard_catalog_incomplete"),
            "exit_code": 0,
            "artifacts": [str(task_dir / "out" / "watchlist_results.json")]
                         + ([str(derived_path)] if derived_path else []),
            "errors": boundary_errors,
            "crossed_boundaries": crossed,
            "dashboard_root": str(dashboard_root),
            "derived_limits": derived_block,
        })

    # ---- optional stage: channel coverage probing --------------------------
    # Placed after the critical path (refresh/quotes/replay/weights): a coverage probe
    # depends on nothing downstream, so it must never delay the weight calculation.
    if coverage_probes:
        import pia_etf_packet  # noqa: E402
        probe_results: list[dict[str, Any]] = []
        artifacts: list[str] = []
        for probe in coverage_probes:
            child = ["coverage-probe", "--channel", probe["channel"],
                     "--target", probe["target"], "--control", probe["control"],
                     "--target-class", probe["target_class"],
                     "--control-class", probe["control_class"],
                     "--channel-scope", probe["channel_scope"],
                     "--as-of-date", datetime.datetime.fromtimestamp(
                         evaluation_epoch, datetime.timezone.utc).date().isoformat(),
                     "--task-dir", str(task_dir),
                     "--window-days", str(probe["window_days"])]
            code, payload = run_module(pia_etf_packet.main, child)
            label = f"{probe['channel']}_{probe['target'].replace('.', '_')}"
            out_path = task_dir / "out" / f"coverage_probe_{label}.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
            artifacts.append(str(out_path))
            probe_results.append({"channel": probe["channel"], "target": probe["target"],
                                  "control": probe["control"],
                                  "verdict": payload.get("detail_status"),
                                  "target_count": payload.get("target_count"),
                                  "control_count": payload.get("control_count"),
                                  "coverage_basis": payload.get("coverage_basis"),
                                  "official_coverage_ready": bool(payload.get("official_coverage")),
                                  "query_quality_notes": payload.get("query_quality_notes") or []})
        unproven = [row for row in probe_results
                    if not str(row.get("verdict") or "").startswith("covered")]
        # The stage's job is to *probe*: it completes once every probe produced a
        # verdict.  An unproven verdict is data, not a stage failure — the same shape
        # the watchlist stage uses when some symbols have undefined thresholds — so it
        # is recorded as `unproven_probes` rather than as an error, and the envelope's
        # worst-case aggregation is not needlessly downgraded.
        stages.append({
            "stage": "coverage-probe",
            "status": "complete",
            "detail_status": ("coverage_proven" if not unproven
                              else "coverage_partially_unproven"),
            "exit_code": 0,
            "artifacts": artifacts,
            "errors": [],
            "probes": probe_results,
            "unproven_probes": [f"{row['channel']} {row['target']}: {row['verdict']}"
                                for row in unproven],
        })

    # ---- optional stage: partial risk diagnostic ---------------------------
    # Same placement rule as the coverage probe: it depends on nothing downstream and
    # must never delay the weight calculation.  Unlike the probe, this stage can fail
    # closed (no usable histories), which is recorded as an incomplete stage.
    if risk_histories:
        diag_out = (Path(args.risk_diagnostic_out).expanduser().resolve()
                    if args.risk_diagnostic_out else task_dir / "out" / "risk_diagnostic.json")
        child = ["--weights-file", str(weights_path), "--out", str(diag_out)]
        for history in risk_histories:
            child.extend(["--history", f"{history['symbol']}={history['path']}"])
        for history in risk_fx_histories:
            child.extend(["--fx-history", f"{history['pair']}={history['path']}"])
        if args.risk_base_currency:
            child.extend(["--base-currency", args.risk_base_currency])
        code, payload = run_module(pia_risk_diagnostic.main, child)
        coverage = payload.get("coverage") or {}
        contributions = payload.get("risk_contribution_within_subset") or {}
        top = sorted(contributions.items(), key=lambda item: -(item[1] or 0))[:3]
        stages.append({
            "stage": "risk-diagnostic",
            "status": "complete" if payload.get("status") == "complete" else "insufficient_data",
            "detail_status": payload.get("detail_status"),
            "exit_code": code,
            "artifacts": [str(diag_out)] if diag_out.is_file() else [],
            "errors": payload.get("errors") or [],
            "coverage": {
                "covered_count": coverage.get("covered_count"),
                "active_non_cash_count": coverage.get("active_non_cash_count"),
                "covered_share_of_non_cash_value": coverage.get(
                    "covered_share_of_non_cash_value"),
                "excluded_symbols": coverage.get("excluded_symbols") or [],
                "statement": coverage.get("statement"),
            },
            "observation_window": payload.get("observation_window"),
            "covered_subset_annualized_volatility": payload.get(
                "covered_subset_annualized_volatility"),
            "top_risk_contributions": [{"symbol": symbol, "contribution": value}
                                       for symbol, value in top],
            "method_labels": (payload.get("method") or {}).get("labels"),
            "value_coverage": payload.get("value_coverage"),
            "cash_fx_risk": {
                "legs": (payload.get("cash_fx_risk") or {}).get("legs") or [],
                "unmeasured_cash": (payload.get("cash_fx_risk") or {}).get("unmeasured_cash") or [],
                "measured_legs_combination": (payload.get("cash_fx_risk") or {}).get(
                    "measured_legs_combination"),
            },
        })

    # Preserve the historical thesis artifact without running a second replay.
    if pack is not None:
        if pack.is_file():
            out_path = task_dir / "out" / "daily_sync_with_thesis.json"
            out_path.write_text(json.dumps(replay_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            thesis = replay_payload.get("thesis_red_team") or {}
            stages.append({"stage": "daily_sync_with_thesis",
                           "status": status_from_payload(replay_payload, replay_code),
                           "detail_status": thesis.get("fatal_event_status"),
                           "exit_code": replay_code, "artifacts": [str(out_path)],
                           "errors": replay_payload.get("errors") or []})
        else:
            stages.append({"stage": "daily_sync_with_thesis", "status": "insufficient_evidence",
                           "detail_status": "thesis_pack_missing", "exit_code": 2,
                           "artifacts": [], "errors": [str(pack)]})

    # ---- optional stage: scenario replay ----------------------------------
    if args.scenario_assumptions and args.scenario_portfolio:
        import portfolio_scenario_analyzer  # noqa: E402
        result_path = task_dir / "out" / "scenario_result.json"
        code, payload = run_module(portfolio_scenario_analyzer.main, [
            str(Path(args.scenario_portfolio).expanduser().resolve()),
            str(Path(args.scenario_assumptions).expanduser().resolve()),
            "--output", str(result_path)])
        stages.append({"stage": "scenario",
                       "status": status_from_payload(payload, code),
                       "detail_status": payload.get("detail_status"),
                       "exit_code": code,
                       "artifacts": [str(result_path)] if result_path.is_file() else [],
                       "errors": payload.get("errors") or []})

    # ---- optional stage: actionability gate + readiness roll-up ------------
    # Supplying the terms snapshot is what turns "the pipeline finished" into one
    # readiness verdict.  The gate keeps its own native vocabulary, so the mapping is
    # explicit: an unexecutable-but-not-broken verdict (closed market, unmet terms) is
    # insufficient evidence, never a failure, and an unrecognised native status fails
    # closed rather than passing as complete.
    if args.actionability_assessment:
        import cn_actionability_gate  # noqa: E402
        snapshot = Path(args.actionability_assessment).expanduser().resolve()
        child = [str(snapshot)]
        if holiday_calendar:
            child.extend(["--holiday-calendar-file", str(holiday_calendar)])
        code, payload = run_module(cn_actionability_gate.main, child)
        gate_path = task_dir / "out" / "actionability_assessment.json"
        gate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        native = str(payload.get("status") or "")
        gate_status = {"complete": "complete",
                       "market_closed": "insufficient_evidence",
                       "insufficient_evidence": "insufficient_evidence",
                       "invalid_input": "failed",
                       "failed": "failed"}.get(native, "failed")
        stages.append({
            "stage": "actionability-gate",
            "status": gate_status,
            "detail_status": payload.get("detail_status") or native or None,
            "decision_scope": DECISION_SCOPE,
            "exit_code": code,
            "artifacts": [str(gate_path)],
            "errors": payload.get("errors") or [],
            "actionability": payload.get("actionability"),
        })
        if gate_status != "complete":
            summary["detail_status"] = f"actionability_gate_{native or 'unknown'}"

    (task_dir / "out").mkdir(parents=True, exist_ok=True)
    requested_stages = {"watchlist"} if not args.skip_watchlist else set()
    if coverage_probes:
        requested_stages.add("coverage-probe")
    if risk_histories:
        requested_stages.add("risk-diagnostic")
    if args.thesis_evidence_file:
        requested_stages.add("daily_sync_with_thesis")
    if args.scenario_assumptions and args.scenario_portfolio:
        requested_stages.add("scenario")
    if args.actionability_assessment:
        requested_stages.add("actionability-gate")
    # A stage the caller explicitly asked for, which then could not produce its
    # artifact, makes the run incomplete — the same rule for every requested stage.
    failed_requested = [stage["stage"] for stage in stages
                        if stage.get("stage") in requested_stages
                        and str(stage.get("status")) == "insufficient_data"]
    if failed_requested:
        summary["detail_status"] = "requested_stage_incomplete:" + ",".join(sorted(failed_requested))
    summary = finalize_run_summary(
        summary, plan=plan, stages=stages, evaluation_epoch=evaluation_epoch,
        skip_watchlist=bool(args.skip_watchlist))
    if summary["status"] == "incomplete" and not args.thesis_evidence_file:
        summary["detail_status"] = "thesis_not_assessed"
    elif summary["status"] == "incomplete" and args.thesis_evidence_file:
        summary["detail_status"] = "thesis_evidence_incomplete"
    write_run_summary(task_dir, summary, previous_run_pending)
    previous_run_pending = None
    # The roll-up judges the run from its own artifacts, so it is derived after the
    # summary lands on disk — and appended to it, so one command's output carries the
    # verdict instead of leaving the caller to run a second command.
    if args.actionability_assessment:
        artifacts, assessment = pia_readiness.load_run_artifacts(task_dir)
        rollup = pia_readiness.build_rollup(task_dir, artifacts, assessment)
        if rollup["scope_conflicts"]:
            rollup = {**rollup, "status": pia_readiness.STATUS_FAILED,
                      "detail_status": "decision_scope_conflict"}
        rollup_path = task_dir / "out" / "readiness_rollup.json"
        rollup_path.write_text(json.dumps(rollup, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        summary["readiness"] = rollup
    if args.record:
        import pia_trigger_ledger  # noqa: E402
        ledger = (Path(args.ledger).expanduser().resolve() if args.ledger
                  else task_dir.parent / pia_trigger_ledger.DEFAULT_LEDGER_NAME)
        ledger_code, ledger_payload = run_module(
            pia_trigger_ledger.main,
            ["append", "--run-dir", str(task_dir), "--ledger", str(ledger)])
        summary["ledger"] = {
            "ledger_file": str(ledger),
            "status": ledger_payload.get("status"),
            "detail_status": ledger_payload.get("detail_status"),
            "entry_id": ledger_payload.get("entry_id"),
            "appended": ledger_payload.get("appended"),
            "exit_code": ledger_code,
        }
    if args.actionability_assessment or args.record:
        write_run_summary(task_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code_for(summary["status"])


if __name__ == "__main__":
    raise SystemExit(main())
