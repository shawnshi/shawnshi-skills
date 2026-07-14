"""Deterministic, read-only aggregation for collaboration audit evidence.

The script accepts an explicit JSON or JSONL file, or a directory containing
those files. It never discovers private runtime folders and only writes when
``--output`` is provided by the caller.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def iter_records(path: Path) -> Iterable[dict[str, Any]]:
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
    for source in files:
        try:
            if source.suffix.lower() == ".jsonl":
                for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict):
                        yield item
                continue

            payload = json.loads(source.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, dict):
                records = payload.get("records")
                if isinstance(records, list):
                    for item in records:
                        if isinstance(item, dict):
                            yield item
                else:
                    yield payload
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        yield item
        except (OSError, json.JSONDecodeError):
            continue


def number(record: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0


def text_value(record: dict[str, Any], *keys: str, default: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def aggregate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "failures": 0, "durations": [], "input_tokens": 0, "output_tokens": 0}
    )
    failure_types: Counter[str] = Counter()
    total = 0

    for record in records:
        total += 1
        name = text_value(record, "skill_name", "skill", "tool", "agent", default="unknown")
        status = text_value(record, "status", "outcome", default="unknown").lower()
        duration = number(record, "duration_sec", "duration_seconds", "elapsed_sec")
        input_tokens = int(number(record, "input_tokens", "prompt_tokens"))
        output_tokens = int(number(record, "output_tokens", "completion_tokens"))

        group = groups[name]
        group["count"] += 1
        if duration >= 0:
            group["durations"].append(duration)
        group["input_tokens"] += input_tokens
        group["output_tokens"] += output_tokens

        failed = status in {"error", "failed", "failure", "blocked"} or bool(record.get("error"))
        if failed:
            group["failures"] += 1
            failure_types[text_value(record, "error_type", "failure_type", default="unspecified")] += 1

    by_component = []
    for name, group in groups.items():
        durations = group.pop("durations")
        count = group["count"]
        by_component.append(
            {
                "component": name,
                **group,
                "failure_rate": round(group["failures"] / count, 4) if count else 0,
                "duration_mean_sec": round(statistics.mean(durations), 3) if durations else None,
                "duration_p95_sec": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 3) if durations else None,
            }
        )

    by_component.sort(key=lambda item: (item["failures"], item["count"]), reverse=True)
    return {
        "record_count": total,
        "component_count": len(by_component),
        "failure_types": dict(failure_types.most_common()),
        "components": by_component,
        "limitations": [
            "Only fields present in the supplied records were aggregated.",
            "Missing durations or token counts are not inferred.",
            "Correlation in telemetry does not establish causation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate explicit JSON or JSONL evidence for a collaboration audit.")
    parser.add_argument("--input", required=True, help="Input JSON/JSONL file or directory.")
    parser.add_argument("--output", help="Optional JSON output path. Without it, the report is printed only.")
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    if not source.exists():
        parser.error(f"input does not exist: {source}")

    report = aggregate(iter_records(source))
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        print(target)
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
