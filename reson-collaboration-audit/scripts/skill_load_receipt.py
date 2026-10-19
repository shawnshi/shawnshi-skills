import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import tiktoken


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
RECEIPT_KEY_FIELDS = (
    "root_task_id",
    "actor_id",
    "context_epoch",
    "skill_name",
    "skill_sha256",
)


def _metadata(text):
    match = FRONTMATTER_RE.search(text)
    if not match:
        raise ValueError("SKILL.md is missing YAML frontmatter")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    if not values.get("name"):
        raise ValueError("SKILL.md frontmatter is missing name")
    return values


def build_receipt(skill_path, root_task_id, actor_id, context_epoch, event_id=None, candidate_event_id=None):
    identities = (root_task_id, actor_id, context_epoch)
    if any(not isinstance(value, str) or not value.strip() for value in identities):
        raise ValueError("root_task_id, actor_id and context_epoch are required")
    for value in (event_id, candidate_event_id):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("event_id and candidate_event_id must be non-empty strings when supplied")
    path = Path(skill_path).resolve()
    if not path.is_file() or path.name != "SKILL.md":
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    meta = _metadata(text)
    digest = hashlib.sha256(raw).hexdigest()
    normalized_path = os.path.normcase(str(path)).replace("\\", "/")
    receipt = {
        "schema_version": 2,
        "event_id": event_id if event_id is not None else f"skill-load-{uuid4()}",
        "event_identity": "occurrence",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root_task_id": root_task_id,
        "actor_id": actor_id,
        "actor_type": "root" if actor_id == "root" else "subagent",
        "event_type": "skill_load",
        "component": "skill_loader",
        "operation": "read_full_skill",
        "status": "ok",
        "context_epoch": context_epoch,
        "skill_name": meta["name"],
        "skill_path_sha256": hashlib.sha256(normalized_path.encode("utf-8")).hexdigest(),
        "skill_version": meta.get("version"),
        "skill_sha256": digest,
    }
    if candidate_event_id is not None:
        receipt["candidate_event_id"] = candidate_event_id
    receipt["token_measurement_basis"] = "skill_text"
    tokenizer_name = "cl100k_base"
    try:
        tokenizer = tiktoken.get_encoding(tokenizer_name)
        receipt["skill_tokens"] = len(tokenizer.encode(text))
        receipt["tokenizer"] = tokenizer_name
    except (OSError, ValueError, RuntimeError) as exc:
        # Preserve a measurement error, not a fabricated zero-token observation.
        receipt["token_measurement_status"] = "error"
        receipt["token_measurement_error_type"] = type(exc).__name__
    return receipt


def receipt_key(receipt):
    values = tuple(receipt.get(field) for field in RECEIPT_KEY_FIELDS)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("receipt is missing an idempotency field")
    return values


def append_receipt(output_path, receipt):
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output.with_name(output.name + ".lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"receipt output is locked: {output}") from exc

    try:
        os.close(lock_fd)
        key = receipt_key(receipt)
        if receipt.get("event_identity") == "occurrence" and (
            not isinstance(receipt.get("event_id"), str) or not receipt["event_id"].strip()
        ):
            raise ValueError("occurrence receipts require event_id")
        replay = False
        if output.exists():
            with output.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"invalid receipt JSON at {output}:{line_number}"
                        ) from exc
                    existing_key = receipt_key(existing)
                    if receipt.get("event_identity") == "occurrence":
                        if (existing.get("event_identity") == "occurrence"
                                and existing.get("event_id") == receipt["event_id"]
                                and existing_key[:2] == key[:2]):
                            fields = RECEIPT_KEY_FIELDS + (
                                "skill_path_sha256", "skill_tokens", "tokenizer",
                                "candidate_event_id", "token_measurement_basis", "token_scope_id",
                                "status", "outcome", "token_measurement_status", "token_measurement_error_type",
                            )
                            existing_payload = {field: existing[field] for field in fields if field in existing}
                            receipt_payload = {field: receipt[field] for field in fields if field in receipt}
                            if json.dumps(existing_payload, sort_keys=True) != json.dumps(receipt_payload, sort_keys=True):
                                raise ValueError("event_id conflicts with an existing occurrence receipt")
                            replay = True
                    elif existing.get("event_identity") != "occurrence" and existing_key == key:
                        # Preserve append compatibility for caller-supplied legacy receipts.
                        replay = True
        if replay:
            return False

        line = json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n"
        with output.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    finally:
        lock_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-path", required=True)
    parser.add_argument("--root-task-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--context-epoch", required=True)
    parser.add_argument("--output")
    parser.add_argument("--event-id", help="Stable ID for one real load; reuse only to replay its receipt. Omission creates a new occurrence.")
    parser.add_argument("--candidate-event-id", help="Optional ID of the exact observed candidate occurrence.")
    args = parser.parse_args()
    receipt = build_receipt(
        args.skill_path, args.root_task_id, args.actor_id, args.context_epoch,
        event_id=args.event_id, candidate_event_id=args.candidate_event_id,
    )
    if args.output:
        append_receipt(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
