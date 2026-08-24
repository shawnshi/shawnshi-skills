#!/usr/bin/env python3
"""Run a bounded, user-authorized GarminDB sync for a scheduled task."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


SCHEMA = "garmin-auto-sync-status.v1"
COMPONENTS = ("sleep", "hrv", "body_battery", "heart_rate", "stress")
PLAN_TIMEOUT_SECONDS = 300


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
    dates = [source.get("date") for source in sources.values() if source.get("date")]
    return {
        "data_status": insight.get("data_status") or insight.get("status"),
        "component_observation_counts": counts,
        "latest_observation_date": max(dates) if dates else None,
    }


def _base_state(start: str, end: str, started_at: str) -> dict:
    return {
        "schema": SCHEMA,
        "status": "running",
        "started_at": started_at,
        "requested_window": {"start": start, "end": end},
        "components": list(COMPONENTS),
        "health_values_persisted": False,
    }


def run_scheduled_sync(
    args: argparse.Namespace,
    *,
    runner: Callable[[list[str], int], dict] = _run_json,
    today: date | None = None,
) -> tuple[int, dict]:
    if not (args.allow_network and args.allow_sync and args.allow_health_data):
        return 2, {"schema": SCHEMA, "status": "capability_denied"}

    python = Path(sys.executable).resolve()
    garmindb_python = Path(args.garmindb_python).resolve()
    config_dir = Path(args.config_dir).resolve()
    scratch_dir = Path(args.scratch_dir).resolve()
    state_output = Path(args.state_output).resolve()
    for required in (python, garmindb_python, config_dir):
        if not required.exists():
            return 2, {"schema": SCHEMA, "status": "invalid_runtime_path"}
    if not all(path.is_absolute() for path in (scratch_dir, state_output)):
        return 2, {"schema": SCHEMA, "status": "invalid_output_path"}

    scratch_dir.mkdir(parents=True, exist_ok=True)
    end_date = today or date.today()
    start, end = compute_window(end_date, args.days)
    started_at = datetime.now(timezone.utc).isoformat()
    state = _base_state(start, end, started_at)
    script_dir = Path(__file__).resolve().parent
    sync_script = script_dir / "sync_health_data.py"
    preflight_script = script_dir / "runtime_preflight.py"
    insight_script = script_dir / "garmin_intelligence.py"
    plan_path = scratch_dir / f"sync-plan-{os.getpid()}-{end_date.isoformat()}.json"

    stage = "initialization"
    try:
        with _singleton(scratch_dir / "garmin-auto-sync.lock"):
            stage = "live_preflight"
            live_preflight = runner([str(python), "-B", str(preflight_script), "--mode", "live"], 60)
            if not live_preflight.get("ok"):
                raise RuntimeError("live_preflight_failed")

            stage = "plan"
            dry_run = runner(
                [
                    str(python), "-B", str(sync_script), "sync",
                    "--start", start, "--end", end, "--dry-run",
                    "--config-dir", str(config_dir),
                    "--garmindb-python", str(garmindb_python),
                    "--plan-output", str(plan_path),
                    "--plan-ttl-seconds", "900",
                ],
                PLAN_TIMEOUT_SECONDS,
            )
            if dry_run.get("status") != "dry_run" or not plan_path.exists():
                raise RuntimeError("sync_plan_failed")

            stage = "sync_execution"
            sync_result = runner(
                [
                    str(python), "-B", str(sync_script), "sync",
                    "--start", start, "--end", end,
                    "--allow-network", "--allow-sync",
                    "--config-dir", str(config_dir),
                    "--garmindb-python", str(garmindb_python),
                    "--plan-file", str(plan_path),
                    "--timeout-seconds", str(args.timeout_seconds),
                ],
                args.timeout_seconds + 120,
            )
            if sync_result.get("status") != "sync_completed":
                raise RuntimeError("sync_execution_failed")

            stage = "local_preflight"
            local_preflight = runner([str(python), "-B", str(preflight_script), "--mode", "local"], 60)
            if not local_preflight.get("ok"):
                raise RuntimeError("local_preflight_failed")
            stage = "local_coverage"
            insight = runner(
                [
                    str(python), "-B", str(insight_script), "insight_cn",
                    "--days", str(args.days), "--source", "local", "--allow-health-data",
                ],
                120,
            )
            coverage = _coverage_summary(insight)
            if coverage["data_status"] not in {"complete", "partial"}:
                raise RuntimeError("local_coverage_unavailable")
            if not any(coverage["component_observation_counts"].values()):
                raise RuntimeError("local_coverage_empty")

            state.update(
                {
                    "status": "success",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "stages": ["preflight_live", "plan", "download", "import_analyze", "verify_local"],
                    **coverage,
                }
            )
            _atomic_json(state_output, state)
            return 0, state
    except BlockingIOError:
        return 0, {"schema": SCHEMA, "status": "skipped_already_running"}
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        error_code = f"{stage}_timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        state.update(
            {
                "status": "failed",
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
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-sync", action="store_true")
    parser.add_argument("--allow-health-data", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        code, state = run_scheduled_sync(args)
    except ValueError as exc:
        code, state = 2, {"schema": SCHEMA, "status": "invalid_request", "error_code": str(exc)}
    _emit(state)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
