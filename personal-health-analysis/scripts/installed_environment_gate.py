#!/usr/bin/env python3
"""Verify that a fresh skill venv contains only locked and bootstrap packages."""

from __future__ import annotations

import argparse
import json
import re
from importlib import metadata
from pathlib import Path


ALLOWED_BOOTSTRAP = {"pip", "setuptools"}
LOCK_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s]+)$")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def read_locked_versions(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("requirements_lock_read_failed") from exc
    locked: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = LOCK_LINE.fullmatch(stripped)
        if not match:
            raise ValueError("requirements_lock_entry_invalid")
        name, version = _normalize(match.group(1)), match.group(2)
        if name in locked:
            raise ValueError("requirements_lock_duplicate_distribution")
        locked[name] = version
    if not locked:
        raise ValueError("requirements_lock_empty")
    return locked


def verify_installed(path: Path) -> dict:
    locked = read_locked_versions(path)
    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            raise ValueError("installed_distribution_name_missing")
        normalized = _normalize(name)
        if normalized in installed:
            raise ValueError("installed_distribution_duplicate")
        installed[normalized] = distribution.version
    extras = sorted(set(installed) - set(locked) - ALLOWED_BOOTSTRAP)
    missing = sorted(set(locked) - set(installed))
    mismatched = sorted(
        name
        for name, version in locked.items()
        if name in installed and installed[name] != version
    )
    if extras or missing or mismatched:
        raise ValueError("installed_environment_lock_mismatch")
    return {
        "ok": True,
        "status": "installed_environment_matches_lock",
        "locked_distribution_count": len(locked),
        "bootstrap_distributions": sorted(set(installed) & ALLOWED_BOOTSTRAP),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements-lock", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_installed(args.requirements_lock)
    except ValueError as exc:
        print(json.dumps({"ok": False, "status": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
