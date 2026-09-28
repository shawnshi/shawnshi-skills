"""Stable, injection-safe command router for Personal Investment Advisor.

This entrypoint is deliberately thin.  It invokes existing business scripts
with fixed executable paths and explicit argument lists, then wraps their
native output in ``status_contract.py``.  It never uses a command shell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NoReturn, Sequence

from status_contract import (
    CONTRACT_VERSION,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_INSUFFICIENT_EVIDENCE,
    exit_code_for,
    make_envelope,
    status_from_payload,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CHILD_TIMEOUT_SECONDS = 300
MAX_CHILD_STREAM_BYTES = 32 * 1024 * 1024
CHILD_READ_BYTES = 64 * 1024
CHILD_CLEANUP_SECONDS = 1.0


class ChildCapabilityError(RuntimeError):
    pass


class ChildOutputLimitError(RuntimeError):
    pass


def _check_nonblocking_pipes() -> None:
    """Probe before launching business code (Windows requires Python >=3.12)."""
    try:
        reader, writer = os.pipe()
    except OSError as exc:
        raise ChildCapabilityError(f"nonblocking pipe probe unavailable: {exc}") from exc
    try:
        try:
            os.set_blocking(reader, False)
            try:
                os.read(reader, 1)
            except BlockingIOError:
                return
            raise ChildCapabilityError("nonblocking pipe probe did not report would-block")
        except (OSError, AttributeError, NotImplementedError) as exc:
            raise ChildCapabilityError(f"nonblocking pipes unavailable: {exc}") from exc
    finally:
        os.close(reader)
        os.close(writer)


def _reap_child(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=CHILD_CLEANUP_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=CHILD_CLEANUP_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("child_cleanup_failed: exact child did not exit after kill") from exc


def _execute_child(invocation: list[str]) -> subprocess.CompletedProcess:
    """Fair, bounded binary pipe reads; own no reader threads or temp transport.

    Only the exact child is owned. After it exits, drain currently available
    bytes, but never wait for EOF from inherited descendant pipe handles.
    """
    _check_nonblocking_pipes()
    deadline = time.monotonic() + CHILD_TIMEOUT_SECONDS
    process = subprocess.Popen(
        invocation, cwd=str(SCRIPT_DIR), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, shell=False, bufsize=0,
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    streams = {name: stream for name, stream in
               (("stdout", process.stdout), ("stderr", process.stderr)) if stream is not None}
    try:
        for stream in streams.values():
            os.set_blocking(stream.fileno(), False)
        open_streams = dict(streams)
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(invocation, CHILD_TIMEOUT_SECONDS)
            exited = process.poll() is not None
            received = False
            for name, stream in list(open_streams.items()):
                remaining = MAX_CHILD_STREAM_BYTES - len(buffers[name])
                try:
                    data = os.read(stream.fileno(), min(CHILD_READ_BYTES, remaining + 1))
                except BlockingIOError:
                    continue
                except BrokenPipeError:
                    data = b""
                if not data:
                    del open_streams[name]
                    continue
                received = True
                if len(data) > remaining:
                    raise ChildOutputLimitError(
                        f"{name} exceeded {MAX_CHILD_STREAM_BYTES} bytes; partial output discarded"
                    )
                buffers[name].extend(data)
            if exited and not received:
                break
            if not received:
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
        return subprocess.CompletedProcess(
            invocation, process.returncode,
            buffers["stdout"].decode("utf-8", errors="replace"),
            buffers["stderr"].decode("utf-8", errors="replace"),
        )
    finally:
        for stream in streams.values():
            stream.close()
        _reap_child(process)


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit the same machine-readable failure contract for CLI usage errors."""

    def error(self, message: str) -> NoReturn:
        envelope = make_envelope(
            command="cli",
            status=STATUS_FAILED,
            detail_status="cli_usage_error",
            errors=[message],
        )
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
        raise SystemExit(exit_code_for(STATUS_FAILED))


def _child_script(name: str) -> Path:
    """Resolve one fixed in-skill child script and reject path drift."""

    candidate = (SCRIPT_DIR / name).resolve()
    if candidate.parent != SCRIPT_DIR or candidate.suffix != ".py":
        raise ValueError(f"unsafe child script route: {name}")
    return candidate


def _append_option(command: list[str], flag: str, value: Any) -> None:
    if value is not None:
        command.extend([flag, str(value)])


def _parse_json_output(stdout: str) -> Any:
    rendered = stdout.strip()
    if not rendered:
        raise ValueError("child command returned empty stdout")
    return json.loads(rendered)


def _output_signature(path: Path | None) -> tuple[int, int] | None:
    if path is None or not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _path_argument(value: str) -> str:
    """Bind user paths to the caller's cwd once, before routing or alias checks."""

    try:
        return str(Path(value).expanduser().resolve(strict=False))
    except (OSError, RuntimeError) as exc:
        raise argparse.ArgumentTypeError(f"cannot resolve path {value!r}: {exc}") from exc


def _same_file(left: Path, right: Path) -> bool:
    if left == right:
        return True
    try:
        return left.exists() and right.exists() and left.samefile(right)
    except OSError:
        return False


def _path_conflict_failure(
    *, command: str, completion_scope: str, message: str
) -> tuple[dict[str, Any], int]:
    envelope = make_envelope(
        command=command,
        status=STATUS_FAILED,
        detail_status="output_path_conflicts_with_input",
        errors=[message],
        completion_scope=completion_scope,
    )
    return envelope, exit_code_for(envelope["status"])


def _screen_status(payload: Any, child_exit_code: int) -> str:
    """Interpret quality-screen business pass/fail separately from CLI failure."""

    if child_exit_code < 0 or child_exit_code >= exit_code_for(STATUS_FAILED):
        return STATUS_FAILED
    if not isinstance(payload, list) or not payload:
        return STATUS_FAILED
    native = [
        item.get("status") if isinstance(item, dict) else None for item in payload
    ]
    allowed = {"pass", "fail", "insufficient_data", "insufficient_evidence", "not_applicable"}
    if any(not isinstance(status, str) or status not in allowed for status in native):
        return STATUS_FAILED
    if any(
        status in {"insufficient_data", "insufficient_evidence", "not_applicable"}
        for status in native
    ):
        return STATUS_INSUFFICIENT_EVIDENCE
    if all(status in {"pass", "fail"} for status in native):
        return STATUS_COMPLETE if child_exit_code == 0 else STATUS_FAILED
    return STATUS_FAILED


CHILD_ERROR_EXCERPT_LIMIT = 5
CHILD_TEXT_EXCERPT_CHARS = 400
CHILD_STDOUT_PARSE_LIMIT_CHARS = 65536


def _child_failure_details(
    completed: subprocess.CompletedProcess[str],
) -> tuple[list[str], dict[str, Any]]:
    """Recover a child's own structured failure reason.

    A child that fails a business contract writes its precise reason to stdout
    (for example the scenario analyzer's ``weight_snapshot.source_locator``
    error) and exits non-zero with an empty stderr.  Reporting only stderr
    replaced that machine-readable cause with a generic "no output file"
    message, which forced the caller to re-run the child by hand.  The child's
    stdout is untrusted input here: parsing is bounded and never raises.
    """

    details: list[str] = []
    route_extra: dict[str, Any] = {}
    raw_stdout = (completed.stdout or "").strip()
    if raw_stdout:
        try:
            payload = json.loads(raw_stdout[:CHILD_STDOUT_PARSE_LIMIT_CHARS])
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            for field in ("detail_status", "status"):
                value = payload.get(field)
                if isinstance(value, str) and value.strip():
                    route_extra[f"child_{field}"] = value.strip()
            candidates: list[Any] = []
            for source in (payload, payload.get("result")):
                if isinstance(source, dict) and isinstance(source.get("errors"), list):
                    candidates.extend(source["errors"])
            for candidate in candidates[:CHILD_ERROR_EXCERPT_LIMIT]:
                if isinstance(candidate, str) and candidate.strip():
                    details.append(f"child: {candidate.strip()}")
    stderr_excerpt = (completed.stderr or "").strip()
    if stderr_excerpt:
        route_extra["child_stderr_excerpt"] = stderr_excerpt[:CHILD_TEXT_EXCERPT_CHARS]
    return details, route_extra


def _run_child(
    *,
    public_command: str,
    script_name: str,
    child_arguments: Sequence[str],
    completion_scope: str,
    limitations: Sequence[str] = (),
    output_mode: str = "json",
    required_output: Path | None = None,
) -> tuple[dict[str, Any], int]:
    script = _child_script(script_name)
    invocation = [sys.executable, str(script), *map(str, child_arguments)]
    route = {
        "script": script.name,
        "shell": False,
    }
    output_before = _output_signature(required_output)
    try:
        completed = _execute_child(invocation)
    except (ChildCapabilityError, ChildOutputLimitError) as exc:
        envelope = make_envelope(
            command=public_command,
            status=STATUS_FAILED,
            detail_status=("child_output_size_limit" if isinstance(exc, ChildOutputLimitError)
                           else "child_transport_unavailable"),
            errors=[str(exc)],
            limitations=limitations,
            route=route,
            completion_scope=completion_scope,
        )
        return envelope, exit_code_for(envelope["status"])
    except subprocess.TimeoutExpired:
        envelope = make_envelope(
            command=public_command,
            status=STATUS_FAILED,
            detail_status="child_timeout",
            errors=[f"child command exceeded {CHILD_TIMEOUT_SECONDS} seconds"],
            limitations=limitations,
            route=route,
            completion_scope=completion_scope,
        )
        return envelope, exit_code_for(envelope["status"])
    except (OSError, ValueError) as exc:
        envelope = make_envelope(
            command=public_command,
            status=STATUS_FAILED,
            detail_status="child_launch_failed",
            errors=[str(exc)],
            limitations=limitations,
            route=route,
            completion_scope=completion_scope,
        )
        return envelope, exit_code_for(envelope["status"])

    route["child_exit_code"] = completed.returncode
    diagnostics = completed.stderr.strip()

    if output_mode == "text":
        output_after = _output_signature(required_output)
        output_exists = output_after is not None and output_after != output_before
        status = (
            STATUS_COMPLETE
            if completed.returncode == 0 and output_exists
            else STATUS_FAILED
        )
        detail = (
            "report_written"
            if status == STATUS_COMPLETE
            else "report_not_verified"
        )
        errors = []
        if status == STATUS_FAILED:
            child_details, route_extra = _child_failure_details(completed)
            route = {**route, **route_extra}
            errors.extend(child_details)
            errors.append(diagnostics or "child did not produce the required report")
        envelope = make_envelope(
            command=public_command,
            status=status,
            detail_status=detail,
            result={
                "stdout": completed.stdout.strip(),
                "output_path": str(required_output) if required_output else None,
            },
            errors=errors,
            limitations=limitations,
            route=route,
            completion_scope=completion_scope,
        )
        return envelope, exit_code_for(envelope["status"])

    if output_mode == "json_file":
        output_after = _output_signature(required_output)
        if (
            completed.returncode != 0
            or required_output is None
            or output_after is None
            or output_after == output_before
        ):
            child_details, route_extra = _child_failure_details(completed)
            envelope = make_envelope(
                command=public_command,
                status=STATUS_FAILED,
                detail_status="json_output_file_not_verified",
                errors=[
                    *child_details,
                    diagnostics or "child did not publish a new JSON output file",
                ],
                limitations=limitations,
                route={**route, **route_extra},
                completion_scope=completion_scope,
            )
            return envelope, exit_code_for(envelope["status"])
        try:
            with required_output.open("rb") as stream:
                output_bytes = stream.read(MAX_CHILD_STREAM_BYTES + 1)
            if len(output_bytes) > MAX_CHILD_STREAM_BYTES:
                raise ValueError(f"json_output_file_size_limit: exceeds {MAX_CHILD_STREAM_BYTES} bytes")
            rendered_output = output_bytes.decode("utf-8")
        except (OSError, ValueError) as exc:
            envelope = make_envelope(
                command=public_command,
                status=STATUS_FAILED,
                detail_status="json_output_file_unreadable",
                errors=[str(exc)],
                limitations=limitations,
                route=route,
                completion_scope=completion_scope,
            )
            return envelope, exit_code_for(envelope["status"])
    else:
        rendered_output = completed.stdout

    try:
        payload = _parse_json_output(rendered_output)
    except (json.JSONDecodeError, ValueError) as exc:
        errors = [f"child output is not one JSON value: {exc}"]
        if diagnostics:
            errors.append(diagnostics)
        envelope = make_envelope(
            command=public_command,
            status=STATUS_FAILED,
            detail_status="child_output_invalid",
            errors=errors,
            limitations=limitations,
            route=route,
            completion_scope=completion_scope,
        )
        return envelope, exit_code_for(envelope["status"])

    if public_command == "portfolio-audit":
        context = payload.get("portfolio_context", {}) if isinstance(payload, dict) else {}
        native_status = context.get("position_status")
        if completed.returncode != 0:
            status = STATUS_FAILED
            detail = "portfolio_context_command_failed"
        elif native_status in {"not_configured", "file_missing", "not_found"}:
            status = STATUS_INSUFFICIENT_EVIDENCE
            detail = str(native_status)
        elif isinstance(payload, dict):
            status = STATUS_INCOMPLETE
            detail = "position_context_only"
        else:
            status = STATUS_FAILED
            detail = "portfolio_context_contract_unknown"
    elif public_command == "screen":
        status = _screen_status(payload, completed.returncode)
        detail = (
            "screen_completed"
            if status == STATUS_COMPLETE
            else "screen_evidence_or_execution_incomplete"
        )
    else:
        status = status_from_payload(payload, completed.returncode)
        native_detail = payload.get("detail_status") if isinstance(payload, dict) else None
        detail = str(native_detail or "child_status_normalized")

    errors: list[str] = []
    if status == STATUS_FAILED and diagnostics:
        errors.append(diagnostics)
    envelope = make_envelope(
        command=public_command,
        status=status,
        detail_status=detail,
        result=payload,
        errors=errors,
        limitations=limitations,
        route=route,
        completion_scope=completion_scope,
    )
    return envelope, exit_code_for(envelope["status"])


def _build_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(
        description="Personal Investment Advisor stable command router."
    )
    parser.add_argument("--version", action="version", version=CONTRACT_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    research = subparsers.add_parser(
        "research", help="Validate a structured research brief before research."
    )
    research.add_argument("brief_json", type=_path_argument)

    screen = subparsers.add_parser(
        "screen", help="Run the profile-driven financial quality pre-screen."
    )
    screen.add_argument("--tickers", nargs="+", required=True)
    screen.add_argument("--profile", required=True)
    screen.add_argument("--market")
    screen.add_argument("--asset-type")
    screen.add_argument("--as-of-date")
    screen.add_argument("--industry-type")
    screen.add_argument("--profiles-file", type=_path_argument)

    edgar = subparsers.add_parser(
        "edgar-fundamentals",
        help="Build free point-in-time annual fundamentals from SEC EDGAR.",
    )
    edgar.add_argument("symbols", nargs="+")
    edgar.add_argument("--as-of", required=True)
    edgar.add_argument("--user-agent")
    edgar.add_argument("--timeout", type=float)
    edgar.add_argument(
        "--decision-scope",
        choices=("research_only", "advisory", "actionable"),
    )

    portfolio = subparsers.add_parser(
        "portfolio-audit",
        help="Load validated portfolio and position context; full audit remains external.",
    )
    portfolio.add_argument("symbol")
    portfolio.add_argument("--positions-file", required=True, type=_path_argument)
    portfolio.add_argument("--current-price", type=float)

    daily = subparsers.add_parser(
        "daily-sync", help="Audit a supplied portfolio and quote package offline."
    )
    daily.add_argument("--positions-file", required=True, type=_path_argument)
    daily.add_argument("--quotes-file", required=True, type=_path_argument)
    daily.add_argument("--holiday-calendar-file", type=_path_argument)
    daily.add_argument("--thesis-evidence-file", type=_path_argument)
    daily.add_argument("--now-epoch", type=float)
    daily.add_argument("--max-quote-age-seconds", type=int)
    daily.add_argument(
        "--decision-scope",
        choices=("research_only", "advisory", "actionable"),
    )

    scenario = subparsers.add_parser(
        "scenario", help="Run the explicit-input portfolio scenario analyzer."
    )
    scenario.add_argument("portfolio_json", type=_path_argument)
    scenario.add_argument("assumptions_json", type=_path_argument)
    scenario.add_argument("--output", type=_path_argument)

    calibrate = subparsers.add_parser(
        "calibrate", help="Write the benchmark-aware decision outcome report."
    )
    calibrate.add_argument(
        "--journal-path", type=_path_argument, default=os.environ.get("PIA_ADVICE_JOURNAL")
    )
    calibrate.add_argument("--output-path", required=True, type=_path_argument)

    alpha_validate = subparsers.add_parser(
        "alpha-validate",
        help="Validate a point-in-time alpha package against promotion gates.",
    )
    alpha_validate.add_argument("alpha_package", type=_path_argument)
    alpha_validate.add_argument("--policy-file", required=True, type=_path_argument)
    alpha_validate.add_argument("--output", type=_path_argument)
    alpha_validate.add_argument("--force", action="store_true")

    alpha_scan = subparsers.add_parser(
        "alpha-scan",
        help="Rank signals from an alpha package that passed validation.",
    )
    alpha_scan.add_argument("alpha_package", type=_path_argument)
    alpha_scan.add_argument("--validation-report", required=True, type=_path_argument)
    alpha_scan.add_argument("--policy-file", required=True, type=_path_argument)
    alpha_scan.add_argument("--output", type=_path_argument)
    alpha_scan.add_argument("--force", action="store_true")

    construct = subparsers.add_parser(
        "portfolio-construct",
        help="Construct ERC and robust active research candidates offline.",
    )
    construct.add_argument("scan_report", type=_path_argument)
    construct.add_argument("--policy-file", required=True, type=_path_argument)
    construct.add_argument("--output", type=_path_argument)
    construct.add_argument("--force", action="store_true")

    proposal = subparsers.add_parser(
        "rebalance-proposal",
        help="Compare current and candidate allocations without execution.",
    )
    proposal.add_argument("construction_report", type=_path_argument)
    proposal.add_argument("--policy-file", required=True, type=_path_argument)
    proposal.add_argument("--output", type=_path_argument)
    proposal.add_argument("--force", action="store_true")

    validate = subparsers.add_parser(
        "validate", help="Run a selected current contract gate."
    )
    validate.add_argument(
        "kind",
        choices=("research-brief", "dashboard", "dashboard-math", "history"),
    )
    validate.add_argument("json_path", type=_path_argument)

    refresh = subparsers.add_parser(
        "refresh",
        help="Write an isolated FX-refreshed portfolio snapshot for downstream gates.",
    )
    refresh.add_argument("--positions-file", required=True, type=_path_argument)
    refresh.add_argument("--task-dir", required=True, type=_path_argument)
    refresh.add_argument("--cache-dir", type=_path_argument)
    refresh.add_argument("--fx-observation-file", type=_path_argument)
    refresh.add_argument(
        "--fx-pair", action="append", default=[],
        help="Explicit currency=yahoo-symbol override, repeatable (e.g. USD=CNY=X).",
    )
    refresh.add_argument("--max-fx-age-hours", type=float)
    refresh.add_argument("--force", action="store_true")

    daily_run = subparsers.add_parser(
        "daily-run",
        help="Run the pinned-epoch Daily Sync pipeline (refresh, quotes, replay, weights).",
    )
    daily_run.add_argument("--positions-file", required=True, type=_path_argument)
    daily_run.add_argument("--task-dir", required=True, type=_path_argument)
    daily_run.add_argument("--cache-dir", type=_path_argument)
    daily_run.add_argument("--thesis-evidence-file", type=_path_argument)
    daily_run.add_argument("--scenario-assumptions", type=_path_argument)
    daily_run.add_argument("--scenario-portfolio", type=_path_argument)
    daily_run.add_argument("--dashboard-root", type=_path_argument)
    daily_run.add_argument("--skip-watchlist", action="store_true")
    daily_run.add_argument("--holiday-calendar-file", type=_path_argument)
    daily_run.add_argument("--coverage-probe-file", type=_path_argument)
    daily_run.add_argument("--risk-history", action="append", default=[],
                           help="symbol=path history for the optional risk diagnostic stage")
    daily_run.add_argument("--risk-fx-history", action="append", default=[],
                           help="PAIR=path fx history (e.g. USDCNY=…) for foreign-currency cash")
    daily_run.add_argument("--risk-base-currency")
    daily_run.add_argument("--risk-diagnostic-out", type=_path_argument)
    daily_run.add_argument("--plan-only", action="store_true")
    daily_run.add_argument("--now-epoch", type=float)

    build = subparsers.add_parser(
        "build",
        help="Build gate-ready active-research inputs from upstream artifacts.",
    )
    build.add_argument(
        "kind", choices=("scenario", "inverse-vol", "thesis-pack", "dataset-manifest")
    )
    build.add_argument("--task-dir", required=True, type=_path_argument)
    build.add_argument("--weights-file", type=_path_argument)
    build.add_argument("--confirmed-policy", type=_path_argument)
    build.add_argument("--positions-file", type=_path_argument)
    build.add_argument("--volatilities-file", type=_path_argument)
    build.add_argument("--quotes-file", type=_path_argument)
    build.add_argument("--evidence-file", type=_path_argument)
    build.add_argument("--assessments-file", type=_path_argument)
    build.add_argument("--scope-coverage-file", type=_path_argument)
    build.add_argument("--window-start")
    build.add_argument("--window-end")
    build.add_argument(
        "--artifact", action="append", default=[],
        help="relative-path=local-file, repeatable (dataset-manifest only)",
    )
    build.add_argument("--force", action="store_true")

    etf_packet = subparsers.add_parser(
        "etf-packet",
        help="Assemble and verify an ETF history-integrity packet from operator evidence.",
    )
    etf_packet.add_argument("--evidence-file", required=True, type=_path_argument)
    etf_packet.add_argument("--task-dir", required=True, type=_path_argument)
    etf_packet.add_argument("--symbol")
    etf_packet.add_argument("--as-of-date")
    etf_packet.add_argument("--provider-source")
    etf_packet.add_argument("--provider-source-locator")
    etf_packet.add_argument("--provider-adjustment")
    etf_packet.add_argument("--allow-unverified", action="store_true")
    etf_packet.add_argument("--force", action="store_true")

    history = subparsers.add_parser(
        "history",
        help="Index PIA task runs and diff them (what changed since the last run).",
    )
    history.add_argument("kind", choices=("index", "diff"))
    history.add_argument("--task-root", required=True, type=_path_argument)
    history.add_argument("--depth", type=int)
    history.add_argument("--registry", type=_path_argument)
    history.add_argument("--write", action="store_true")
    history.add_argument("--output", type=_path_argument)
    history.add_argument("--from", dest="run_from")
    history.add_argument("--to", dest="run_to")
    history.add_argument("--summary", action="store_true")

    report = subparsers.add_parser(
        "report", help="Render one run directory to a deterministic Markdown report.",
    )
    report.add_argument("--run-dir", required=True, type=_path_argument)
    report.add_argument("--out", type=_path_argument)

    trigger = subparsers.add_parser(
        "trigger-ledger",
        help="Append-only run-trigger ledger: record what a run flagged, then review it.",
    )
    trigger.add_argument("kind", choices=("append", "list", "due", "close"))
    trigger.add_argument("--run-dir", type=_path_argument)
    trigger.add_argument("--task-root", type=_path_argument)
    trigger.add_argument("--ledger", type=_path_argument)
    trigger.add_argument("--review-days", type=int)
    trigger.add_argument("--now")
    trigger.add_argument("--symbol")
    trigger.add_argument("--limit", type=int)
    trigger.add_argument("--as-of")
    trigger.add_argument("--entry-id")
    trigger.add_argument("--note")
    trigger.add_argument("--outcome")

    thesis = subparsers.add_parser(
        "thesis-ledger",
        help="Versioned ledger of user-confirmed thesis conditions.",
    )
    thesis.add_argument("kind", choices=("init", "append", "show", "list"))
    thesis.add_argument("--file", required=True, type=_path_argument)
    thesis.add_argument("--symbol")
    thesis.add_argument("--confirmed-at")
    thesis.add_argument("--source-locator")
    thesis.add_argument("--conditions-file", type=_path_argument)
    thesis.add_argument("--note")
    thesis.add_argument("--as-of")
    thesis.add_argument("--force", action="store_true")

    labels = subparsers.add_parser(
        "labels", help="Interpretive label vocabulary checks and drift measurement.",
    )
    labels.add_argument("kind", choices=("vocab", "check"))
    labels.add_argument("--axis")
    labels.add_argument("--file", type=_path_argument)
    labels.add_argument("--previous", type=_path_argument)
    labels.add_argument("--vocabulary-file", type=_path_argument)

    review = subparsers.add_parser(
        "review-pack",
        help="Emit an independent review brief (declared tools + hashed inputs) for a run.",
    )
    review.add_argument("--lane", required=True)
    review.add_argument("--run-dir", required=True, type=_path_argument)
    review.add_argument("--out", type=_path_argument)
    review.add_argument("--lanes-file", type=_path_argument)

    calendar = subparsers.add_parser(
        "calendar",
        help="Build or query the verified market holiday table (quote-freshness basis).",
    )
    calendar.add_argument("kind", choices=("build", "closed"))
    calendar.add_argument("--cn-html", type=_path_argument)
    calendar.add_argument("--us-html", type=_path_argument)
    calendar.add_argument("--cn-locator")
    calendar.add_argument("--us-locator")
    calendar.add_argument("--retrieved-at")
    calendar.add_argument("--table", type=_path_argument)
    calendar.add_argument("--market")
    calendar.add_argument("--start")
    calendar.add_argument("--end")
    calendar.add_argument("--out", type=_path_argument)

    risk_diagnostic = subparsers.add_parser(
        "risk-diagnostic",
        help="Partial portfolio risk diagnostic with an explicit coverage declaration.",
    )
    risk_diagnostic.add_argument("--weights-file", required=True, type=_path_argument)
    risk_diagnostic.add_argument("--history", action="append", default=[],
                                 help="symbol=path to a yf.py price payload, repeatable")
    risk_diagnostic.add_argument("--out", type=_path_argument)
    dilution = subparsers.add_parser(
        "dilution", help="Signed share-count change (dilution/accretion) for A-share holdings.",
    )
    dilution.add_argument("--symbol", action="append", default=[], help="repeatable")
    dilution.add_argument("--class", action="append", default=[], dest="class_overrides",
                          help="SYMBOL=stock|fund override, repeatable")
    dilution.add_argument("--as-of-date", required=True)
    dilution.add_argument("--lookback-days", type=int)
    dilution.add_argument("--threshold", type=float)
    dilution.add_argument("--out", type=_path_argument)
    return parser


def _write_result_output(
    envelope: dict[str, Any],
    output_path: Path | None,
    *,
    force: bool,
    input_paths: Sequence[Path] = (),
) -> tuple[bool, str | None, str | None]:
    """Persist an active-research stage's ``result`` for the caller.

    Why: the four active-research stages only printed their result, so callers
    hand-redirected stdout (and a syntax slip could write an error message into a
    downstream input).  Writing is refused for a non-complete envelope — an
    incomplete stage must not become a downstream input — and the written bytes are
    re-read and hashed so the receipt matches the file.
    """

    if output_path is None:
        return False, None, None
    for input_path in input_paths:
        if _same_file(output_path, input_path):
            return False, "output_path_conflicts_with_input", None
    if envelope.get("status") != STATUS_COMPLETE or not isinstance(envelope.get("result"), (dict, list)):
        return False, "output_skipped_because_stage_not_complete", None
    rendered = json.dumps(envelope["result"], ensure_ascii=False, indent=2).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not force:
        return False, "output_exists_without_force", None
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output_path)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return True, None, digest


def _run_active_stage(
    *, envelope: dict[str, Any], code: int, output_path: Path | None,
    force: bool, input_paths: Sequence[Path] = (),
) -> tuple[dict[str, Any], int]:
    written, reason, digest = _write_result_output(
        envelope, output_path, force=force, input_paths=input_paths)
    if output_path is not None:
        route = dict(envelope.get("route") or {})
        route["result_written"] = written
        route["result_path"] = str(output_path) if written else None
        route["result_sha256"] = digest
        if reason:
            route["result_skipped_reason"] = reason
        envelope = {**envelope, "route": route}
    return envelope, code


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "daily-run":
        child = [
            "--positions-file", args.positions_file,
            "--task-dir", args.task_dir,
        ]
        for flag, value in (
            ("--cache-dir", args.cache_dir),
            ("--thesis-evidence-file", args.thesis_evidence_file),
            ("--scenario-assumptions", args.scenario_assumptions),
            ("--scenario-portfolio", args.scenario_portfolio),
            ("--dashboard-root", args.dashboard_root),
            ("--holiday-calendar-file", args.holiday_calendar_file),
            ("--coverage-probe-file", args.coverage_probe_file),
            ("--now-epoch", args.now_epoch),
        ):
            _append_option(child, flag, value)
        if args.skip_watchlist:
            child.append("--skip-watchlist")
        for item in args.risk_history:
            child.extend(["--risk-history", item])
        for item in args.risk_fx_history:
            child.extend(["--risk-fx-history", item])
        _append_option(child, "--risk-base-currency", args.risk_base_currency)
        _append_option(child, "--risk-diagnostic-out", args.risk_diagnostic_out)
        if args.plan_only:
            child.append("--plan-only")
        return _run_child(
            public_command=args.command,
            script_name="pia_daily.py",
            child_arguments=child,
            completion_scope="pinned_epoch_daily_sync_pipeline",
            limitations=[
                "the pipeline is read-only: it never modifies the positions input and never trades",
                "dependent stages do not run from an incomplete upstream stage",
            ],
        )

    if args.command == "calendar":
        child = [args.kind]
        for flag, value in (
            ("--cn-html", args.cn_html), ("--us-html", args.us_html),
            ("--cn-locator", args.cn_locator), ("--us-locator", args.us_locator),
            ("--retrieved-at", args.retrieved_at), ("--table", args.table),
            ("--market", args.market), ("--start", args.start), ("--end", args.end),
            ("--out", args.out),
        ):
            _append_option(child, flag, value)
        return _run_child(
            public_command=args.command,
            script_name="market_calendar.py",
            child_arguments=child,
            completion_scope="verified_market_holiday_calendar",
            limitations=[
                "a table is only written when every parser completeness assertion passes",
                "the calendar never widens a quote-age ceiling on its own; callers opt in",
            ],
        )

    if args.command == "risk-diagnostic":
        child = ["--weights-file", args.weights_file]
        for item in args.history:
            child.extend(["--history", item])
        _append_option(child, "--out", args.out)
        return _run_child(
            public_command=args.command,
            script_name="pia_risk_diagnostic.py",
            child_arguments=child,
            completion_scope="partial_portfolio_risk_diagnostic",
            limitations=[
                "the result covers only the supplied histories and is not the portfolio's "
                "risk contribution",
                "excluded symbols are listed with reasons; nothing is back-filled",
            ],
        )

    if args.command == "review-pack":
        child = ["--lane", args.lane, "--run-dir", args.run_dir]
        for flag, value in (("--out", args.out), ("--lanes-file", args.lanes_file)):
            _append_option(child, flag, value)
        return _run_child(
            public_command=args.command,
            script_name="pia_review_pack.py",
            child_arguments=child,
            completion_scope="independent_review_brief",
            limitations=[
                "the brief is a task request, not a permission to review or to act",
                "a lane whose required inputs are missing is not handed a brief",
            ],
        )

    if args.command == "dilution":
        child: list[str] = []
        for symbol in args.symbol:
            child.extend(["--symbol", symbol])
        for item in args.class_overrides:
            child.extend(["--class", item])
        child.extend(["--as-of-date", args.as_of_date])
        if args.lookback_days is not None:
            child.extend(["--lookback-days", str(args.lookback_days)])
        if args.threshold is not None:
            child.extend(["--threshold", str(args.threshold)])
        _append_option(child, "--out", args.out)
        return _run_child(
            public_command=args.command,
            script_name="pia_dilution.py",
            child_arguments=child,
            completion_scope="share_change_assessment",
            limitations=[
                "A-share issuers only; open-ended funds are not_applicable because their share count moves by creation/redemption",
                "an event is selected by announcement date and reported with its effective date, so a replay cannot see a later announcement",
                "a share-count change is context for per-share metrics; it is never a trade instruction",
            ],
        )

    if args.command == "labels":
        child = [args.kind]
        for flag, value in (("--axis", args.axis), ("--file", args.file),
                            ("--previous", args.previous),
                            ("--vocabulary-file", args.vocabulary_file)):
            _append_option(child, flag, value)
        return _run_child(
            public_command=args.command,
            script_name="pia_labels.py",
            child_arguments=child,
            completion_scope="interpretive_label_check",
            limitations=[
                "the checker validates labels against the published vocabulary; it never derives one",
                "a label is research output and never replaces a machine gate status",
            ],
        )

    if args.command == "trigger-ledger":
        child = [args.kind]
        for flag, value in (
            ("--run-dir", args.run_dir), ("--task-root", args.task_root),
            ("--ledger", args.ledger), ("--review-days", args.review_days),
            ("--now", args.now), ("--symbol", args.symbol), ("--limit", args.limit),
            ("--as-of", args.as_of), ("--entry-id", args.entry_id),
            ("--note", args.note), ("--outcome", args.outcome),
        ):
            _append_option(child, flag, value)
        return _run_child(
            public_command=args.command,
            script_name="pia_trigger_ledger.py",
            child_arguments=child,
            completion_scope="run_trigger_ledger",
            limitations=[
                "append-only; duplicate run entries are refused",
                "this ledger is separate from the advice journal and writes no advice record",
            ],
        )

    if args.command == "thesis-ledger":
        child = [args.kind, "--file", args.file]
        for flag, value in (
            ("--symbol", args.symbol), ("--confirmed-at", args.confirmed_at),
            ("--source-locator", args.source_locator),
            ("--conditions-file", args.conditions_file),
            ("--note", args.note), ("--as-of", args.as_of),
        ):
            _append_option(child, flag, value)
        if args.force:
            child.append("--force")
        return _run_child(
            public_command=args.command,
            script_name="pia_thesis_ledger.py",
            child_arguments=child,
            completion_scope="thesis_condition_ledger",
            limitations=[
                "only user-confirmed entries with a confirmation date and source locator are stored",
                "the ledger does not evaluate conditions or declare a thesis safe",
            ],
        )

    if args.command == "report":
        child = ["--run-dir", args.run_dir]
        _append_option(child, "--out", args.out)
        return _run_child(
            public_command=args.command,
            script_name="pia_report.py",
            child_arguments=child,
            completion_scope="run_report_render",
            limitations=[
                "the renderer formats existing artifacts only and adds no judgement",
                "missing artifacts are rendered as gaps, never as empty results",
            ],
        )

    if args.command == "history":
        child = [args.kind, "--task-root", args.task_root]
        _append_option(child, "--depth", args.depth)
        for flag, value in (("--registry", args.registry), ("--output", args.output),
                            ("--from", args.run_from), ("--to", args.run_to)):
            _append_option(child, flag, value)
        for flag in ("--write", "--summary"):
            if getattr(args, flag.strip("-").replace("-", "_")):
                child.append(flag)
        return _run_child(
            public_command=args.command,
            script_name="pia_history.py",
            child_arguments=child,
            completion_scope="cross_run_registry_and_delta",
            limitations=[
                "the index is read-only unless --write is given; the diff never writes",
                "missing artifacts are reported as gaps, never as 'no change'",
            ],
        )

    if args.command == "etf-packet":
        child = ["--evidence-file", args.evidence_file, "--task-dir", args.task_dir]
        for flag, value in (
            ("--symbol", args.symbol),
            ("--as-of-date", args.as_of_date),
            ("--provider-source", args.provider_source),
            ("--provider-source-locator", args.provider_source_locator),
            ("--provider-adjustment", args.provider_adjustment),
        ):
            _append_option(child, flag, value)
        if args.allow_unverified:
            child.append("--allow-unverified")
        if args.force:
            child.append("--force")
        return _run_child(
            public_command=args.command,
            script_name="pia_etf_packet.py",
            child_arguments=child,
            completion_scope="etf_history_integrity_packet",
            limitations=[
                "official corporate actions must be supplied with evidence; the tool never invents one",
                "packet verification does not by itself authorize technical metrics; yf.py binds the series",
            ],
        )

    if args.command == "build":
        child = [args.kind, "--task-dir", args.task_dir]
        for flag, value in (
            ("--weights-file", args.weights_file),
            ("--confirmed-policy", args.confirmed_policy),
            ("--positions-file", args.positions_file),
            ("--volatilities-file", args.volatilities_file),
            ("--quotes-file", args.quotes_file),
            ("--evidence-file", args.evidence_file),
            ("--assessments-file", args.assessments_file),
            ("--scope-coverage-file", args.scope_coverage_file),
            ("--window-start", args.window_start),
            ("--window-end", args.window_end),
        ):
            _append_option(child, flag, value)
        for artifact in args.artifact:
            child.extend(["--artifact", artifact])
        if args.force:
            child.append("--force")
        return _run_child(
            public_command=args.command,
            script_name="pia_build.py",
            child_arguments=child,
            completion_scope="active_research_input_build",
            limitations=[
                "builders derive inputs from upstream artifacts and never invent a value",
                "built inputs remain non-executable research artifacts",
            ],
        )

    if args.command == "refresh":
        derived = Path(args.task_dir) / "inputs" / "positions_fx_snapshot.json"
        if _same_file(derived, Path(args.positions_file)):
            return _path_conflict_failure(
                command=args.command,
                completion_scope="isolated_fx_snapshot_refresh",
                message="--task-dir must not resolve the derived snapshot onto the positions input",
            )
        child = [
            "--positions-file", args.positions_file,
            "--task-dir", args.task_dir,
        ]
        for flag, value in (
            ("--cache-dir", args.cache_dir),
            ("--fx-observation-file", args.fx_observation_file),
            ("--max-fx-age-hours", args.max_fx_age_hours),
        ):
            _append_option(child, flag, value)
        for pair in args.fx_pair:
            child.extend(["--fx-pair", pair])
        if args.force:
            child.append("--force")
        return _run_child(
            public_command=args.command,
            script_name="pia_refresh.py",
            child_arguments=child,
            completion_scope="isolated_fx_snapshot_refresh",
            limitations=[
                "this step refreshes FX and writes a derived snapshot only",
                "quote acquisition remains yf.py --daily-sync and the positions input is never modified",
            ],
        )

    if args.command == "research":
        return _run_child(
            public_command=args.command,
            script_name="research_brief_gate.py",
            child_arguments=[args.brief_json],
            completion_scope="research_brief_validation",
            limitations=["company research execution is not part of this thin route"],
        )

    if args.command == "screen":
        child = ["--tickers", *args.tickers, "--profile", args.profile, "--format", "json"]
        for flag, value in (
            ("--market", args.market),
            ("--asset-type", args.asset_type),
            ("--as-of-date", args.as_of_date),
            ("--industry-type", args.industry_type),
            ("--profiles-file", args.profiles_file),
        ):
            _append_option(child, flag, value)
        return _run_child(
            public_command=args.command,
            script_name="quality_screener.py",
            child_arguments=child,
            completion_scope="financial_quality_prescreen",
            limitations=["screen output is descriptive and is not validated alpha"],
        )

    if args.command == "edgar-fundamentals":
        child = [*args.symbols, "--as-of", args.as_of]
        _append_option(child, "--user-agent", args.user_agent)
        _append_option(child, "--timeout", args.timeout)
        _append_option(child, "--decision-scope", args.decision_scope)
        return _run_child(
            public_command=args.command,
            script_name="sec_edgar_fundamentals.py",
            child_arguments=child,
            completion_scope="free_sec_point_in_time_fundamentals",
            limitations=[
                "SEC filings do not establish historical index membership or delisting returns"
            ],
        )

    if args.command == "portfolio-audit":
        child = [args.symbol, "--positions-file", args.positions_file]
        _append_option(child, "--current-price", args.current_price)
        return _run_child(
            public_command=args.command,
            script_name="portfolio_loader.py",
            child_arguments=child,
            completion_scope="portfolio_position_context",
            limitations=[
                "the routed script loads portfolio and position context only",
                "quality screening and thesis red-team review are not connected here",
            ],
        )

    if args.command == "daily-sync":
        child = [
            "--positions-file",
            args.positions_file,
            "--quotes-file",
            args.quotes_file,
        ]
        _append_option(child, "--now-epoch", args.now_epoch)
        _append_option(child, "--max-quote-age-seconds", args.max_quote_age_seconds)
        _append_option(child, "--thesis-evidence-file", args.thesis_evidence_file)
        _append_option(child, "--holiday-calendar-file", args.holiday_calendar_file)
        _append_option(child, "--decision-scope", args.decision_scope)
        return _run_child(
            public_command=args.command,
            script_name="daily_sync.py",
            child_arguments=child,
            completion_scope="offline_daily_sync_contract_audit",
            limitations=[
                "thesis completion requires a supplied evidence package that passes the primary-source gate"
            ],
        )

    if args.command == "scenario":
        output_path = Path(args.output) if args.output else None
        if output_path is not None and any(
            _same_file(output_path, Path(input_path))
            for input_path in (args.portfolio_json, args.assumptions_json)
        ):
            return _path_conflict_failure(
                command=args.command,
                completion_scope="explicit_input_scenario_analysis",
                message="--output must not resolve to a portfolio or assumptions input",
            )
        child = [args.portfolio_json, args.assumptions_json]
        _append_option(child, "--output", args.output)
        return _run_child(
            public_command=args.command,
            script_name="portfolio_scenario_analyzer.py",
            child_arguments=child,
            completion_scope="explicit_input_scenario_analysis",
            limitations=["the router does not source market, FX, or risk inputs"],
            output_mode="json_file" if args.output else "json",
            required_output=output_path,
        )

    if args.command == "calibrate":
        output_path = Path(args.output_path)
        journal_value = args.journal_path
        if journal_value and _same_file(output_path, Path(journal_value)):
            return _path_conflict_failure(
                command=args.command,
                completion_scope="calibration_report_write",
                message="--output-path must not resolve to the advice journal input",
            )
        child: list[str] = []
        _append_option(child, "--journal-path", args.journal_path)
        _append_option(child, "--output-path", args.output_path)
        return _run_child(
            public_command=args.command,
            script_name="decision_outcome_report.py",
            child_arguments=child,
            completion_scope="calibration_report_write",
            output_mode="text",
            required_output=output_path,
            limitations=["report completion does not establish calibration quality"],
        )

    if args.command == "alpha-validate":
        envelope, code = _run_child(
            public_command=args.command,
            script_name="alpha_validation.py",
            child_arguments=[args.alpha_package, "--policy-file", args.policy_file],
            completion_scope="point_in_time_alpha_validation",
            limitations=[
                "eligibility permits active research only; it does not authorize capital deployment"
            ],
        )
        return _run_active_stage(
            envelope=envelope, code=code,
            output_path=Path(args.output) if args.output else None, force=args.force,
            input_paths=[Path(args.alpha_package), Path(args.policy_file)],
        )

    if args.command == "alpha-scan":
        envelope, code = _run_child(
            public_command=args.command,
            script_name="active_alpha_scan.py",
            child_arguments=[
                args.alpha_package,
                "--validation-report",
                args.validation_report,
                "--policy-file",
                args.policy_file,
            ],
            completion_scope="validated_alpha_rank_yank_scan",
            limitations=["Rank/Yank pools are research attention lists, not trade lists"],
        )
        return _run_active_stage(
            envelope=envelope, code=code,
            output_path=Path(args.output) if args.output else None, force=args.force,
            input_paths=[Path(args.alpha_package), Path(args.validation_report),
                         Path(args.policy_file)],
        )

    if args.command == "portfolio-construct":
        envelope, code = _run_child(
            public_command=args.command,
            script_name="active_portfolio_constructor.py",
            child_arguments=[args.scan_report, "--policy-file", args.policy_file],
            completion_scope="read_only_active_portfolio_construction",
            limitations=["candidate weights are non-executable and are not target weights"],
        )
        return _run_active_stage(
            envelope=envelope, code=code,
            output_path=Path(args.output) if args.output else None, force=args.force,
            input_paths=[Path(args.scan_report), Path(args.policy_file)],
        )

    if args.command == "rebalance-proposal":
        envelope, code = _run_child(
            public_command=args.command,
            script_name="rebalance_proposal.py",
            child_arguments=[args.construction_report, "--policy-file", args.policy_file],
            completion_scope="non_executable_rebalance_research_proposal",
            limitations=["allocation gaps cannot authorize or route an order"],
        )
        return _run_active_stage(
            envelope=envelope, code=code,
            output_path=Path(args.output) if args.output else None, force=args.force,
            input_paths=[Path(args.construction_report), Path(args.policy_file)],
        )

    if args.command == "validate":
        routes = {
            "research-brief": ("research_brief_gate.py", []),
            "dashboard": ("dashboard_gate.py", ["--strict-current-contract"]),
            "dashboard-math": ("dashboard_math_gate.py", []),
            "history": ("history_integrity_gate.py", []),
        }
        script_name, extra = routes[args.kind]
        return _run_child(
            public_command=args.command,
            script_name=script_name,
            child_arguments=[args.json_path, *extra],
            completion_scope=f"{args.kind}_contract_validation",
        )

    return (
        make_envelope(
            command=str(args.command),
            status=STATUS_FAILED,
            detail_status="unknown_command",
            errors=["command dispatch is not implemented"],
        ),
        exit_code_for(STATUS_FAILED),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        envelope, exit_code = _dispatch(args)
    except Exception as exc:  # Final public fail-closed boundary.
        envelope = make_envelope(
            command=str(getattr(args, "command", "cli")),
            status=STATUS_FAILED,
            detail_status="router_exception",
            errors=[str(exc)],
        )
        exit_code = exit_code_for(STATUS_FAILED)
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
