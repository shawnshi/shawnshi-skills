#!/usr/bin/env python3
"""Deterministic archive paths for collaboration-audit Markdown and HTML."""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping


REPORT_DIR_ENV = "MENTAT_AUDIT_REPORT_DIR"
PERIOD_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def get_report_dir(
    *,
    env: Mapping[str, str] | None = None,
    workspace: Path | None = None,
    allow_environment: bool = False,
) -> Path:
    """Return the configured report archive without creating it."""
    env_values = os.environ if env is None else env
    configured = env_values.get(REPORT_DIR_ENV) if allow_environment else None
    if configured and configured.strip():
        return Path(configured).expanduser()

    workspace_root = Path.cwd() if workspace is None else Path(workspace)
    return workspace_root / "output" / "mentat-collaboration-audit"


def build_report_paths(
    *,
    period: str,
    now: datetime | None = None,
    output_dir: Path | None = None,
    use_configured_output_dir: bool = False,
    create_dir: bool = False,
) -> dict[str, Path]:
    """Build paired Markdown and HTML paths with a shared run identifier."""
    if not period or not PERIOD_PATTERN.fullmatch(period):
        raise ValueError(
            "period must contain only letters, digits, underscore, or hyphen"
        )

    archive_dir = (
        get_report_dir(allow_environment=use_configured_output_dir)
        if output_dir is None
        else Path(output_dir).expanduser()
    )
    if create_dir:
        archive_dir.mkdir(parents=True, exist_ok=True)

    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    stem = f"collaboration_audit_{period}_{timestamp}"
    return {
        "output_dir": archive_dir,
        "markdown": archive_dir / f"{stem}.md",
        "html": archive_dir / f"{stem}.html",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Allocate paired collaboration-audit report paths."
    )
    parser.add_argument("--period", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--use-configured-output-dir",
        action="store_true",
        help=f"explicitly use {REPORT_DIR_ENV}; ignored unless this flag is supplied",
    )
    parser.add_argument(
        "--timestamp",
        help="Optional deterministic timestamp in YYYYMMDD_HHMMSS format.",
    )
    args = parser.parse_args()
    if args.output_dir and args.use_configured_output_dir:
        parser.error("--output-dir and --use-configured-output-dir are mutually exclusive")

    now = (
        datetime.strptime(args.timestamp, "%Y%m%d_%H%M%S")
        if args.timestamp
        else None
    )
    paths = build_report_paths(
        period=args.period,
        now=now,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        use_configured_output_dir=args.use_configured_output_dir,
        create_dir=True,
    )
    print(
        json.dumps(
            {key: str(value) for key, value in paths.items()},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
