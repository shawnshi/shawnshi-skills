#!/usr/bin/env python3
"""Fail-closed authority gate for the canonical health runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).replace("\\", "/")


def _locator(locator: dict) -> Path:
    if locator.get("base") != "user_home":
        raise ValueError("only user_home locators are allowed")
    segments = locator.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("locator segments are required")
    if any(
        not isinstance(item, str)
        or not item
        or item in {".", ".."}
        or "/" in item
        or "\\" in item
        for item in segments
    ):
        raise ValueError("locator segments must be simple path components")
    return Path.home().joinpath(*segments).resolve()


def _frontmatter(path: Path) -> dict[str, str]:
    match = FRONTMATTER_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"missing frontmatter: {path.name}")
    values: dict[str, str] = {}
    section: str | None = None
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        if line[:1].isspace():
            if section != "metadata":
                continue
            key, value = line.strip().split(":", 1)
            values[f"metadata.{key.strip()}"] = value.strip().strip("'\"")
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("'\"")
        section = key.strip() if not value.strip() else None
    return values


def _error(code: str, message: str, **details: object) -> dict:
    return {"ok": False, "error_code": code, "message": message, **details}


def verify(config: dict) -> dict:
    if config.get("schema_version") != 1:
        return _error("CONFIG_SCHEMA_MISMATCH", "schema_version must be 1")
    try:
        authority_path = _locator(config["authority_locator"])
        proxy_paths = [_locator(item) for item in config.get("proxy_locators", [])]
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        return _error("CONFIG_LOCATOR_INVALID", str(exc))
    skill_root = authority_path.parent
    if authority_path.name != "SKILL.md" or not authority_path.is_file():
        return _error("AUTHORITY_NOT_FOUND", "canonical SKILL.md is unavailable")
    if _normalized(skill_root) != _normalized(Path(__file__).resolve().parent.parent):
        return _error("GATE_LOCATION_MISMATCH", "authority gate is not running from the canonical root")

    actual_skill_sha = _sha256(authority_path)
    if actual_skill_sha != config.get("authority_sha256"):
        return _error(
            "AUTHORITY_HASH_MISMATCH",
            "canonical SKILL.md hash differs from the binding",
            expected_sha256=config.get("authority_sha256"),
            actual_sha256=actual_skill_sha,
        )
    try:
        authority_meta = _frontmatter(authority_path)
    except (OSError, UnicodeError, ValueError) as exc:
        return _error("AUTHORITY_PARSE_FAILED", str(exc))
    if authority_meta.get("name") != config.get("skill_name"):
        return _error("AUTHORITY_NAME_MISMATCH", "canonical skill name changed")
    authority_version = authority_meta.get("metadata.version") or authority_meta.get("version")
    if authority_version != config.get("authority_version"):
        return _error("AUTHORITY_VERSION_MISMATCH", "canonical skill version changed")

    entrypoints: dict[str, str] = {}
    for relative, expected_sha in config.get("entrypoint_sha256", {}).items():
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            return _error("ENTRYPOINT_PATH_INVALID", "entrypoint path is not portable")
        candidate = (skill_root / relative).resolve()
        try:
            candidate.relative_to(skill_root.resolve())
        except ValueError:
            return _error("ENTRYPOINT_PATH_INVALID", "entrypoint escapes the skill root")
        if not candidate.is_file():
            return _error("ENTRYPOINT_NOT_FOUND", "bound entrypoint is unavailable", entrypoint=relative)
        actual_sha = _sha256(candidate)
        if actual_sha != expected_sha:
            return _error(
                "ENTRYPOINT_HASH_MISMATCH",
                "bound entrypoint hash differs",
                entrypoint=relative,
                expected_sha256=expected_sha,
                actual_sha256=actual_sha,
            )
        entrypoints[relative] = _normalized(candidate)

    task_binding = config.get("task_binding")
    if (
        not isinstance(task_binding, dict)
        or not re.fullmatch(r"[0-9a-f]{64}", str(task_binding.get("arguments_sha256", "")))
    ):
        return _error("TASK_BINDING_INVALID", "task action SHA-256 binding is missing or invalid")

    authority_norm = _normalized(authority_path)
    for proxy in proxy_paths:
        if not proxy.is_file():
            continue
        try:
            metadata = _frontmatter(proxy)
        except (OSError, UnicodeError, ValueError) as exc:
            return _error("PROXY_PARSE_FAILED", str(exc))
        if metadata.get("name") != config.get("skill_name"):
            continue
        proxy_target = metadata.get("metadata.authority_proxy_for") or metadata.get("authority_proxy_for", "")
        proxy_version = metadata.get("metadata.authority_version") or metadata.get("authority_version")
        proxy_sha = metadata.get("metadata.authority_sha256") or metadata.get("authority_sha256")
        if _normalized(proxy_target) != authority_norm:
            return _error("PROXY_TARGET_MISMATCH", "same-name proxy points elsewhere")
        if proxy_version != config.get("authority_version"):
            return _error("PROXY_VERSION_MISMATCH", "same-name proxy version is stale")
        if proxy_sha != actual_skill_sha:
            return _error("PROXY_HASH_MISMATCH", "same-name proxy hash is stale")

    return {
        "ok": True,
        "schema": "health-runtime-authority.v1",
        "skill_name": config["skill_name"],
        "authority_version": config["authority_version"],
        "authority_sha256": actual_skill_sha,
        "authority_path": authority_norm,
        "skill_root": _normalized(skill_root),
        "entrypoints": entrypoints,
        "task_binding": task_binding,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        result = verify(config)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = _error("CONFIG_READ_FAILED", str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
