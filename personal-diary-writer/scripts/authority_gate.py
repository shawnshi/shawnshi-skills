import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import tiktoken


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_path(path):
    return os.path.normcase(os.path.abspath(os.fspath(path))).replace("\\", "/")


def _resolve_locator(locator):
    if not isinstance(locator, dict):
        raise ValueError("locator must be an object")
    base = locator.get("base")
    if base == "user_home":
        root = Path.home()
        segments = locator.get("segments", [])
        if not isinstance(segments, list) or not segments:
            raise ValueError("user_home locator requires non-empty segments")
        if any(
            not isinstance(segment, str)
            or not segment
            or segment in {".", ".."}
            or "/" in segment
            or "\\" in segment
            for segment in segments
        ):
            raise ValueError("locator segments must be simple path components")
        return root.joinpath(*segments).resolve()
    if base == "absolute":
        path = locator.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("absolute locator requires path")
        return Path(path).resolve()
    raise ValueError("unsupported locator base")


def _frontmatter(path):
    text = Path(path).read_text(encoding="utf-8")
    match = FRONTMATTER_RE.search(text)
    if not match:
        raise ValueError(f"Missing YAML frontmatter: {path}")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values, text


def _error(code, message, **details):
    return {"ok": False, "error_code": code, "message": message, **details}


def verify(config, root_task_id, actor_id, context_epoch):
    schema_version = config.get("schema_version")
    if schema_version not in {1, 2}:
        return _error("CONFIG_SCHEMA_MISMATCH", "authority config schema_version must be 1 or 2")
    required = (root_task_id, actor_id, context_epoch)
    if any(not isinstance(value, str) or not value.strip() for value in required):
        return _error("MISSING_EVENT_IDENTITY", "root task, actor, and context epoch are required")

    try:
        if schema_version == 2:
            authority = _resolve_locator(config["authority_locator"])
            candidate_paths = [
                _resolve_locator(locator)
                for locator in config.get("candidate_locators", [])
            ]
            allowed_proxy_paths = [
                _resolve_locator(locator)
                for locator in config.get("allowed_proxy_locators", [])
            ]
        else:
            authority = Path(config["authority_path"]).resolve()
            candidate_paths = [
                Path(value).resolve() for value in config.get("candidate_paths", [])
            ]
            allowed_proxy_paths = [
                Path(value).resolve() for value in config.get("allowed_proxy_paths", [])
            ]
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        return _error("CONFIG_LOCATOR_INVALID", str(exc))
    if not authority.is_file():
        return _error("AUTHORITY_NOT_FOUND", "configured authority path does not exist")
    actual_sha256 = sha256_file(authority)
    if actual_sha256 != config.get("authority_sha256"):
        return _error(
            "AUTHORITY_HASH_MISMATCH",
            "configured authority hash does not match current SKILL.md",
            expected_sha256=config.get("authority_sha256"),
            actual_sha256=actual_sha256,
        )

    try:
        authority_meta, authority_text = _frontmatter(authority)
    except (OSError, UnicodeError, ValueError) as exc:
        return _error("AUTHORITY_PARSE_FAILED", str(exc))
    if authority_meta.get("name") != config.get("skill_name"):
        return _error("AUTHORITY_NAME_MISMATCH", "authority skill name changed")
    if authority_meta.get("version") != config.get("authority_version"):
        return _error("AUTHORITY_VERSION_MISMATCH", "authority skill version changed")

    authority_norm = _normalized_path(authority)
    allowed_proxies = {
        _normalized_path(path) for path in allowed_proxy_paths
    }
    for candidate in candidate_paths:
        if not candidate.is_file() or _normalized_path(candidate) == authority_norm:
            continue
        try:
            candidate_meta, _ = _frontmatter(candidate)
        except (OSError, UnicodeError, ValueError) as exc:
            return _error("CANDIDATE_PARSE_FAILED", str(exc), candidate=str(candidate))
        if candidate_meta.get("name") != config.get("skill_name"):
            continue
        candidate_norm = _normalized_path(candidate)
        if candidate_norm not in allowed_proxies:
            return _error(
                "UNBOUND_SKILL_FORK",
                "same-name skill exists outside the bound proxy set",
                candidate=candidate_norm,
            )
        if schema_version == 1:
            if _normalized_path(candidate_meta.get("authority_proxy_for", "")) != authority_norm:
                return _error("PROXY_TARGET_MISMATCH", "proxy points to a different authority")
            if candidate_meta.get("authority_sha256") != actual_sha256:
                return _error("PROXY_HASH_MISMATCH", "proxy authority hash is stale")

    tokenizer_name = "cl100k_base"
    tokenizer = tiktoken.get_encoding(tokenizer_name)
    event = {
        "schema_version": 2,
        "event_id": f"skill-load-{actual_sha256[:12]}-{context_epoch}",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root_task_id": root_task_id,
        "actor_id": actor_id,
        "actor_type": "root" if actor_id == "root" else "subagent",
        "event_type": "skill_load",
        "component": "skill_authority_gate",
        "operation": "read_full_skill",
        "status": "ok",
        "context_epoch": context_epoch,
        "skill_name": config["skill_name"],
        "skill_path": authority_norm,
        "skill_version": config["authority_version"],
        "skill_sha256": actual_sha256,
        "skill_tokens": len(tokenizer.encode(authority_text)),
        "tokenizer": tokenizer_name,
    }
    return {"ok": True, "authority_path": authority_norm, "skill_load": event}


def _append_event(path, event):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    with open(output, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--root-task-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--context-epoch", required=True)
    parser.add_argument("--event-output")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    result = verify(config, args.root_task_id, args.actor_id, args.context_epoch)
    if result.get("ok") and args.event_output:
        _append_event(args.event_output, result["skill_load"])
        result["event_output"] = _normalized_path(args.event_output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result.get("ok"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
