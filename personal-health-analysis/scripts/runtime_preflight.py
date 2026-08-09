#!/usr/bin/env python3
"""Verify mode-specific dependencies in the selected Python interpreter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from importlib import metadata


MIN_PYTHON = (3, 11)
MODE_REQUIREMENTS = {
    "local": {"pandas": ("pandas", "3.0.3")},
    "live": {
        "pandas": ("pandas", "3.0.3"),
        "garminconnect": ("garminconnect", "0.3.9"),
    },
    "activity": {
        "fitparse": ("fitparse", "1.2.0"),
        "gpxpy": ("gpxpy", "1.6.2"),
    },
}


def verify_runtime(mode: str) -> dict[str, object]:
    """Return a machine-readable compatibility result for *mode*."""
    if mode not in MODE_REQUIREMENTS:
        raise ValueError(f"unsupported mode: {mode}")

    failures: list[dict[str, object]] = []
    requirements: dict[str, dict[str, object]] = {}
    if sys.version_info < MIN_PYTHON:
        failures.append(
            {
                "package": "python",
                "reason": "version_mismatch",
                "expected": f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
                "actual": ".".join(str(part) for part in sys.version_info[:3]),
            }
        )

    for distribution, (module, expected) in MODE_REQUIREMENTS[mode].items():
        try:
            actual = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            requirements[distribution] = {
                "expected": expected,
                "actual": None,
                "importable": False,
            }
            failures.append(
                {
                    "package": distribution,
                    "reason": "missing",
                    "expected": expected,
                    "actual": None,
                }
            )
            continue

        importable = importlib.util.find_spec(module) is not None
        requirements[distribution] = {
            "expected": expected,
            "actual": actual,
            "importable": importable,
        }
        if actual != expected:
            failures.append(
                {
                    "package": distribution,
                    "reason": "version_mismatch",
                    "expected": expected,
                    "actual": actual,
                }
            )
        elif not importable:
            failures.append(
                {
                    "package": distribution,
                    "reason": "not_importable",
                    "expected": expected,
                    "actual": actual,
                }
            )

    ok = not failures
    return {
        "ok": ok,
        "status": "RUNTIME_READY" if ok else "RUNTIME_DEPENDENCY_UNAVAILABLE",
        "mode": mode,
        "python_executable": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "requirements": requirements,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the selected interpreter before running health tools."
    )
    parser.add_argument("--mode", choices=sorted(MODE_REQUIREMENTS), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = verify_runtime(args.mode)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
