import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

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


def build_receipt(skill_path, root_task_id, actor_id, context_epoch):
    identities = (root_task_id, actor_id, context_epoch)
    if any(not isinstance(value, str) or not value.strip() for value in identities):
        raise ValueError("root_task_id, actor_id and context_epoch are required")
    path = Path(skill_path).resolve()
    if not path.is_file() or path.name != "SKILL.md":
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    meta = _metadata(text)
    digest = hashlib.sha256(raw).hexdigest()
    normalized_path = os.path.normcase(str(path)).replace("\\", "/")
    tokenizer_name = "cl100k_base"
    tokenizer = tiktoken.get_encoding(tokenizer_name)
    return {
        "schema_version": 2,
        "event_id": f"skill-load-{digest[:12]}-{context_epoch}",
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
        "skill_tokens": len(tokenizer.encode(text)),
        "tokenizer": tokenizer_name,
    }


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
                    if receipt_key(existing) == key:
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
    args = parser.parse_args()
    receipt = build_receipt(
        args.skill_path, args.root_task_id, args.actor_id, args.context_epoch
    )
    if args.output:
        append_receipt(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
