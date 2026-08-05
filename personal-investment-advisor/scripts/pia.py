"""Stable, injection-safe command router for Personal Investment Advisor.

This entrypoint is deliberately thin.  It invokes existing business scripts
with fixed executable paths and explicit argument lists, then wraps their
native output in ``status_contract.py``.  It never uses a command shell.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

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


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit the same machine-readable failure contract for CLI usage errors."""

    def error(self, message: str) -> None:
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


def _resolved_path(value: str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


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

    if not isinstance(payload, list) or not payload:
        return STATUS_FAILED
    native = [
        item.get("status") if isinstance(item, dict) else None for item in payload
    ]
    if any(status in {"data_error", "invalid", "invalid_input"} for status in native):
        return STATUS_FAILED
    if any(
        status in {"insufficient_data", "insufficient_evidence", "not_applicable"}
        for status in native
    ):
        return STATUS_INSUFFICIENT_EVIDENCE
    if all(status in {"pass", "fail"} for status in native):
        return STATUS_COMPLETE if child_exit_code == 0 else STATUS_FAILED
    return STATUS_FAILED


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
        completed = subprocess.run(
            invocation,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=CHILD_TIMEOUT_SECONDS,
        )
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
            envelope = make_envelope(
                command=public_command,
                status=STATUS_FAILED,
                detail_status="json_output_file_not_verified",
                errors=[diagnostics or "child did not publish a new JSON output file"],
                limitations=limitations,
                route=route,
                completion_scope=completion_scope,
            )
            return envelope, exit_code_for(envelope["status"])
        try:
            rendered_output = required_output.read_text(encoding="utf-8")
        except OSError as exc:
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
    research.add_argument("brief_json")

    screen = subparsers.add_parser(
        "screen", help="Run the profile-driven financial quality pre-screen."
    )
    screen.add_argument("--tickers", nargs="+", required=True)
    screen.add_argument("--profile", required=True)
    screen.add_argument("--market")
    screen.add_argument("--asset-type")
    screen.add_argument("--as-of-date")
    screen.add_argument("--industry-type")
    screen.add_argument("--profiles-file")

    portfolio = subparsers.add_parser(
        "portfolio-audit",
        help="Load validated portfolio and position context; full audit remains external.",
    )
    portfolio.add_argument("symbol")
    portfolio.add_argument("--positions-file", required=True)
    portfolio.add_argument("--current-price", type=float)

    daily = subparsers.add_parser(
        "daily-sync", help="Audit a supplied portfolio and quote package offline."
    )
    daily.add_argument("--positions-file", required=True)
    daily.add_argument("--quotes-file", required=True)
    daily.add_argument("--now-epoch", type=float)
    daily.add_argument("--max-quote-age-seconds", type=int)

    scenario = subparsers.add_parser(
        "scenario", help="Run the explicit-input portfolio scenario analyzer."
    )
    scenario.add_argument("portfolio_json")
    scenario.add_argument("assumptions_json")
    scenario.add_argument("--output")

    calibrate = subparsers.add_parser(
        "calibrate", help="Write the benchmark-aware decision outcome report."
    )
    calibrate.add_argument("--journal-path")
    calibrate.add_argument("--output-path", required=True)

    validate = subparsers.add_parser(
        "validate", help="Run a selected current contract gate."
    )
    validate.add_argument(
        "kind",
        choices=("research-brief", "dashboard", "dashboard-math", "history"),
    )
    validate.add_argument("json_path")
    return parser


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
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
        return _run_child(
            public_command=args.command,
            script_name="daily_sync.py",
            child_arguments=child,
            completion_scope="offline_daily_sync_contract_audit",
            limitations=["news and thesis red-team review require a separate evidence workflow"],
        )

    if args.command == "scenario":
        output_path = _resolved_path(args.output) if args.output else None
        if output_path is not None and any(
            _same_file(output_path, _resolved_path(input_path))
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
        output_path = _resolved_path(args.output_path)
        journal_value = args.journal_path or os.environ.get("PIA_ADVICE_JOURNAL")
        if journal_value and _same_file(output_path, _resolved_path(journal_value)):
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
