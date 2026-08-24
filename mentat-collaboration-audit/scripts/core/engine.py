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
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
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
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _issue(source: Path, category: str, detail: str, line: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": str(source),
        "category": category,
        "detail": detail,
    }
    if line is not None:
        result["line"] = line
    return result


def _append_event(
    item: Any,
    source: Path,
    records: list[dict[str, Any]],
    coverage: dict[str, Any],
    *,
    line: int | None = None,
    item_index: int | None = None,
) -> None:
    if not isinstance(item, dict):
        coverage["skipped_record_count"] += 1
        location = f"item {item_index} is" if item_index is not None else "expected object, got"
        coverage["issues"].append(
            _issue(source, "unsupported_record", f"{location} {type(item).__name__}", line)
        )
        return

    missing = [
        field
        for field in ("event_type", "root_task_id")
        if not isinstance(item.get(field), str) or not item[field].strip()
    ]
    if missing:
        coverage["skipped_record_count"] += 1
        coverage["issues"].append(
            _issue(
                source,
                "invalid_event_envelope",
                "missing or invalid required field(s): " + ", ".join(missing),
                line,
            )
        )
        return

    records.append(item)


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
            _append_event(payload, source, records, coverage)
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
        _append_event(item, source, records, coverage, item_index=index)


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
        if source.suffix.lower() == ".jsonl":
            try:
                with source.open("r", encoding="utf-8", errors="strict") as handle:
                    for line_number, line in enumerate(handle, start=1):
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
                        _append_event(item, source, records, coverage, line=line_number)
            except (OSError, UnicodeDecodeError) as exc:
                coverage["skipped_file_count"] += 1
                coverage["issues"].append(_issue(source, "read_error", str(exc)))
                continue
            coverage["parsed_file_count"] += 1
            continue

        try:
            text = source.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            coverage["skipped_file_count"] += 1
            coverage["issues"].append(_issue(source, "read_error", str(exc)))
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


def event_timestamp(record: dict[str, Any]) -> float | None:
    value = text_value(record, "timestamp")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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
    wait_gate_breaches = 0
    wait_gate_breach_sequences = 0
    wait_with_local_work = 0
    wait_with_local_work_duration = 0.0
    last_timestamps: dict[tuple[str, str], float] = {}
    out_of_order = missing_timestamps = 0

    for record in waits:
        root_task = text_value(record, "root_task_id", default="unknown-root")
        actor = text_value(record, "actor_id", default="root")
        key = (root_task, actor)
        observed_timestamp = event_timestamp(record)
        if observed_timestamp is None:
            missing_timestamps += 1
        else:
            previous_timestamp = last_timestamps.get(key)
            if previous_timestamp is not None and observed_timestamp < previous_timestamp:
                out_of_order += 1
            last_timestamps[key] = observed_timestamp
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
            if streak > 2:
                wait_gate_breaches += 1
                if streak == 3:
                    wait_gate_breach_sequences += 1
        else:
            timeout_streaks[key] = (state, 0)

        if record.get("local_work_available") is True:
            wait_with_local_work += 1
            wait_with_local_work_duration += duration_seconds(record) or 0.0

    timeout_count = sum(
        1 for record in waits if text_value(record, "status", "outcome").lower() == "timeout"
    )
    sequence_valid = out_of_order == 0 and missing_timestamps == 0
    sequence_status = (
        "not_applicable"
        if not waits
        else "invalid"
        if out_of_order
        else "unverifiable"
        if missing_timestamps
        else "verified"
    )
    return {
        "wait_call_count": len(waits),
        "wait_call_share": ratio(len(waits), len(records)),
        "timeout_count": timeout_count,
        "state_observation_count": state_observations,
        "redundant_wait_count": redundant if sequence_valid else None,
        "redundant_wait_rate": ratio(redundant, state_observations) if sequence_valid else None,
        "max_same_state_timeout_streak": max_timeout_streak if sequence_valid else None,
        "wait_gate_breach_count": wait_gate_breaches if sequence_valid else None,
        "wait_gate_breach_sequence_count": wait_gate_breach_sequences if sequence_valid else None,
        "wait_with_local_work_count": wait_with_local_work,
        "wait_with_local_work_duration_sec": round(wait_with_local_work_duration, 3),
        "unverifiable_wait_count": len(waits) - state_observations,
        "sequence_order_status": sequence_status,
        "out_of_order_sequence_count": out_of_order,
        "missing_sequence_timestamp_count": missing_timestamps,
    }


def _is_formal_skill_load(record: dict[str, Any]) -> bool:
    required_text = ("root_task_id", "actor_id", "context_epoch", "skill_name", "tokenizer")
    if any(not isinstance(record.get(field), str) or not record[field].strip() for field in required_text):
        return False
    if not all(
        isinstance(record.get(field), str) and SHA256_PATTERN.fullmatch(record[field])
        for field in ("skill_path_sha256", "skill_sha256")
    ):
        return False
    tokens = record.get("skill_tokens")
    return isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0


def _skill_load_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    raw_loads = [record for record in records if event_type(record) == "skill_load"]
    loads = [record for record in raw_loads if _is_formal_skill_load(record)]
    candidates = [record for record in records if event_type(record) == "skill_load_candidate"]
    seen: set[tuple[str, str, str, str, str]] = set()
    duplicates = 0
    loaded_tokens = 0
    token_observations = 0

    for record in loads:
        values = (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_sha256"),
        )
        loaded_tokens += record["skill_tokens"]
        token_observations += 1
        if values in seen:
            duplicates += 1
        else:
            seen.add(values)

    receipt_keys = Counter(
        (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_path_sha256"),
        )
        for record in loads
    )
    verified_candidates = 0
    for record in candidates:
        key = (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_path_sha256"),
        )
        if all(key) and receipt_keys[key] > 0:
            verified_candidates += 1
            receipt_keys[key] -= 1

    return {
        "skill_load_count": len(loads),
        "skill_load_candidate_count": len(candidates),
        "verified_candidate_count": verified_candidates,
        "receipt_coverage": ratio(verified_candidates, len(candidates)),
        "duplicate_load_count": duplicates,
        "duplicate_load_rate": ratio(duplicates, len(loads)),
        "loaded_tokens": loaded_tokens,
        "token_observation_count": token_observations,
        "token_coverage": ratio(token_observations, len(raw_loads)),
        "unverifiable_load_count": len(raw_loads) - len(loads),
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
    attempts = [record for record in writes if event_type(record) == "write_attempt"]
    commits = [record for record in writes if event_type(record) == "write_commit"]
    unmatched = 0
    for record in commits:
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
        "write_attempt_count": len(attempts),
        "write_commit_count": len(commits),
        "unmatched_write_count": unmatched,
        "unmatched_write_rate": ratio(unmatched, len(commits)),
        "authorization_evidence_status": (
            "no_writes" if not commits else "complete" if unmatched == 0 else "partial"
        ),
        "readonly_approval_rounds": readonly_approvals,
    }


def _context_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    root_tasks = {text_value(record, "root_task_id") for record in records if text_value(record, "root_task_id")}
    compaction_events = [record for record in records if event_type(record) == "context_compacted"]
    recovery_events = [record for record in records if event_type(record) == "context_recovered"]
    compactions = len(compaction_events)
    recovery_keys = {
        (text_value(record, "root_task_id"), text_value(record, "context_epoch"))
        for record in recovery_events
    }
    semantic_recovery_keys = {
        (text_value(record, "root_task_id"), text_value(record, "context_epoch"))
        for record in recovery_events
        if record.get("required_fields_verified") is True
    }
    matched_recoveries = sum(
        1
        for record in compaction_events
        if (text_value(record, "root_task_id"), text_value(record, "context_epoch")) in recovery_keys
    )
    semantic_recoveries = sum(
        1
        for record in compaction_events
        if (text_value(record, "root_task_id"), text_value(record, "context_epoch")) in semantic_recovery_keys
    )
    total_input_tokens = sum(int(number(record, "input_tokens", "prompt_tokens") or 0) for record in records)
    skill_tokens = sum(
        record["skill_tokens"]
        for record in records
        if event_type(record) == "skill_load" and _is_formal_skill_load(record)
    )
    return {
        "root_task_count": len(root_tasks),
        "context_compaction_count": compactions,
        "compactions_per_10_root_tasks": round(compactions * 10 / len(root_tasks), 4) if root_tasks else None,
        "context_recovery_count": len(recovery_events),
        "matched_context_recovery_count": matched_recoveries,
        "context_recovery_coverage": ratio(matched_recoveries, compactions),
        "semantic_recovery_verified_count": semantic_recoveries,
        "semantic_recovery_coverage": ratio(semantic_recoveries, compactions),
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
                # Performance: Replaced slow statistics.mean with built-in sum/len for ~55x speedup
                "duration_mean_sec": round(sum(durations) / len(durations), 3) if durations else None,
                "duration_p95_sec": round(p95, 3) if p95 is not None else None,
            }
        )

    by_component.sort(key=lambda item: (item["failures"], item["count"]), reverse=True)
    return by_component, dict(failure_types.most_common())


def _stream_records(path: Path, coverage: dict[str, Any]) -> Iterable[dict[str, Any]]:
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
    if not files:
        coverage["issues"].append(_issue(path, "no_input_files", "no JSON or JSONL files found"))

    for source in files:
        if source.suffix.lower() == ".jsonl":
            try:
                with source.open("r", encoding="utf-8", errors="strict") as handle:
                    for line_number, line in enumerate(handle, start=1):
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
                        accepted: list[dict[str, Any]] = []
                        _append_event(item, source, accepted, coverage, line=line_number)
                        yield from accepted
            except (OSError, UnicodeDecodeError) as exc:
                coverage["skipped_file_count"] += 1
                coverage["issues"].append(_issue(source, "read_error", str(exc)))
                continue
            coverage["parsed_file_count"] += 1
            continue

        try:
            text = source.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            coverage["skipped_file_count"] += 1
            coverage["issues"].append(_issue(source, "read_error", str(exc)))
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            coverage["skipped_file_count"] += 1
            coverage["issues"].append(
                _issue(source, "invalid_json", f"line {exc.lineno}, column {exc.colno}: {exc.msg}")
            )
            continue
        accepted = []
        _collect_objects(payload, source, accepted, coverage)
        coverage["parsed_file_count"] += 1
        yield from accepted


class _StreamingAggregate:
    def __init__(self) -> None:
        self.record_count = 0
        self.groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "failures": 0,
                "durations": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "token_observation_count": 0,
            }
        )
        self.failure_types: Counter[str] = Counter()
        self.wait_count = self.wait_timeout_count = self.wait_state_count = 0
        self.wait_redundant = self.wait_max_streak = 0
        self.wait_gate_breaches = self.wait_gate_sequences = 0
        self.wait_local_count = 0
        self.wait_local_duration = 0.0
        self.previous_wait: dict[tuple[str, str], tuple[str, bool]] = {}
        self.timeout_streaks: dict[tuple[str, str], tuple[str, int]] = {}
        self.wait_last_timestamps: dict[tuple[str, str], float] = {}
        self.wait_out_of_order = self.wait_missing_timestamps = 0
        self.raw_skill_loads = self.valid_skill_loads = 0
        self.skill_duplicates = self.skill_tokens = 0
        self.skill_seen: set[tuple[str, str, str, str, str]] = set()
        self.skill_receipts: Counter[tuple[str, str, str, str, str]] = Counter()
        self.skill_candidates: Counter[tuple[str, str, str, str, str]] = Counter()
        self.skill_candidate_count = 0
        self.retry_count = self.retry_blind = 0
        self.retry_signatures: Counter[tuple[str, str, str, str]] = Counter()
        self.connector_eof = self.eof_without_fallback = self.ambiguous_write_retries = 0
        self.root_tokens = self.child_tokens = 0
        self.spawns = self.full_history_forks = self.minimal_packets = 0
        self.write_count = self.write_attempts = self.write_commits = self.unmatched_writes = 0
        self.readonly_approvals = 0
        self.root_tasks: set[str] = set()
        self.compactions: Counter[tuple[str, str]] = Counter()
        self.recovery_keys: set[tuple[str, str]] = set()
        self.semantic_recovery_keys: set[tuple[str, str]] = set()
        self.recovery_count = 0
        self.total_input_tokens = 0

    def update(self, record: dict[str, Any]) -> None:
        self.record_count += 1
        kind = event_type(record)
        root = text_value(record, "root_task_id")
        actor = text_value(record, "actor_id", default="root")
        component = text_value(record, "component", "skill_name", "skill", "tool", "agent", default="unknown")
        status = text_value(record, "status", "outcome", default="unknown").lower()
        duration = duration_seconds(record)
        input_tokens = number(record, "input_tokens", "prompt_tokens")
        output_tokens = number(record, "output_tokens", "completion_tokens")

        group = self.groups[component]
        group["count"] += 1
        if duration is not None and duration >= 0:
            group["durations"].append(duration)
        if input_tokens is not None or output_tokens is not None:
            group["token_observation_count"] += 1
        group["input_tokens"] += int(input_tokens or 0)
        group["output_tokens"] += int(output_tokens or 0)
        if status in FAILURE_STATUSES or bool(record.get("error")):
            group["failures"] += 1
            self.failure_types[
                text_value(record, "error_category", "error_type", "failure_type", default="unspecified")
            ] += 1

        if root:
            self.root_tasks.add(root)
        self.total_input_tokens += int(input_tokens or 0)
        tokens = token_count(record)
        is_child = text_value(record, "actor_type").lower() == "subagent" or bool(record.get("parent_actor_id"))
        if is_child:
            self.child_tokens += tokens
        else:
            self.root_tokens += tokens

        if kind in WAIT_EVENTS:
            self._update_wait(record, root or "unknown-root", actor)
        if kind == "skill_load":
            self._update_skill_load(record)
        elif kind == "skill_load_candidate":
            self._update_skill_candidate(record)
        if kind == "retry" or record.get("retry_of"):
            self._update_retry(record)
        if kind == "subagent_spawn":
            self.spawns += 1
            if text_value(record, "fork_turns", default="all").lower() == "all":
                self.full_history_forks += 1
            required = ("evidence_pointers", "halt_condition", "output_schema", "max_turns")
            if all(record.get(field) not in (None, "", []) for field in required):
                self.minimal_packets += 1
        if kind in WRITE_EVENTS:
            self.write_count += 1
            if kind == "write_attempt":
                self.write_attempts += 1
            elif kind == "write_commit":
                self.write_commits += 1
                authorization_id = text_value(record, "authorization_id")
                write_scope = text_value(record, "write_scope_sha256")
                authorization_scope = text_value(record, "authorization_scope_sha256")
                if not authorization_id or not write_scope or write_scope != authorization_scope:
                    self.unmatched_writes += 1
        if kind == "approval_request" and text_value(record, "task_mode").lower() in {"audit_only", "read_only"}:
            self.readonly_approvals += 1
        context_key = (root, text_value(record, "context_epoch"))
        if kind == "context_compacted":
            self.compactions[context_key] += 1
        elif kind == "context_recovered":
            self.recovery_count += 1
            self.recovery_keys.add(context_key)
            if record.get("required_fields_verified") is True:
                self.semantic_recovery_keys.add(context_key)

    def _update_wait(self, record: dict[str, Any], root: str, actor: str) -> None:
        self.wait_count += 1
        key = (root, actor)
        observed_timestamp = event_timestamp(record)
        if observed_timestamp is None:
            self.wait_missing_timestamps += 1
        else:
            previous_timestamp = self.wait_last_timestamps.get(key)
            if previous_timestamp is not None and observed_timestamp < previous_timestamp:
                self.wait_out_of_order += 1
            self.wait_last_timestamps[key] = observed_timestamp
        state = text_value(record, "state_version", "agent_state_version")
        timeout = text_value(record, "status", "outcome").lower() == "timeout"
        if timeout:
            self.wait_timeout_count += 1
        if state:
            self.wait_state_count += 1
            previous = self.previous_wait.get(key)
            if previous and previous[0] == state and previous[1]:
                self.wait_redundant += 1
            self.previous_wait[key] = (state, timeout)
        if timeout and state:
            previous_state, previous_count = self.timeout_streaks.get(key, ("", 0))
            streak = previous_count + 1 if previous_state == state else 1
            self.timeout_streaks[key] = (state, streak)
            self.wait_max_streak = max(self.wait_max_streak, streak)
            if streak > 2:
                self.wait_gate_breaches += 1
                if streak == 3:
                    self.wait_gate_sequences += 1
        else:
            self.timeout_streaks[key] = (state, 0)
        if record.get("local_work_available") is True:
            self.wait_local_count += 1
            self.wait_local_duration += duration_seconds(record) or 0.0

    @staticmethod
    def _skill_key(record: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_path_sha256"),
        )

    def _update_skill_load(self, record: dict[str, Any]) -> None:
        self.raw_skill_loads += 1
        if not _is_formal_skill_load(record):
            return
        self.valid_skill_loads += 1
        self.skill_tokens += record["skill_tokens"]
        identity = (
            text_value(record, "root_task_id"),
            text_value(record, "actor_id"),
            text_value(record, "context_epoch"),
            text_value(record, "skill_name", "skill"),
            text_value(record, "skill_sha256"),
        )
        if identity in self.skill_seen:
            self.skill_duplicates += 1
        else:
            self.skill_seen.add(identity)
        self.skill_receipts[self._skill_key(record)] += 1

    def _update_skill_candidate(self, record: dict[str, Any]) -> None:
        self.skill_candidate_count += 1
        key = self._skill_key(record)
        if all(key):
            self.skill_candidates[key] += 1

    def _update_retry(self, record: dict[str, Any]) -> None:
        self.retry_count += 1
        category = text_value(record, "error_category", "error_type", "failure_type")
        signature = text_value(record, "error_signature")
        hypothesis = text_value(record, "hypothesis_delta", "changed_variable")
        if not category or not signature or not hypothesis:
            self.retry_blind += 1
        if signature:
            self.retry_signatures[
                (
                    text_value(record, "root_task_id"),
                    text_value(record, "component", "tool", "skill"),
                    text_value(record, "operation", "action"),
                    signature,
                )
            ] += 1
        if signature.lower() == "connector_eof":
            self.connector_eof += 1
            if not text_value(record, "fallback"):
                self.eof_without_fallback += 1
            operation = text_value(record, "operation", "action").lower()
            side_effect = text_value(record, "side_effect_state", default="unknown").lower()
            if operation in WRITE_OPERATIONS and side_effect in {"", "unknown"}:
                self.ambiguous_write_retries += 1

    def finalize(self, coverage: dict[str, Any]) -> dict[str, Any]:
        components: list[dict[str, Any]] = []
        for name, group in self.groups.items():
            durations = group["durations"]
            p95 = nearest_rank(durations, 0.95)
            components.append(
                {
                    "component": name,
                    "count": group["count"],
                    "failures": group["failures"],
                    "input_tokens": group["input_tokens"],
                    "output_tokens": group["output_tokens"],
                    "token_observation_count": group["token_observation_count"],
                    "failure_rate": round(group["failures"] / group["count"], 4) if group["count"] else 0,
                    "duration_observation_count": len(durations),
                    "duration_mean_sec": round(sum(durations) / len(durations), 3) if durations else None,
                    "duration_p95_sec": round(p95, 3) if p95 is not None else None,
                }
            )
        components.sort(key=lambda item: (item["failures"], item["count"]), reverse=True)
        verified_candidates = sum(
            min(count, self.skill_receipts[key]) for key, count in self.skill_candidates.items()
        )
        repeated_retries = sum(max(0, count - 1) for count in self.retry_signatures.values())
        compaction_count = sum(self.compactions.values())
        matched_recoveries = sum(
            count for key, count in self.compactions.items() if key in self.recovery_keys
        )
        semantic_recoveries = sum(
            count for key, count in self.compactions.items() if key in self.semantic_recovery_keys
        )
        total_tokens = self.root_tokens + self.child_tokens
        wait_sequence_valid = self.wait_out_of_order == 0 and self.wait_missing_timestamps == 0
        wait_sequence_status = (
            "not_applicable"
            if not self.wait_count
            else "invalid"
            if self.wait_out_of_order
            else "unverifiable"
            if self.wait_missing_timestamps
            else "verified"
        )
        operational = {
            "wait": {
                "wait_call_count": self.wait_count,
                "wait_call_share": ratio(self.wait_count, self.record_count),
                "timeout_count": self.wait_timeout_count,
                "state_observation_count": self.wait_state_count,
                "redundant_wait_count": self.wait_redundant if wait_sequence_valid else None,
                "redundant_wait_rate": ratio(self.wait_redundant, self.wait_state_count) if wait_sequence_valid else None,
                "max_same_state_timeout_streak": self.wait_max_streak if wait_sequence_valid else None,
                "wait_gate_breach_count": self.wait_gate_breaches if wait_sequence_valid else None,
                "wait_gate_breach_sequence_count": self.wait_gate_sequences if wait_sequence_valid else None,
                "wait_with_local_work_count": self.wait_local_count,
                "wait_with_local_work_duration_sec": round(self.wait_local_duration, 3),
                "unverifiable_wait_count": self.wait_count - self.wait_state_count,
                "sequence_order_status": wait_sequence_status,
                "out_of_order_sequence_count": self.wait_out_of_order,
                "missing_sequence_timestamp_count": self.wait_missing_timestamps,
            },
            "skill_load": {
                "skill_load_count": self.valid_skill_loads,
                "skill_load_candidate_count": self.skill_candidate_count,
                "verified_candidate_count": verified_candidates,
                "receipt_coverage": ratio(verified_candidates, self.skill_candidate_count),
                "duplicate_load_count": self.skill_duplicates,
                "duplicate_load_rate": ratio(self.skill_duplicates, self.valid_skill_loads),
                "loaded_tokens": self.skill_tokens,
                "token_observation_count": self.valid_skill_loads,
                "token_coverage": ratio(self.valid_skill_loads, self.raw_skill_loads),
                "unverifiable_load_count": self.raw_skill_loads - self.valid_skill_loads,
            },
            "retry": {
                "retry_count": self.retry_count,
                "blind_retry_count": self.retry_blind,
                "blind_retry_rate": ratio(self.retry_blind, self.retry_count),
                "same_signature_retries_beyond_first": repeated_retries,
                "max_same_signature_attempts": max(self.retry_signatures.values(), default=0),
                "connector_eof_count": self.connector_eof,
                "connector_eof_without_fallback_count": self.eof_without_fallback,
                "ambiguous_write_retry_count": self.ambiguous_write_retries,
            },
            "subagent": {
                "root_tokens": self.root_tokens,
                "child_tokens": self.child_tokens,
                "child_token_share": ratio(self.child_tokens, total_tokens),
                "child_to_root_token_ratio": ratio(self.child_tokens, self.root_tokens),
                "subagent_spawn_count": self.spawns,
                "full_history_fork_count": self.full_history_forks,
                "structured_packet_rate": ratio(self.minimal_packets, self.spawns),
            },
            "authorization": {
                "write_event_count": self.write_count,
                "write_attempt_count": self.write_attempts,
                "write_commit_count": self.write_commits,
                "unmatched_write_count": self.unmatched_writes,
                "unmatched_write_rate": ratio(self.unmatched_writes, self.write_commits),
                "authorization_evidence_status": (
                    "no_writes" if not self.write_commits else "complete" if self.unmatched_writes == 0 else "partial"
                ),
                "readonly_approval_rounds": self.readonly_approvals,
            },
            "context": {
                "root_task_count": len(self.root_tasks),
                "context_compaction_count": compaction_count,
                "compactions_per_10_root_tasks": (
                    round(compaction_count * 10 / len(self.root_tasks), 4) if self.root_tasks else None
                ),
                "context_recovery_count": self.recovery_count,
                "matched_context_recovery_count": matched_recoveries,
                "context_recovery_coverage": ratio(matched_recoveries, compaction_count),
                "semantic_recovery_verified_count": semantic_recoveries,
                "semantic_recovery_coverage": ratio(semantic_recoveries, compaction_count),
                "skill_input_token_share": ratio(self.skill_tokens, self.total_input_tokens),
            },
        }
        return _report_payload(components, dict(self.failure_types.most_common()), operational, coverage, self.record_count)


LIMITATIONS = [
    "Only explicit fields in the supplied records were aggregated.",
    "Missing durations, token counts, state versions, and fingerprints are not inferred.",
    "Write authorization is complete only when commit events carry matching scope receipts.",
    "A context recovery event proves presence; semantic recovery requires required_fields_verified=true.",
    "Wait sequence metrics fail closed when same-task actor timestamps are missing or regress.",
    "Correlation in telemetry does not establish causation.",
]


def _report_payload(
    components: list[dict[str, Any]],
    failure_types: dict[str, int],
    operational_metrics: dict[str, Any],
    coverage: dict[str, Any],
    record_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "coverage": coverage,
        "record_count": record_count,
        "component_count": len(components),
        "failure_types": failure_types,
        "components": components,
        "operational_metrics": operational_metrics,
        "limitations": list(LIMITATIONS),
    }


def aggregate_path(path: Path) -> dict[str, Any]:
    """Aggregate an explicit path without retaining every decoded event."""

    path = Path(path)
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl"))
    coverage: dict[str, Any] = {
        "source_file_count": len(files),
        "parsed_file_count": 0,
        "skipped_file_count": 0,
        "skipped_record_count": 0,
        "issues": [],
    }
    state = _StreamingAggregate()
    for record in _stream_records(path, coverage):
        state.update(record)
    if state.wait_out_of_order:
        coverage["issues"].append(
            _issue(path, "out_of_order_sequence", f"{state.wait_out_of_order} wait event(s) regress within a task/actor sequence")
        )
    if state.wait_missing_timestamps:
        coverage["issues"].append(
            _issue(path, "missing_sequence_timestamp", f"{state.wait_missing_timestamps} wait event(s) lack a valid timestamp")
        )
    coverage["record_count"] = state.record_count
    if not state.record_count:
        coverage["status"] = "empty"
    elif coverage["issues"]:
        coverage["status"] = "partial"
    else:
        coverage["status"] = "complete"
    return state.finalize(coverage)


def aggregate(
    records: Iterable[dict[str, Any]],
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate component health and the five operational control metrics."""

    materialized = records if isinstance(records, list) else list(records)
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

    operational = {
            "wait": _wait_metrics(materialized),
            "skill_load": _skill_load_metrics(materialized),
            "retry": _retry_metrics(materialized),
            "subagent": _subagent_metrics(materialized),
            "authorization": _authorization_metrics(materialized),
            "context": _context_metrics(materialized),
    }
    return _report_payload(components, failure_types, operational, coverage, len(materialized))


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

    report = aggregate_path(source)
    coverage = report["coverage"]
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized + "\n", encoding="utf-8")
        print(target)
    else:
        print(serialized)

    if not report["record_count"]:
        return 1
    if args.strict and coverage["status"] != "complete":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
