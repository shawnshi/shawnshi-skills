#!/usr/bin/env python3
"""Deterministic archive paths for persisted Garmin Markdown and HTML reports."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping


REPORT_DIR_ENV = "GARMIN_REPORT_DIR"
LEGACY_OUTPUT_DIR_ENV = "GARMIN_OUTPUT_DIR"
DEFAULT_REPORT_DIR = Path.home() / "MEMORY" / "raw" / "garmin"


def get_report_dir(
    *,
    env: Mapping[str, str] | None = None,
    workspace: Path | None = None,
) -> Path:
    """Return the configured report archive without creating it."""
    env_values = os.environ if env is None else env
    configured = env_values.get(REPORT_DIR_ENV) or env_values.get(
        LEGACY_OUTPUT_DIR_ENV
    )
    if configured:
        return Path(configured).expanduser().resolve()

    return DEFAULT_REPORT_DIR.resolve()


def build_report_paths(
    *,
    days: int,
    now: datetime | None = None,
    output_dir: Path | None = None,
    create_dir: bool = False,
    allow_overwrite: bool = False,
) -> dict[str, Path]:
    """Build paired Markdown and HTML paths with a shared run identifier."""
    if days <= 0:
        raise ValueError("days must be positive")

    archive_dir = (
        get_report_dir()
        if output_dir is None
        else Path(output_dir).expanduser().resolve()
    )
    if create_dir:
        archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    stem = f"health_analysis_{days}days_{timestamp}"
    paths = {
        "output_dir": archive_dir,
        "markdown": archive_dir / f"{stem}.md",
        "html": archive_dir / f"{stem}.html",
    }
    if not allow_overwrite:
        collisions = [paths[key] for key in ("markdown", "html") if paths[key].exists()]
        if collisions:
            raise FileExistsError("report_output_exists")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Allocate paired Garmin report paths."
    )
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--timestamp",
        help="Optional deterministic timestamp in YYYYMMDD_HHMMSS format.",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Allow returning paths that already exist",
    )
    args = parser.parse_args()

    now = (
        datetime.strptime(args.timestamp, "%Y%m%d_%H%M%S")
        if args.timestamp
        else None
    )
    try:
        paths = build_report_paths(
            days=args.days,
            now=now,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            create_dir=True,
            allow_overwrite=args.allow_overwrite,
        )
    except FileExistsError:
        print(json.dumps({"ok": False, "status": "output_exists"}))
        return 2
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
