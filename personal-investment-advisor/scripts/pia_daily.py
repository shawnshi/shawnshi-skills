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

import pia_refresh  # noqa: E402
import pia_risk_diagnostic  # noqa: E402

SCHEMA_VERSION = "pia_daily_run_v1"
DECISION_SCOPE = "research_only"
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


def active_symbols(positions: dict[str, Any]) -> list[str]:
    return [str(item.get("symbol")) for item in positions.get("positions", [])
            if isinstance(item, dict) and float(item.get("quantity") or 0) > 0
            and str(item.get("market") or "").upper() != "CASH"
            and str(item.get("asset_type") or "").lower() != "cash"]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the pinned-epoch Daily Sync pipeline.")
    parser.add_argument("--positions-file", required=True)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--thesis-evidence-file")
    parser.add_argument("--scenario-assumptions")
    parser.add_argument("--scenario-portfolio")
    parser.add_argument("--dashboard-root")
    parser.add_argument("--skip-watchlist", action="store_true")
    parser.add_argument("--holiday-calendar-file")
    parser.add_argument("--coverage-probe-file")
    parser.add_argument("--risk-history", action="append", default=[],
                        help="symbol=path history for the optional risk diagnostic stage")
    parser.add_argument("--risk-fx-history", action="append", default=[],
                        help="PAIR=path fx history (e.g. USDCNY=…) for foreign-currency cash")
    parser.add_argument("--risk-base-currency")
    parser.add_argument("--risk-diagnostic-out")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--now-epoch", type=float)
    args = parser.parse_args(argv)

    positions_path = Path(args.positions_file).expanduser().resolve()
    task_dir = Path(args.task_dir).expanduser().resolve()
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
            "status": payload.get("status"),
            "detail_status": payload.get("detail_status"),
            "exit_code": code,
            "artifacts": artifacts or [],
            "errors": payload.get("errors") or [],
        })
        return payload.get("status") in TERMINAL_COMPLETE

    # ---- stage 1: isolated FX refresh (writes a derived snapshot) -------------
    refresh_argv = ["--positions-file", str(positions_path), "--task-dir", str(task_dir),
                    "--cache-dir", str(cache_dir)]
    code, payload = run_module(pia_refresh.main, refresh_argv)
    snapshot_path = task_dir / "inputs" / pia_refresh.DERIVED_FILENAME
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
        summary = {"status": "insufficient_evidence", "detail_status": "refresh_stage_failed",
                   "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch,
                   "stages": stages, "errors": payload.get("errors") or []}
        (task_dir / "out").mkdir(parents=True, exist_ok=True)
        (task_dir / "out" / "daily_run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    positions = json.loads(snapshot_path.read_text(encoding="utf-8"))
    symbols = active_symbols(positions)

    # ---- stage 2: quote batch ------------------------------------------------
    code, payload, quotes_path = run_quotes(snapshot_path, cache_dir, symbols, task_dir,
                                            holiday_calendar)
    ok = record("quotes", code, payload, [str(quotes_path)] if quotes_path else [])
    if not ok:
        summary = {"status": "insufficient_evidence", "detail_status": "quote_stage_incomplete",
                   "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch,
                   "stages": stages}
        (task_dir / "out").mkdir(parents=True, exist_ok=True)
        (task_dir / "out" / "daily_run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    # ---- stage 3: offline replay --------------------------------------------
    import daily_sync  # noqa: E402  (imported here: heavy module, only needed after quotes)
    replay_argv = ["--positions-file", str(snapshot_path), "--quotes-file", str(quotes_path),
                   "--now-epoch", str(evaluation_epoch), "--decision-scope", DECISION_SCOPE]
    if holiday_calendar is not None:
        replay_argv.extend(["--holiday-calendar-file", str(holiday_calendar)])
    code, payload = run_module(daily_sync.main, replay_argv)
    replay_path = task_dir / "out" / "daily_sync.json"
    replay_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    quotes_complete = bool((payload.get("completeness") or {}).get("complete"))
    record("daily_sync", code, {"status": "complete" if quotes_complete else payload.get("status"),
                                "detail_status": payload.get("detail_status"),
                                "errors": payload.get("errors") if not quotes_complete else []},
           [str(replay_path)])
    if not quotes_complete:
        summary = {"status": "insufficient_evidence", "detail_status": "replay_stage_incomplete",
                   "decision_scope": DECISION_SCOPE, "evaluation_epoch": evaluation_epoch,
                   "stages": stages}
        (task_dir / "out" / "daily_run_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    # ---- stage 4: current weights (15-minute freshness window) --------------
    import rebalance_weights  # noqa: E402
    # No --as-of-epoch here: that flag labels the output as a point-in-time replay,
    # and this stage must stay a *current* weight calculation.  The pinned epoch is
    # carried by the replay stage above and recorded in the run summary.
    weights_argv = ["--filepath", str(snapshot_path), "--quotes-file", str(replay_path)]
    code, payload = run_module(rebalance_weights.main, weights_argv)
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
            code, boundary = run_module(
                watchlist_gate.main, [entry["json_path"], "--quote-snapshot", str(runtime_path)])
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
        stages.append({
            "stage": "watchlist",
            "status": boundary_status,
            "detail_status": ("boundaries_evaluated" if not missing_boundaries
                              else "dashboard_catalog_incomplete"),
            "exit_code": 0,
            "artifacts": [str(task_dir / "out" / "watchlist_results.json")],
            "errors": ([f"no gate-valid Dashboard found for: {', '.join(missing_boundaries)}"]
                       if missing_boundaries else []),
            "crossed_boundaries": crossed,
            "dashboard_root": str(dashboard_root),
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

    # ---- optional stage: thesis evidence replay ----------------------------
    if args.thesis_evidence_file:
        pack = Path(args.thesis_evidence_file).expanduser().resolve()
        if pack.is_file():
            thesis_argv = [
                "--positions-file", str(snapshot_path), "--quotes-file", str(quotes_path),
                "--now-epoch", str(evaluation_epoch), "--decision-scope", DECISION_SCOPE,
                "--thesis-evidence-file", str(pack)]
            if holiday_calendar is not None:
                thesis_argv.extend(["--holiday-calendar-file", str(holiday_calendar)])
            code, payload = run_module(daily_sync.main, thesis_argv)
            out_path = task_dir / "out" / "daily_sync_with_thesis.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            thesis = payload.get("thesis_red_team") or {}
            stages.append({"stage": "daily_sync_with_thesis",
                           "status": thesis.get("status") or payload.get("status"),
                           "detail_status": thesis.get("fatal_event_status"),
                           "exit_code": code, "artifacts": [str(out_path)],
                           "errors": payload.get("errors") or []})
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
                       "status": payload.get("status") or ("complete" if code == 0 else "failed"),
                       "detail_status": payload.get("detail_status"),
                       "exit_code": code,
                       "artifacts": [str(result_path)] if result_path.is_file() else [],
                       "errors": payload.get("errors") or []})

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
    # A stage the caller explicitly asked for, which then could not produce its
    # artifact, makes the run incomplete — the same rule for every requested stage.
    failed_requested = [stage["stage"] for stage in stages
                        if stage.get("stage") in requested_stages
                        and str(stage.get("status")) == "insufficient_data"]
    if failed_requested and summary["status"] == "complete":
        summary["status"] = "insufficient_evidence"
        summary["detail_status"] = "requested_stage_incomplete:" + ",".join(sorted(failed_requested))
    (task_dir / "out" / "daily_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
