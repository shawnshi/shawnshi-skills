"""Cold-process, offline broker replay; never launches an agent or public request."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

from hub_utils import atomic_dump_json

ROOT = Path(__file__).resolve().parent.parent
WORKLOAD = "scripts/test_article_broker_evidence.py::test_bound_before_query_retains_clock"
CHILD = r'''
import json, pytest, run_contract
counts = {"load_manifest": 0, "skill_bundle_sha256": 0}
for name in counts:
    original = getattr(run_contract, name)
    def wrapper(*args, _name=name, _original=original, **kwargs):
        counts[_name] += 1
        return _original(*args, **kwargs)
    setattr(run_contract, name, wrapper)
code = pytest.main(["-q", "-p", "no:cacheprovider", "test_article_broker_evidence.py::test_bound_before_query_retains_clock"])
print("BENCHMARK_COUNTERS=" + json.dumps(counts))
raise SystemExit(code)
'''


def measure(repeat: int) -> dict:
    samples = []
    for _ in range(repeat):
        with tempfile.TemporaryDirectory(prefix="pih-benchmark-") as directory:
            env = os.environ.copy()
            env.update(PIH_RUNTIME_DIR=str(Path(directory) / "runtime"),
                       PIH_NEWS_DIR=str(Path(directory) / "news"),
                       PYTHONDONTWRITEBYTECODE="1")
            start = time.perf_counter()
            result = subprocess.run(
                [sys.executable, "-B", "-X", "utf8", "-c", CHILD], cwd=ROOT / "scripts",
                env=env, capture_output=True, text=True, encoding="utf8", timeout=60,
            )
            elapsed = time.perf_counter() - start
            if result.returncode:
                raise RuntimeError(f"offline replay failed ({result.returncode}): {result.stdout[-4000:]} {result.stderr[-4000:]}")
            counters = next(line.removeprefix("BENCHMARK_COUNTERS=")
                            for line in result.stdout.splitlines() if line.startswith("BENCHMARK_COUNTERS="))
            samples.append({"wall_seconds": elapsed, **json.loads(counters)})
    return {
        "workload": WORKLOAD, "transport": "stubbed public HTTP; real contract gates",
        "cold_process": True, "concurrency": 1, "repeat": repeat,
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("pytest", "aiohttp", "jsonschema")},
        "recorded_at": datetime.now(timezone.utc).isoformat(), "samples": samples,
        "median_wall_seconds": statistics.median(sample["wall_seconds"] for sample in samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 5:
        parser.error("repeat must be between 1 and 5")
    payload = measure(args.repeat)
    atomic_dump_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
