from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_STABLE_SECONDS = 1.0
DEFAULT_POLL_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 10.0


def _valid_json_object(path: Path) -> tuple[tuple[int, str] | None, str | None]:
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, OSError) as exc:
        return None, exc.__class__.__name__
    if not raw:
        return None, "empty"
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "not_json_object"
    return (len(raw), hashlib.sha256(raw).hexdigest()), None


def wait_for_artifacts(
    paths: list[Path],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    stable_seconds: float = DEFAULT_STABLE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one artifact path is required")
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be within (0, {MAX_TIMEOUT_SECONDS}]")
    if stable_seconds < 0 or stable_seconds > timeout_seconds:
        raise ValueError("stable_seconds must be within [0, timeout_seconds]")
    if not 0 < poll_seconds <= 1:
        raise ValueError("poll_seconds must be within (0, 1]")

    resolved = list(dict.fromkeys(path.resolve() for path in paths))
    started = time.monotonic()
    deadline = started + timeout_seconds
    observations: dict[Path, dict[str, Any]] = {
        path: {"signature": None, "stable_since": None, "reason": "not_checked"}
        for path in resolved
    }

    while True:
        now = time.monotonic()
        all_ready = True
        for path in resolved:
            signature, reason = _valid_json_object(path)
            state = observations[path]
            if signature is None:
                state.update(signature=None, stable_since=None, reason=reason)
                all_ready = False
                continue
            if state["signature"] != signature:
                state.update(signature=signature, stable_since=now, reason="stabilizing")
            if now - float(state["stable_since"]) < stable_seconds:
                all_ready = False
            else:
                state["reason"] = "ready"

        if all_ready:
            return {
                "status": "ready",
                "elapsed_seconds": round(now - started, 3),
                "artifacts": [
                    {
                        "path": str(path),
                        "bytes": observations[path]["signature"][0],
                        "sha256": observations[path]["signature"][1],
                    }
                    for path in resolved
                ],
            }
        if now >= deadline:
            return {
                "status": "timed_out",
                "elapsed_seconds": round(now - started, 3),
                "pending": [
                    {"path": str(path), "reason": observations[path]["reason"]}
                    for path in resolved
                    if observations[path]["reason"] != "ready"
                ],
            }
        time.sleep(min(poll_seconds, max(0.0, deadline - now)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wait briefly for atomic, stable JSON-object artifacts without mutating them."
    )
    parser.add_argument("--path", type=Path, action="append", required=True)
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument("--stable-seconds", type=float, default=DEFAULT_STABLE_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args()
    try:
        result = wait_for_artifacts(
            args.path,
            timeout_seconds=args.timeout_seconds,
            stable_seconds=args.stable_seconds,
            poll_seconds=args.poll_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
