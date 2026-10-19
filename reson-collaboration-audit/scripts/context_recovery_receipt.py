"""Validate a minimal post-compaction state packet and emit a redacted receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_state(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["state must be a JSON object"]
    errors: list[str] = []
    objective = payload.get("objective")
    authorization = payload.get("authorization_scope")
    completed = payload.get("completed_steps")
    outputs = payload.get("output_paths")
    if not isinstance(objective, str) or not objective.strip():
        errors.append("objective must be a non-empty string")
    if not isinstance(authorization, (str, dict)) or authorization in ("", {}):
        errors.append("authorization_scope must be a non-empty string or object")
    if not isinstance(completed, list) or any(not isinstance(item, str) or not item.strip() for item in completed):
        errors.append("completed_steps must be an array of non-empty strings")
    if not isinstance(outputs, list) or any(not isinstance(item, str) or not item.strip() for item in outputs):
        errors.append("output_paths must be an array of non-empty strings")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit a redacted context recovery receipt.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--root-task-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--context-epoch", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    state_path = Path(args.state).resolve()
    output_path = Path(args.output).resolve()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    errors = validate_state(payload)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
        return 2

    receipt = {
        "schema_version": 2,
        "event_id": f"context-recovery-{args.root_task_id}-{args.context_epoch}",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root_task_id": args.root_task_id,
        "actor_id": args.actor_id,
        "actor_type": "root",
        "event_type": "context_recovered",
        "component": "context_recovery_receipt",
        "operation": "restore_context",
        "status": "ok",
        "context_epoch": str(args.context_epoch),
        "recovery_artifact_present": True,
        "required_fields_verified": True,
        "state_sha256": canonical_sha256(payload),
        "completed_step_count": len(payload["completed_steps"]),
        "output_path_count": len(payload["output_paths"]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append else "x"
    with output_path.open(mode, encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"ok": True, "output": str(output_path), "state_sha256": receipt["state_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
