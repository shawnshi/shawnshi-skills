#!/usr/bin/env python3
"""Run the discovery-call stdlib unittest suite with a machine summary."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行discovery-call自动化测试。")
    parser.add_argument("tests", nargs="*", help="可选的unittest全限定test id。")
    parser.add_argument("--pattern", default="test*.py", help="discover文件模式。")
    parser.add_argument("--verbosity", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--failfast", action="store_true")
    parser.add_argument("--json", action="store_true", help="将汇总以JSON写到stdout。")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if str(SKILL_ROOT) not in sys.path:
        sys.path.insert(0, str(SKILL_ROOT))
    loader = unittest.defaultTestLoader
    suite = (
        loader.loadTestsFromNames(args.tests)
        if args.tests
        else loader.discover(str(SKILL_ROOT / "tests"), pattern=args.pattern, top_level_dir=str(SKILL_ROOT))
    )
    started = time.perf_counter()
    stream = sys.stderr if args.json else sys.stdout
    result = unittest.TextTestRunner(
        stream=stream,
        verbosity=args.verbosity,
        failfast=args.failfast,
    ).run(suite)
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    skipped = len(result.skipped)
    failures = len(result.failures)
    errors = len(result.errors)
    expected_failures = len(result.expectedFailures)
    unexpected_successes = len(result.unexpectedSuccesses)
    passed = (
        result.testsRun
        - skipped
        - failures
        - errors
        - expected_failures
        - unexpected_successes
    )
    summary = {
        "schema": "discovery-call-test-summary/v1",
        "tests_run": result.testsRun,
        "passed": passed,
        "skipped": skipped,
        "failures": failures,
        "errors": errors,
        "expected_failures": expected_failures,
        "unexpected_successes": unexpected_successes,
        "duration_ms": duration_ms,
        "successful": result.wasSuccessful(),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "summary: "
            + ", ".join(f"{key}={value}" for key, value in summary.items() if key != "schema")
        )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
