"""Stable CLI entrypoint for the explicit-input collaboration audit engine."""

from __future__ import annotations

import sys
from pathlib import Path


ENGINE_DIR = Path(__file__).resolve().parent / "scripts" / "core"
sys.path.insert(0, str(ENGINE_DIR))

from engine import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
