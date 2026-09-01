#!/usr/bin/env python3
"""Verify and invoke one previously enabled Garmin freshness task instance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import runtime_authority


COMPONENTS = ("sleep", "hrv", "body_battery", "heart_rate", "stress")
TERMINAL_STATUSES = {"success", "failed"}


def _norm(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value))).replace("\\", "/")


def expected_task_arguments_sha256(args: argparse.Namespace) -> str:
    required = (
        "runner",
        "task_config_dir",
        "task_garmindb_python",
        "task_scratch_dir",
        "state_output",
        "authority_config",
    )
    values = {}
    for name in required:
        raw = getattr(args, name, None)
        if not isinstance(raw, str) or not raw.strip() or '"' in raw:
            raise ValueError(f"{name}_invalid")
        values[name] = str(Path(raw).resolve())
    if not 1 <= args.task_days <= 31:
        raise ValueError("task_days_invalid")
    if args.task_timeout_seconds <= 0 or args.task_total_timeout_seconds <= 0:
        raise ValueError("task_timeout_invalid")
    task_arguments = " ".join(
        (
            "-B",
            f'"{values["runner"]}"',
            "--days",
            str(args.task_days),
            "--config-dir",
            f'"{values["task_config_dir"]}"',
            "--garmindb-python",
            f'"{values["task_garmindb_python"]}"',
            "--scratch-dir",
            f'"{values["task_scratch_dir"]}"',
            "--state-output",
            f'"{values["state_output"]}"',
            "--authority-config",
            f'"{values["authority_config"]}"',
            "--timeout-seconds",
            str(args.task_timeout_seconds),
            "--total-timeout-seconds",
            str(args.task_total_timeout_seconds),
            "--allow-network",
            "--allow-sync",
            "--allow-health-data",
        )
    )
    return hashlib.sha256(task_arguments.encode("utf-8")).hexdigest()


def _parse_json(text: str) -> dict:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("probe_payload_invalid")
    return payload


def _powershell_probe(script: Path, task_name: str, mode: str) -> dict:
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-File", str(script), "-Mode", mode, "-TaskName", task_name],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    payload = _parse_json(completed.stdout.strip())
    if completed.returncode != 0 and payload.get("ok") is not False:
        raise RuntimeError("task_probe_failed")
    return payload


def _read_state(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("task_state_invalid") from exc
    return payload if isinstance(payload, dict) else None


def validate_task(snapshot: dict, expected: dict) -> str | None:
    if not snapshot.get("ok"):
        return str(snapshot.get("error_code") or "task_probe_failed")
    if snapshot.get("exists") is False and snapshot.get("reason") == "task_missing":
        return "task_missing"
    if snapshot.get("exists") is not True:
        return "task_probe_invalid"
    checks = (
        (snapshot.get("task_name") == expected["task_name"], "task_name_drift"),
        (snapshot.get("task_path") == "\\", "task_path_drift"),
        (snapshot.get("enabled") is True, "task_disabled"),
        (bool(snapshot.get("current_sid")) and snapshot.get("task_user_sid") == snapshot.get("current_sid"), "task_user_drift"),
        (snapshot.get("run_level") == "Limited", "task_run_level_drift"),
        (snapshot.get("logon_type") == "Interactive", "task_logon_type_drift"),
        (snapshot.get("multiple_instances") == "IgnoreNew", "task_singleton_drift"),
        (snapshot.get("start_when_available") is True, "task_start_policy_drift"),
        (snapshot.get("action_count") == 1, "task_action_count_drift"),
        (_norm(str(snapshot.get("execute", ""))) == _norm(expected["python"]), "task_python_drift"),
        (_norm(str(snapshot.get("working_directory", ""))) == _norm(expected["working_directory"]), "task_workdir_drift"),
    )
    for passed, reason in checks:
        if not passed:
            return reason
    if snapshot.get("arguments_sha256") != expected["arguments_sha256"]:
        return "task_arguments_drift"
    if snapshot.get("state") not in {"Ready", "Running"}:
        return "task_state_ineligible"
    return None


def validate_terminal_state(
    state: dict | None,
    end: str,
    authority: dict,
    expected_run_id: str | None,
    expected_start: str | None = None,
) -> str | None:
    if not state:
        return "terminal_state_missing"
    if state.get("status") not in TERMINAL_STATUSES:
        return "terminal_state_not_terminal"
    if expected_run_id and state.get("run_id") != expected_run_id:
        return "terminal_run_id_mismatch"
    if state.get("status") != "success":
        return str(state.get("error_code") or "sync_failed")
    if state.get("health_values_persisted") is not False:
        return "terminal_health_values_persisted_invalid"
    if (state.get("requested_window") or {}).get("end") != end:
        return "terminal_window_mismatch"
    if expected_start is not None and (state.get("requested_window") or {}).get("start") != expected_start:
        return "terminal_window_mismatch"
    binding = state.get("runtime_binding") or {}
    if binding.get("authority_version") != authority.get("authority_version") or binding.get("authority_sha256") != authority.get("authority_sha256"):
        return "terminal_runtime_binding_mismatch"
    if state.get("database_fingerprint_changed") is not True:
        return "terminal_database_unchanged"
    dates = state.get("component_latest_observation_dates") or {}
    for component in COMPONENTS:
        observation = dates.get(component)
        if not isinstance(observation, str):
            return "terminal_date_invalid"
        try:
            parsed = date.fromisoformat(observation)
        except ValueError:
            return "terminal_date_invalid"
        if parsed.isoformat() != end:
            return "terminal_coverage_stale"
    return None


def run_gate(
    args: argparse.Namespace,
    *,
    probe: Callable[[str], dict],
    state_reader: Callable[[], dict | None],
    sleeper: Callable[[float], None] = time.sleep,
    direct_runner: Callable[[], int] | None = None,
    today: date | None = None,
) -> tuple[int, dict]:
    audit = {
        "schema": "garmin-freshness-acquisition.v1",
        "sync_eligible": False,
        "sync_attempted": "not_attempted",
        "task_status": "not_checked",
        "local_reread": "not_run",
        "local_status": "not_run",
        "live_fallback": "not_used",
        "reason": "not_evaluated",
    }
    if not (args.allow_network and args.allow_sync and args.allow_health_data):
        audit["reason"] = "capability_denied"
        return 2, audit
    requested_end = getattr(args, "end", None)
    if not isinstance(requested_end, str):
        audit["reason"] = "requested_end_invalid"
        return 2, audit
    try:
        date.fromisoformat(requested_end)
    except ValueError:
        audit["reason"] = "requested_end_invalid"
        return 2, audit
    if requested_end != (today or date.today()).isoformat():
        audit["reason"] = "requested_end_not_current"
        return 2, audit
    if not 1 <= args.max_polls <= 240 or not 0.1 <= args.poll_seconds <= 10:
        audit["reason"] = "poll_budget_invalid"
        return 2, audit
    authority = runtime_authority.verify(json.loads(Path(args.authority_config).read_text(encoding="utf-8")))
    if not authority.get("ok"):
        audit.update({"task_status": "invalid", "reason": "runtime_authority_mismatch"})
        return 2, audit
    try:
        task_arguments_sha256 = expected_task_arguments_sha256(args)
    except (OSError, RuntimeError, ValueError) as exc:
        audit.update({"task_status": "invalid", "reason": f"task_binding_config_invalid:{exc}"})
        return 2, audit
    expected = {
        "task_name": args.task_name,
        "python": args.python,
        "runner": args.runner,
        "authority_config": args.authority_config,
        "state_output": args.state_output,
        "working_directory": str(Path(args.runner).resolve().parent),
        "arguments_sha256": task_arguments_sha256,
    }
    snapshot = probe("Inspect")
    task_error = validate_task(snapshot, expected)
    if task_error == "task_missing" and args.allow_direct_sync:
        confirmation = probe("Inspect")
        confirmation_error = validate_task(confirmation, expected)
        if confirmation_error is None:
            snapshot = confirmation
            task_error = None
        elif confirmation_error != "task_missing":
            audit.update({"task_status": "invalid", "reason": confirmation_error})
            return 1, audit
    if task_error:
        if task_error == "task_missing" and args.allow_direct_sync:
            if direct_runner is None:
                audit.update({"task_status": "invalid", "reason": "direct_sync_config_missing"})
                return 2, audit
            bound_runner = (authority.get("entrypoints") or {}).get("scripts/garmin_auto_sync.py")
            if not bound_runner or _norm(args.runner) != _norm(bound_runner):
                audit.update({"task_status": "invalid", "reason": "direct_sync_runner_drift"})
                return 2, audit
            audit.update({"sync_eligible": True, "sync_attempted": "direct"})
            baseline = state_reader()
            baseline_run_id = baseline.get("run_id") if isinstance(baseline, dict) else None
            direct_code = direct_runner()
            current_state = state_reader()
            expected_run_id = (
                current_state.get("run_id")
                if isinstance(current_state, dict) and current_state.get("run_id") != baseline_run_id
                else None
            )
            error = (
                "direct_terminal_run_id_missing"
                if expected_run_id is None
                else validate_terminal_state(
                    current_state,
                    requested_end,
                    authority,
                    expected_run_id,
                    (date.fromisoformat(requested_end) - timedelta(days=args.direct_days - 1)).isoformat(),
                )
            )
            if direct_code != 0 or error:
                audit.update(
                    {
                        "task_status": str((current_state or {}).get("status") or "failed"),
                        "reason": error or "direct_sync_failed",
                    }
                )
                return 1, audit
            audit.update({"task_status": "success", "reason": "sync_verified_local_reread_required"})
            return 0, audit
        audit.update({"task_status": "invalid", "reason": task_error})
        return 1, audit
    audit["sync_eligible"] = True
    baseline = state_reader()
    baseline_run_id = baseline.get("run_id") if isinstance(baseline, dict) else None
    if snapshot.get("state") == "Running":
        audit["sync_attempted"] = "waited_existing"
        expected_run_id = baseline_run_id if isinstance(baseline, dict) and baseline.get("status") == "running" else None
    else:
        start_result = probe("Start")
        if not start_result.get("ok"):
            audit.update({"task_status": "start_failed", "reason": "task_start_failed"})
            return 1, audit
        audit["sync_attempted"] = "started"
        expected_run_id = None

    for _ in range(args.max_polls):
        sleeper(args.poll_seconds)
        current_task = probe("Inspect")
        current_state = state_reader()
        if expected_run_id is None and isinstance(current_state, dict):
            candidate_run_id = current_state.get("run_id")
            if candidate_run_id and candidate_run_id != baseline_run_id:
                expected_run_id = candidate_run_id
        if current_task.get("state") != "Running" and isinstance(current_state, dict) and current_state.get("status") == "running":
            audit.update({"task_status": "interrupted_or_terminated", "reason": "interrupted_or_terminated"})
            return 1, audit
        if (
            expected_run_id is None
            and isinstance(current_state, dict)
            and current_state.get("status") in TERMINAL_STATUSES
        ):
            continue
        if isinstance(current_state, dict) and current_state.get("status") in TERMINAL_STATUSES:
            error = validate_terminal_state(current_state, requested_end, authority, expected_run_id)
            if error:
                audit.update({"task_status": str(current_state.get("status")), "reason": error})
                return 1, audit
            audit.update({"task_status": "success", "reason": "sync_verified_local_reread_required"})
            return 0, audit
    audit.update({"task_status": "timeout", "reason": "task_wait_timeout"})
    return 1, audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-name", default="Codex-Garmin-Health-Sync")
    parser.add_argument("--python", required=True)
    parser.add_argument("--runner", required=True)
    parser.add_argument("--authority-config", required=True)
    parser.add_argument("--state-output", required=True)
    parser.add_argument("--task-config-dir", required=True)
    parser.add_argument("--task-garmindb-python", required=True)
    parser.add_argument("--task-scratch-dir", required=True)
    parser.add_argument("--task-days", type=int, default=7)
    parser.add_argument("--task-timeout-seconds", type=int, default=480)
    parser.add_argument("--task-total-timeout-seconds", type=int, default=900)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-polls", type=int, default=204)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-sync", action="store_true")
    parser.add_argument("--allow-health-data", action="store_true")
    parser.add_argument("--allow-direct-sync", action="store_true")
    parser.add_argument("--direct-config-dir")
    parser.add_argument("--direct-garmindb-python")
    parser.add_argument("--direct-scratch-dir")
    parser.add_argument("--direct-days", type=int, default=7)
    parser.add_argument("--direct-timeout-seconds", type=int, default=480)
    parser.add_argument("--direct-total-timeout-seconds", type=int, default=900)
    return parser


def _run_direct_sync(args: argparse.Namespace) -> int:
    required = (args.direct_config_dir, args.direct_garmindb_python, args.direct_scratch_dir)
    if not all(required):
        raise RuntimeError("direct_sync_config_missing")
    paths = (
        args.python,
        args.runner,
        args.authority_config,
        args.state_output,
        args.direct_config_dir,
        args.direct_garmindb_python,
        args.direct_scratch_dir,
    )
    if any(not Path(item).is_absolute() for item in paths):
        raise RuntimeError("direct_sync_path_not_absolute")
    if _norm(args.python) != _norm(sys.executable):
        raise RuntimeError("direct_sync_python_drift")
    if not 1 <= args.direct_days <= 31:
        raise RuntimeError("direct_sync_days_invalid")
    if args.direct_timeout_seconds <= 0 or not 1 <= args.direct_total_timeout_seconds <= 900:
        raise RuntimeError("direct_sync_timeout_invalid")
    command = [
        args.python,
        "-B",
        args.runner,
        "--days",
        str(args.direct_days),
        "--config-dir",
        args.direct_config_dir,
        "--garmindb-python",
        args.direct_garmindb_python,
        "--scratch-dir",
        args.direct_scratch_dir,
        "--state-output",
        args.state_output,
        "--authority-config",
        args.authority_config,
        "--timeout-seconds",
        str(args.direct_timeout_seconds),
        "--total-timeout-seconds",
        str(args.direct_total_timeout_seconds),
        "--allow-network",
        "--allow-sync",
        "--allow-health-data",
    ]
    clean_env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "PIP_CONFIG_FILE"):
        clean_env.pop(name, None)
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=clean_env,
        timeout=args.direct_total_timeout_seconds + 30,
    )
    return completed.returncode


def main() -> int:
    args = build_parser().parse_args()
    probe_script = Path(__file__).with_name("scheduled_task_probe.ps1")
    probe = lambda mode: _powershell_probe(probe_script, args.task_name, mode)
    try:
        direct_runner = (lambda: _run_direct_sync(args)) if args.allow_direct_sync else None
        code, audit = run_gate(
            args,
            probe=probe,
            state_reader=lambda: _read_state(Path(args.state_output)),
            direct_runner=direct_runner,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        code, audit = 1, {
            "schema": "garmin-freshness-acquisition.v1",
            "sync_eligible": False,
            "sync_attempted": "not_attempted",
            "task_status": "invalid",
            "local_reread": "not_run",
            "local_status": "not_run",
            "live_fallback": "not_used",
            "reason": "task_probe_failed",
        }
    print(json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
