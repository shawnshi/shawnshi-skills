"""Deterministic, read-only aggregation for collaboration audit events.

The CLI reads only the explicit JSON/JSONL input selected by the caller. It
never discovers private runtime folders and writes only when ``--output`` is
provided. Partial or malformed evidence is surfaced in ``coverage`` instead
of being silently discarded.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


WAIT_EVENTS = {"wait", "wait_agent"}
WRITE_EVENTS = {
    "delete",
    "merge",
    "persist",
    "publish",
    "send",
    "write_attempt",
    "write_commit",
}
WRITE_OPERATIONS = WRITE_EVENTS | {"create", "update", "write"}
FAILURE_STATUSES = {"blocked", "error", "failed", "failure"}


def _issue(source: Path, category: str, detail: str, line: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": str(source),
        "category": category,
        "detail": detail,
    }
    if line is not None:
        result["line"] = line
    return result


def _collect_objects(
    payload: Any,
    source: Path,
    records: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> None:
    if isinstance(payload, dict):
        nested = payload.get("records")
        if isinstance(nested, list):
            items = nested
        else:
            records.append(payload)
            return
    elif isinstance(payload, list):
        items = payload
    else:
        coverage["skipped_record_count"] += 1
        coverage["issues"].append(
            _issue(source, "unsupported_record", f"expected object or list, got {type(payload).__name__}")
        )
        return

    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            records.append(item)
        else:
            coverage["skipped_record_count"] += 1
            coverage["issues"].append(
                _issue(source, "unsupported_record", f"item {index} is {type(item).__name__}, expected object")
            )


def load_records(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load explicit evidence and return records plus loss/coverage metadata."""

    files = [path] if path.is_file() else sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
    records: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {
        "source_file_count": len(files),
        "parsed_file_count": 0,
        "skipped_file_count": 0,
        "skipped_record_count": 0,
        "issues": [],
    }

    if not files:
        coverage["issues"].append(_issue(path, "no_input_files", "no JSON or JSONL files found"))

    for source in files:
        try:
            text = source.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            coverage["skipped_file_count"] += 1
            coverage["issues"].append(_issue(source, "read_error", str(exc)))
            continue

        if source.suffix.lower() == ".jsonl":
            coverage["parsed_file_count"] += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    coverage["skipped_record_count"] += 1
                    coverage["issues"].append(
                        _issue(source, "invalid_json", f"column {exc.colno}: {exc.msg}", line_number)
                    )
                    continue
                if isinstance(item, dict):
                    records.append(item)
                else:
                    coverage["skipped_record_count"] += 1
                    coverage["issues"].append(
                        _issue(source, "unsupported_record", f"expected object, got {type(item).__name__}", line_number)
                    )
            continue

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            coverage["skipped_file_count"] += 1
            coverage["issues"].append(
                _issue(source, "invalid_json", f"line {exc.lineno}, column {exc.colno}: {exc.msg}")
            )
            continue

        coverage["parsed_file_count"] += 1
        _collect_objects(payload, source, records, coverage)

    coverage["record_count"] = len(records)
    if not records:
        coverage["status"] = "empty"
    elif coverage["issues"]:
        coverage["status"] = "partial"
    else:
        coverage["status"] = "complete"
    return records, coverage


def iter_records(path: Path) -> Iterable[dict[str, Any]]:
    """Compatibility iterator; callers needing auditability should use load_records."""

    records, _ = load_records(path)
    yield from records


def number(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def text_value(record: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def event_type(record: dict[str, Any]) -> str:
    return text_value(record, "event_type", "event", default="unknown").strip().lower()


def duration_seconds(record: dict[str, Any]) -> float | None:
    milliseconds = number(record, "duration_ms")
    if milliseconds is not None:
        return milliseconds / 1000.0
    return number(record, "duration_sec", "duration_seconds", "elapsed_sec")


def token_count(record: dict[str, Any]) -> int:
    input_tokens = number(record, "input_tokens", "prompt_tokens")
    output_tokens = number(record, "output_tokens", "completion_tokens")
    return int(input_tokens or 0) + int(output_tokens or 0)


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _wait_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    waits = [record for record in records if event_type(record) in WAIT_EVENTS]
    previous_wait: dict[tuple[str, str], tuple[str, bool]] = {}
    timeout_streaks: dict[tuple[str, str], tuple[str, int]] = {}
    redundant = 0
    state_observations = 0
    max_timeout_streak = 0
    wait_with_local_work = 0
    wait_with_local_work_duration = 0.0

    for record in waits:
        root_task = text_value(record, "root_task_id", default="unknown-root")
        actor = text_value(record, "actor_id", default="root")
        key = (root_task, actor)
        state = text_value(record, "state_version", "agent_state_version")
        timeout = text_value(record, "status", "outcome").lower() == "timeout"

        if state:
            state_observations += 1
            previous = previous_wait.get(key)
            if previous and previous[0] == state and previous[1]:
                redundant += 1
            previous_wait[key] = (state, timeout)

        if timeout and state:
            previous_state, previous_count = timeout_streaks.get(key, ("", 0))
            streak = previous_count + 1 if previous_state == state else 1
            timeout_streaks[key] = (state, streak)
            max_timeout_streak = max(max_timeout_streak, streak)
        else:
            timeout_streaks[key] = (state, 0)

        if record.get("local_work_available") is True:
            wait_with_local_work += 1
            wait_with_local_work_duration += duration_seconds(record) or 0.0

    timeout_count = sum(
        1 for record in waits if text_value(record, "status", "outcome").lower() == "timeout"
    )
    return {
        "wait_call_count": len(waits),
        "wait_call_share": ratio(len(waits), len(records)),
        "timeout_count": timeout_count,
        "state_observation_count": state_observations,
        "redundant_wait_count": redundant,
        "redundant_wait_rate": ratio(redundant, state_observations),
        "max_same_state_timeout_streak": max_timeout_streak,
        "wait_with_local_work_count": wait_with_local_work,
        "wait_with_local_work_duration_sec": round(wait_with_local_work_duration, 3),
        "unverifiable_wait_count": len(waits) - state_observations,
    }


def _skill_load_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    loads = [record for record in records if event_type(record) == "skill_load"]
    seen: set[tuple[str, str, str, str, str]] = set()
    duplicates = 0
    unverifiable = 0
    loaded_tokens = 0

    for record in loads:
        values = (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_sha256"),
        )
        observed_tokens = number(record, "skill_tokens", "loaded_tokens")
        loaded_tokens += int(observed_tokens or 0)
        if not all(values):
            unverifiable += 1
            continue
        if values in seen:
            duplicates += 1
        else:
            seen.add(values)

    return {
        "skill_load_count": len(loads),
        "duplicate_load_count": duplicates,
        "duplicate_load_rate": ratio(duplicates, len(loads)),
        "loaded_tokens": loaded_tokens,
        "unverifiable_load_count": unverifiable,
    }


def _retry_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    retries = [record for record in records if event_type(record) == "retry" or record.get("retry_of")]
    blind = 0
    signatures: Counter[tuple[str, str, str, str]] = Counter()
    connector_eof = 0
    eof_without_fallback = 0
    ambiguous_write_retries = 0

    for record in retries:
        category = text_value(record, "error_category", "error_type", "failure_type")
        signature = text_value(record, "error_signature")
        hypothesis = text_value(record, "hypothesis_delta", "changed_variable")
        if not category or not signature or not hypothesis:
            blind += 1

        if signature:
            signatures[
                (
                    text_value(record, "root_task_id"),
                    text_value(record, "component", "tool", "skill"),
                    text_value(record, "operation", "action"),
                    signature,
                )
            ] += 1

        if signature.lower() == "connector_eof":
            connector_eof += 1
            if not text_value(record, "fallback"):
                eof_without_fallback += 1
            operation = text_value(record, "operation", "action").lower()
            side_effect_state = text_value(record, "side_effect_state", default="unknown").lower()
            if operation in WRITE_OPERATIONS and side_effect_state in {"", "unknown"}:
                ambiguous_write_retries += 1

    repeated_beyond_first = sum(max(0, count - 1) for count in signatures.values())
    return {
        "retry_count": len(retries),
        "blind_retry_count": blind,
        "blind_retry_rate": ratio(blind, len(retries)),
        "same_signature_retries_beyond_first": repeated_beyond_first,
        "max_same_signature_attempts": max(signatures.values(), default=0),
        "connector_eof_count": connector_eof,
        "connector_eof_without_fallback_count": eof_without_fallback,
        "ambiguous_write_retry_count": ambiguous_write_retries,
    }


def _subagent_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    root_tokens = 0
    child_tokens = 0
    spawns = 0
    full_history_forks = 0
    minimal_packets = 0

    for record in records:
        kind = text_value(record, "actor_type").lower()
        is_child = kind == "subagent" or bool(record.get("parent_actor_id"))
        if is_child:
            child_tokens += token_count(record)
        else:
            root_tokens += token_count(record)

        if event_type(record) == "subagent_spawn":
            spawns += 1
            fork_turns = text_value(record, "fork_turns", default="all").lower()
            if fork_turns == "all":
                full_history_forks += 1
            required_packet_fields = ("evidence_pointers", "halt_condition", "output_schema", "max_turns")
            if all(record.get(field) not in (None, "", []) for field in required_packet_fields):
                minimal_packets += 1

    total_tokens = root_tokens + child_tokens
    return {
        "root_tokens": root_tokens,
        "child_tokens": child_tokens,
        "child_token_share": ratio(child_tokens, total_tokens),
        "child_to_root_token_ratio": ratio(child_tokens, root_tokens),
        "subagent_spawn_count": spawns,
        "full_history_fork_count": full_history_forks,
        "structured_packet_rate": ratio(minimal_packets, spawns),
    }


def _authorization_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    writes = [record for record in records if event_type(record) in WRITE_EVENTS]
    unmatched = 0
    for record in writes:
        authorization_id = text_value(record, "authorization_id")
        write_scope = text_value(record, "write_scope_sha256")
        authorization_scope = text_value(record, "authorization_scope_sha256")
        if not authorization_id or not write_scope or write_scope != authorization_scope:
            unmatched += 1

    readonly_approvals = sum(
        1
        for record in records
        if event_type(record) == "approval_request"
        and text_value(record, "task_mode").lower() in {"audit_only", "read_only"}
    )
    return {
        "write_event_count": len(writes),
        "unmatched_write_count": unmatched,
        "unmatched_write_rate": ratio(unmatched, len(writes)),
        "readonly_approval_rounds": readonly_approvals,
    }


def _context_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    root_tasks = {text_value(record, "root_task_id") for record in records if text_value(record, "root_task_id")}
    compactions = sum(1 for record in records if event_type(record) == "context_compacted")
    total_input_tokens = sum(int(number(record, "input_tokens", "prompt_tokens") or 0) for record in records)
    skill_tokens = sum(
        int(number(record, "skill_tokens", "loaded_tokens") or 0)
        for record in records
        if event_type(record) == "skill_load"
    )
    return {
        "root_task_count": len(root_tasks),
        "context_compaction_count": compactions,
        "compactions_per_10_root_tasks": round(compactions * 10 / len(root_tasks), 4) if root_tasks else None,
        "skill_input_token_share": ratio(skill_tokens, total_input_tokens),
    }


def _component_metrics(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "failures": 0,
            "durations": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "token_observation_count": 0,
        }
    )
    failure_types: Counter[str] = Counter()

    for record in records:
        name = text_value(record, "component", "skill_name", "skill", "tool", "agent", default="unknown")
        status = text_value(record, "status", "outcome", default="unknown").lower()
        duration = duration_seconds(record)
        input_tokens = number(record, "input_tokens", "prompt_tokens")
        output_tokens = number(record, "output_tokens", "completion_tokens")

        group = groups[name]
        group["count"] += 1
        if duration is not None and duration >= 0:
            group["durations"].append(duration)
        if input_tokens is not None or output_tokens is not None:
            group["token_observation_count"] += 1
        group["input_tokens"] += int(input_tokens or 0)
        group["output_tokens"] += int(output_tokens or 0)

        failed = status in FAILURE_STATUSES or bool(record.get("error"))
        if failed:
            group["failures"] += 1
            failure_types[text_value(record, "error_category", "error_type", "failure_type", default="unspecified")] += 1

    by_component: list[dict[str, Any]] = []
    for name, group in groups.items():
        durations = group.pop("durations")
        count = group["count"]
        p95 = nearest_rank(durations, 0.95)
        by_component.append(
            {
                "component": name,
                **group,
                "failure_rate": round(group["failures"] / count, 4) if count else 0,
                "duration_observation_count": len(durations),
                "duration_mean_sec": round(statistics.mean(durations), 3) if durations else None,
                "duration_p95_sec": round(p95, 3) if p95 is not None else None,
            }
        )

    by_component.sort(key=lambda item: (item["failures"], item["count"]), reverse=True)
    return by_component, dict(failure_types.most_common())


def aggregate(
    records: Iterable[dict[str, Any]],
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate component health and the five operational control metrics."""

    materialized = list(records)
    components, failure_types = _component_metrics(materialized)
    if coverage is None:
        coverage = {
            "status": "not_provided",
            "source_file_count": None,
            "parsed_file_count": None,
            "skipped_file_count": None,
            "skipped_record_count": None,
            "record_count": len(materialized),
            "issues": [],
        }

    return {
        "schema_version": 2,
        "coverage": coverage,
        "record_count": len(materialized),
        "component_count": len(components),
        "failure_types": failure_types,
        "components": components,
        "operational_metrics": {
            "wait": _wait_metrics(materialized),
            "skill_load": _skill_load_metrics(materialized),
            "retry": _retry_metrics(materialized),
            "subagent": _subagent_metrics(materialized),
            "authorization": _authorization_metrics(materialized),
            "context": _context_metrics(materialized),
        },
        "limitations": [
            "Only explicit fields in the supplied records were aggregated.",
            "Missing durations, token counts, state versions, and fingerprints are not inferred.",
            "Event-order metrics assume records are already in chronological order.",
            "Correlation in telemetry does not establish causation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate explicit collaboration audit JSON or JSONL events.")
    parser.add_argument("--input", required=True, help="Input JSON/JSONL file or directory.")
    parser.add_argument("--output", help="Optional JSON output path. Without it, the report is printed only.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 when any source file or record was skipped.",
    )
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    if not source.exists():
        parser.error(f"input does not exist: {source}")

    records, coverage = load_records(source)
    report = aggregate(records, coverage)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        print(target)
    else:
        print(serialized)

    if not records:
        return 1
    if args.strict and coverage["status"] != "complete":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
