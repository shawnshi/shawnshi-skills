#!/usr/bin/env python3
"""Verify mode-specific dependencies in the selected Python interpreter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from importlib import metadata


MIN_PYTHON = (3, 11)
MODE_REQUIREMENTS = {
    "local": {"pandas": ("pandas", "3.0.6")},
    "live": {
        "pandas": ("pandas", "3.0.6"),
        "garminconnect": ("garminconnect", "0.3.17"),
    },
    "activity": {
        "fitparse": ("fitparse", "1.2.0"),
        "gpxpy": ("gpxpy", "1.6.2"),
    },
}


def probe_imports(modules: list[str]) -> dict[str, object]:
    """Import reviewed modules without initializing clients or ambient Garmin tokens."""
    code = r'''
import importlib, json, sys
apis = {"pandas": ("DataFrame",), "garminconnect": ("Garmin",),
        "fitparse": ("FitFile",), "gpxpy": ("parse",)}
try:
    for name in json.loads(sys.argv[1]):
        module = importlib.import_module(name)
        for symbol in apis[name]:
            if not hasattr(module, symbol):
                raise AttributeError("required_api_missing")
    print(json.dumps({"ok": True}))
except Exception as exc:
    print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
    sys.exit(1)
'''
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("GARTH_", "GARMIN_"))}
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, json.dumps(modules)],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", timeout=15, check=False,
        )
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or result.get("ok") is not (completed.returncode == 0):
            return {"ok": False, "error_type": "InvalidProbeOutput"}
        error_type = result.get("error_type")
        if error_type is not None and (not isinstance(error_type, str) or not error_type.isidentifier()):
            return {"ok": False, "error_type": "InvalidProbeOutput"}
        return {"ok": completed.returncode == 0, "error_type": error_type}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_type": "ImportTimeout"}
    except (OSError, ValueError):
        return {"ok": False, "error_type": "ImportProbeUnavailable"}


def verify_runtime(mode: str) -> dict[str, object]:
    """Return a machine-readable compatibility result for *mode*."""
    if mode not in MODE_REQUIREMENTS:
        raise ValueError(f"unsupported mode: {mode}")

    failures: list[dict[str, object]] = []
    requirements: dict[str, dict[str, object]] = {}
    minimum_python = (3, 12) if mode == "live" else MIN_PYTHON
    if sys.version_info < minimum_python:
        failures.append(
            {
                "package": "python",
                "reason": "version_mismatch",
                "expected": f">={minimum_python[0]}.{minimum_python[1]}",
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

        try:
            importable = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            importable = False
        requirements[distribution] = {
            "expected": expected,
            "actual": actual,
            "located": importable,
            "importable": None,
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

    import_probe = None
    if not failures:
        import_probe = probe_imports([module for module, _ in MODE_REQUIREMENTS[mode].values()])
        if not import_probe["ok"]:
            failures.append({"reason": "import_probe_failed", **import_probe})
        else:
            for requirement in requirements.values():
                requirement["importable"] = True
    ok = not failures
    return {
        "ok": ok,
        "status": "RUNTIME_READY" if ok else "RUNTIME_DEPENDENCY_UNAVAILABLE",
        "mode": mode,
        "import_probe": import_probe,
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
