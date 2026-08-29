#!/usr/bin/env python3
"""Run a bounded, user-authorized GarminDB sync for a scheduled task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import runtime_authority
from garmin_sqlite_adapter import GARMIN_DB, MONITORING_DB, fingerprint_database


SCHEMA = "garmin-auto-sync-status.v1"
COMPONENTS = ("sleep", "hrv", "body_battery", "heart_rate", "stress")
PLAN_TIMEOUT_SECONDS = 150
TOTAL_TIMEOUT_SECONDS = 900
SAFE_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,80}$")


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parse_json_output(text: str) -> dict:
    decoder = json.JSONDecoder()
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, end = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if not text[offset + end :].strip() and isinstance(payload, dict):
            return payload
    raise ValueError("command did not return one terminal JSON object")


def _run_json(command: list[str], timeout: int) -> dict:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command_exit_{completed.returncode}")
    return _parse_json_output(completed.stdout)


def _run_bounded(
    runner: Callable[[list[str], int], dict],
    command: list[str],
    requested_timeout: int,
    deadline: float,
) -> dict:
    remaining = int(deadline - time.monotonic())
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, 0)
    return runner(command, min(requested_timeout, remaining))


def _verify_authority(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return runtime_authority.verify(config)


def _database_fingerprint() -> str:
    evidence = []
    for database in (GARMIN_DB, MONITORING_DB):
        item = fingerprint_database(database)
        evidence.append(
            {
                "database": item["database"],
                "schema_sha256": item["schema_sha256"],
                "storage_sha256": item["storage_sha256"],
            }
        )
    canonical = json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_error_code(stage: str, exc: BaseException) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"{stage}_timeout"
    message = str(exc)
    if isinstance(exc, (RuntimeError, ValueError)) and SAFE_ERROR_CODE.fullmatch(message):
        return message
    return f"{stage}_{type(exc).__name__.lower()}"


@contextmanager
def _singleton(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BlockingIOError("auto sync is already running") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BlockingIOError("auto sync is already running") from exc
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def compute_window(end_date: date, days: int) -> tuple[str, str]:
    if not 1 <= days <= 31:
        raise ValueError("days must be between 1 and 31")
    start_date = end_date - timedelta(days=days - 1)
    return start_date.isoformat(), end_date.isoformat()


def _coverage_summary(insight: dict) -> dict:
    observations = insight.get("observations") or {}

    def field(name: str) -> dict:
        value = observations.get(name)
        return value if isinstance(value, dict) else {}

    battery = field("body_battery")
    battery_high = battery.get("highest") if isinstance(battery.get("highest"), dict) else {}
    sources = {
        "sleep": field("sleep"),
        "hrv": field("hrv"),
        "body_battery": battery_high,
        "heart_rate": field("resting_heart_rate"),
        "stress": field("stress_average"),
    }
    counts = {name: int(source.get("observation_count") or 0) for name, source in sources.items()}
    component_dates = {name: source.get("date") for name, source in sources.items()}
    dates = [value for value in component_dates.values() if value]
    return {
        "data_status": insight.get("data_status") or insight.get("status"),
        "component_observation_counts": counts,
        "component_latest_observation_dates": component_dates,
        "latest_observation_date": max(dates) if dates else None,
    }


def _stale_components(component_dates: dict, end: str) -> list[str]:
    expected = date.fromisoformat(end)
    stale = []
    for name in COMPONENTS:
        observation = component_dates.get(name)
        try:
            observed = date.fromisoformat(observation)
        except (TypeError, ValueError):
            stale.append(name)
            continue
        if observed != expected:
            stale.append(name)
    return stale


def _base_state(start: str, end: str, started_at: str) -> dict:
    return {
        "schema": SCHEMA,
        "run_id": uuid.uuid4().hex,
        "status": "running",
        "stage": "initialization",
        "started_at": started_at,
        "updated_at": started_at,
        "requested_window": {"start": start, "end": end},
        "components": list(COMPONENTS),
        "health_values_persisted": False,
    }


def run_scheduled_sync(
    args: argparse.Namespace,
    *,
    runner: Callable[[list[str], int], dict] = _run_json,
    authority_verifier: Callable[[Path], dict] = _verify_authority,
    database_fingerprinter: Callable[[], str] = _database_fingerprint,
    today: date | None = None,
) -> tuple[int, dict]:
    if not (args.allow_network and args.allow_sync and args.allow_health_data):
        return 2, {"schema": SCHEMA, "status": "capability_denied"}
    if not 1 <= args.timeout_seconds <= 600 or not 60 <= args.total_timeout_seconds <= TOTAL_TIMEOUT_SECONDS:
        return 2, {"schema": SCHEMA, "status": "invalid_timeout_budget"}

    python = Path(sys.executable).resolve()
    garmindb_python = Path(args.garmindb_python).resolve()
    config_dir = Path(args.config_dir).resolve()
    scratch_dir = Path(args.scratch_dir).resolve()
    state_output = Path(args.state_output).resolve()
    authority_config = Path(args.authority_config).resolve()
    for required in (python, garmindb_python, config_dir, authority_config):
        if not required.exists():
            return 2, {"schema": SCHEMA, "status": "invalid_runtime_path"}
    if not all(path.is_absolute() for path in (scratch_dir, state_output)):
        return 2, {"schema": SCHEMA, "status": "invalid_output_path"}

    scratch_dir.mkdir(parents=True, exist_ok=True)
    end_date = today or date.today()
    start, end = compute_window(end_date, args.days)
    started_at = datetime.now(timezone.utc).isoformat()
    state = _base_state(start, end, started_at)
    deadline = time.monotonic() + min(args.total_timeout_seconds, TOTAL_TIMEOUT_SECONDS)
    script_dir = Path(__file__).resolve().parent
    sync_script = script_dir / "sync_health_data.py"
    preflight_script = script_dir / "runtime_preflight.py"
    insight_script = script_dir / "garmin_intelligence.py"
    plan_path = scratch_dir / f"sync-plan-{os.getpid()}-{end_date.isoformat()}.json"

    stage = "initialization"
    try:
        with _singleton(scratch_dir / "garmin-auto-sync.lock"):
            authority_result = authority_verifier(authority_config)
            if not authority_result.get("ok"):
                raise RuntimeError("runtime_authority_mismatch")
            state["runtime_binding"] = {
                "authority_version": authority_result.get("authority_version"),
                "authority_sha256": authority_result.get("authority_sha256"),
            }
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(state_output, state)

            stage = "database_fingerprint_before"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            before_fingerprint = database_fingerprinter()

            stage = "live_preflight"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            live_preflight = _run_bounded(runner, [str(python), "-B", str(preflight_script), "--mode", "live"], 60, deadline)
            if not live_preflight.get("ok"):
                raise RuntimeError("live_preflight_failed")

            stage = "plan"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            dry_run = _run_bounded(
                runner,
                [
                    str(python), "-B", str(sync_script), "sync",
                    "--start", start, "--end", end, "--dry-run",
                    "--config-dir", str(config_dir),
                    "--garmindb-python", str(garmindb_python),
                    "--plan-output", str(plan_path),
                    "--plan-ttl-seconds", "900",
                ],
                PLAN_TIMEOUT_SECONDS,
                deadline,
            )
            if dry_run.get("status") != "dry_run" or not plan_path.exists():
                raise RuntimeError("sync_plan_failed")

            stage = "sync_execution"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            sync_result = _run_bounded(
                runner,
                [
                    str(python), "-B", str(sync_script), "sync",
                    "--start", start, "--end", end,
                    "--allow-network", "--allow-sync",
                    "--config-dir", str(config_dir),
                    "--garmindb-python", str(garmindb_python),
                    "--plan-file", str(plan_path),
                    "--timeout-seconds", str(args.timeout_seconds),
                ],
                args.timeout_seconds + 30,
                deadline,
            )
            if sync_result.get("status") != "sync_completed":
                raise RuntimeError("sync_execution_failed")

            stage = "database_fingerprint_after"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            after_fingerprint = database_fingerprinter()
            state["database_fingerprint_changed"] = before_fingerprint != after_fingerprint
            if not state["database_fingerprint_changed"]:
                raise RuntimeError("database_fingerprint_unchanged")

            stage = "local_preflight"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            local_preflight = _run_bounded(runner, [str(python), "-B", str(preflight_script), "--mode", "local"], 60, deadline)
            if not local_preflight.get("ok"):
                raise RuntimeError("local_preflight_failed")
            stage = "local_coverage"
            state.update({"stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()})
            _atomic_json(state_output, state)
            insight = _run_bounded(
                runner,
                [
                    str(python), "-B", str(insight_script), "insight_cn",
                    "--days", str(args.days), "--source", "local", "--allow-health-data",
                ],
                120,
                deadline,
            )
            coverage = _coverage_summary(insight)
            if coverage["data_status"] not in {"complete", "partial"}:
                raise RuntimeError("local_coverage_unavailable")
            if not any(coverage["component_observation_counts"].values()):
                raise RuntimeError("local_coverage_empty")
            stale_components = _stale_components(coverage["component_latest_observation_dates"], end)
            if stale_components:
                state["stale_components"] = stale_components
                raise RuntimeError("terminal_coverage_stale")

            state.update(
                {
                    "status": "success",
                    "stage": "completed",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "stages": ["preflight_live", "plan", "download", "import_analyze", "verify_local"],
                    **coverage,
                }
            )
            _atomic_json(state_output, state)
            return 0, state
    except BlockingIOError:
        return 0, {"schema": SCHEMA, "status": "skipped_already_running"}
    except (RuntimeError, ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        error_code = _safe_error_code(stage, exc)
        state.update(
            {
                "status": "failed",
                "stage": stage,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error_code": error_code,
            }
        )
        _atomic_json(state_output, state)
        return 1, state
    finally:
        if plan_path.exists():
            plan_path.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded scheduled GarminDB sync")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--garmindb-python", required=True)
    parser.add_argument("--scratch-dir", required=True)
    parser.add_argument("--state-output", required=True)
    parser.add_argument("--authority-config", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--total-timeout-seconds", type=int, default=900)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-sync", action="store_true")
    parser.add_argument("--allow-health-data", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        code, state = run_scheduled_sync(args)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        code, state = 2, {
            "schema": SCHEMA,
            "status": "failed",
            "stage": "initialization",
            "error_code": _safe_error_code("initialization", exc),
        }
    if code != 0:
        try:
            output = Path(args.state_output)
            if output.is_absolute():
                _atomic_json(output, state)
        except (OSError, UnicodeError):
            pass
    _emit(state)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
