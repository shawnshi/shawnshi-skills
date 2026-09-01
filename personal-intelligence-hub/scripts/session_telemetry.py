from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from hub_utils import atomic_dump_json
from run_contract import load_manifest, record_execution_telemetry


MAX_SESSION_BYTES = 256 * 1024 * 1024
USAGE_FIELDS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "reasoning": "reasoning_tokens",
    "cacheRead": "cache_read_tokens",
    "cacheWrite": "cache_write_tokens",
    "totalTokens": "total_tokens",
}


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def summarize_sessions(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one session file is required")
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("session files must be unique")
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "assistant_messages": 0,
        "tool_results": 0,
        "tool_errors": 0,
    }
    sources: list[dict[str, Any]] = []
    observed_times: list[datetime] = []
    for path in resolved:
        if not path.is_file():
            raise ValueError(f"session file not found: {path}")
        size = path.stat().st_size
        if size > MAX_SESSION_BYTES:
            raise ValueError(f"session file exceeds {MAX_SESSION_BYTES} bytes: {path.name}")
        raw = path.read_bytes()
        record_count = 0
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid session JSON at {path.name}:{line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"session record must be an object at {path.name}:{line_number}"
                )
            record_count += 1
            timestamp = _timestamp(record.get("timestamp"))
            if timestamp is not None:
                observed_times.append(timestamp)
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "assistant":
                usage["assistant_messages"] += 1
                raw_usage = message.get("usage")
                if isinstance(raw_usage, dict):
                    for source_field, target_field in USAGE_FIELDS.items():
                        value = raw_usage.get(source_field, 0)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            usage[target_field] += value
                    cost = raw_usage.get("cost")
                    if isinstance(cost, dict):
                        total = cost.get("total", 0)
                        if isinstance(total, (int, float)) and not isinstance(total, bool):
                            usage["cost_usd"] += float(total)
            elif role == "toolResult":
                usage["tool_results"] += 1
                if message.get("isError") is True:
                    usage["tool_errors"] += 1
        sources.append(
            {
                "file_name": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": size,
                "records": record_count,
            }
        )
    usage["cost_usd"] = round(float(usage["cost_usd"]), 6)
    usage["budget_tokens"] = (
        usage["total_tokens"]
        - usage["cache_read_tokens"]
        - usage["cache_write_tokens"]
    )
    if usage["budget_tokens"] < 0:
        raise ValueError("session token counters are inconsistent")
    started_at = min(observed_times) if observed_times else None
    ended_at = max(observed_times) if observed_times else None
    return {
        "usage": usage,
        "sources": sources,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_seconds": (
            round((ended_at - started_at).total_seconds(), 3)
            if started_at is not None and ended_at is not None
            else 0.0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate token, cost, timing, and error counts from local Pi JSONL without copying message content."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument(
        "--status",
        choices=("completed", "degraded", "degraded_timeout", "failed", "cancelled"),
        required=True,
    )
    parser.add_argument("--session", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.invocation_id):
        parser.error("--invocation-id is invalid")
    try:
        manifest = load_manifest(args.manifest)
        summary = summarize_sessions(args.session)
        run_dir = Path(manifest["run_dir"]).resolve()
        output = (
            args.output.resolve()
            if args.output is not None
            else run_dir / f"execution_telemetry_{args.stage}_{args.invocation_id}.json"
        )
        if output.parent != run_dir:
            raise ValueError("telemetry output must be inside the run directory")
        payload = {
            "contract_version": "pih-execution-telemetry/1.0",
            "run_id": manifest["run_id"],
            "stage": args.stage,
            "invocation_id": args.invocation_id,
            "status": args.status,
            **summary,
        }
        atomic_dump_json(output, payload)
        record_execution_telemetry(args.manifest, output)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "registered",
                "artifact_path": str(output),
                "total_tokens": payload["usage"]["total_tokens"],
                "budget_tokens": payload["usage"]["budget_tokens"],
                "cost_usd": payload["usage"]["cost_usd"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
