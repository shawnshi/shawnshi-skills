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
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collaboration_analysis import CollaborationAnalysis

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
AUTHORIZATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
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
    if (any(field in record and record[field] not in ("ok", "success", "completed")
            for field in ("status", "outcome"))
            or ("token_measurement_status" in record and record["token_measurement_status"] != "ok")):
        return False
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


def _nonempty_string(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    return value if isinstance(value, str) and value.strip() else ""


def _invalid_candidate_binding(record: dict[str, Any]) -> bool:
    return (event_type(record) == "skill_load" and "candidate_event_id" in record
            and not _nonempty_string(record, "candidate_event_id"))


def _occurrence_id(record: dict[str, Any]) -> str:
    # Old receipts also carried event_id, but derived it from the business key.
    return _nonempty_string(record, "event_id") if record.get("event_identity") == "occurrence" else ""


def _skill_pair_key(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(_nonempty_string(record, field) for field in (
        "root_task_id", "actor_id", "context_epoch", "skill_name", "skill_path_sha256",
    ))


def _token_scope_key(record: dict[str, Any]) -> tuple[str, ...]:
    values = tuple(_nonempty_string(record, field) for field in (
        "root_task_id", "actor_id", "token_scope_id", "tokenizer", "token_measurement_basis",
    ))
    return tuple("" if value.strip().lower() in {"unknown", "unverified"} else value for value in values)


class _SkillLoadState:
    """Count deliveries separately from occurrences; retain only keys and counters."""

    def __init__(self) -> None:
        self.deliveries: dict[tuple[str, ...], str] = {}
        self.replays = self.conflicts = 0
        self.conflicted_deliveries: set[tuple[str, ...]] = set()
        self.raw_loads = self.loads = self.unverified_occurrences = self.duplicates = 0
        self.candidate_count = self.invalid_candidate_bindings = 0
        self.seen: Counter[tuple[str, ...]] = Counter()
        self.tokens: Counter[str] = Counter()
        self.tokenizer_loads: Counter[str] = Counter()
        self.scoped_tokens: Counter[tuple[str, ...]] = Counter()
        self.receipts: Counter[tuple[str, ...]] = Counter()
        self.linked_receipts: Counter[tuple[str, ...]] = Counter()
        self.candidates: Counter[tuple[str, ...]] = Counter()
        self.identified_candidates: Counter[tuple[str, ...]] = Counter()

    def update(self, record: dict[str, Any]) -> None:
        kind = event_type(record)
        occurrence = _occurrence_id(record)
        pair_key = _skill_pair_key(record)
        self.invalid_candidate_bindings += int(_invalid_candidate_binding(record))
        if occurrence:
            delivery_key = (pair_key[0], pair_key[1], kind, occurrence)
            fields = ("context_epoch", "skill_name", "skill_path_sha256", "skill_sha256",
                      "skill_tokens", "tokenizer", "candidate_event_id",
                      "token_measurement_basis", "token_scope_id", "status", "outcome",
                      "token_measurement_status", "token_measurement_error_type")
            fingerprint = json.dumps({field: record[field] for field in fields if field in record}, sort_keys=True)
            if delivery_key in self.deliveries:
                if self.deliveries[delivery_key] != fingerprint:
                    self.conflicts += 1
                    if delivery_key not in self.conflicted_deliveries:
                        # Retract the first payload as well: neither version proves an occurrence.
                        previous = json.loads(self.deliveries[delivery_key])
                        previous.update(root_task_id=pair_key[0], actor_id=pair_key[1],
                                        event_type=kind, event_id=occurrence, event_identity="occurrence")
                        self._apply(previous, -1)
                        if kind == "skill_load":
                            self.raw_loads += 1
                        else:
                            self.candidate_count += 1
                        self.conflicted_deliveries.add(delivery_key)
                else:
                    self.replays += 1
                return
            self.deliveries[delivery_key] = fingerprint
        self._apply(record, 1)

    def _apply(self, record: dict[str, Any], delta: int) -> None:
        kind = event_type(record)
        occurrence = _occurrence_id(record)
        pair_key = _skill_pair_key(record)
        if kind == "skill_load_candidate":
            self.candidate_count += delta
            if all(pair_key):
                self.candidates[pair_key] += delta
                if occurrence:
                    self.identified_candidates[(*pair_key, occurrence)] += delta
            return
        self.raw_loads += delta
        if not _is_formal_skill_load(record):
            return
        self.loads += delta
        self.tokens[record["tokenizer"]] += delta * record["skill_tokens"]
        self.tokenizer_loads[record["tokenizer"]] += delta
        if not self.tokenizer_loads[record["tokenizer"]]:
            del self.tokens[record["tokenizer"]]
        scope = _token_scope_key(record)
        self.scoped_tokens[scope] += delta * record["skill_tokens"]
        if occurrence:
            business_key = (*pair_key[:4], record["skill_sha256"])
            before = self.seen[business_key]
            self.seen[business_key] += delta
            self.duplicates += max(0, before + delta - 1) - max(0, before - 1)
        else:
            self.unverified_occurrences += delta
        candidate_id = _nonempty_string(record, "candidate_event_id")
        if candidate_id:
            if occurrence:
                self.linked_receipts[(*pair_key, candidate_id)] += delta
        elif "candidate_event_id" not in record:
            self.receipts[pair_key] += delta

    def metrics(self) -> dict[str, Any]:
        exact_by_key: Counter[tuple[str, ...]] = Counter()
        for key, count in self.identified_candidates.items():
            exact_by_key[key[:-1]] += min(count, self.linked_receipts[key])
        exact = sum(exact_by_key.values())
        matched = exact + sum(min(count - exact_by_key[key], self.receipts[key])
                              for key, count in self.candidates.items())
        complete = not (self.unverified_occurrences or self.conflicts or self.raw_loads != self.loads)
        return {
            "skill_load_count": self.loads,
            "skill_load_candidate_count": self.candidate_count,
            "verified_candidate_count": matched if not self.conflicts else None,
            "receipt_coverage": ratio(matched, self.candidate_count) if not self.conflicts else None,
            "occurrence_matched_candidate_count": exact if not self.conflicts else None,
            "occurrence_receipt_coverage": ratio(exact, self.candidate_count) if not self.conflicts else None,
            "receipt_pairing_basis": "business_key_upper_bound" if matched != exact else "occurrence",
            "duplicate_load_count": self.duplicates if complete else None,
            "duplicate_load_rate": ratio(self.duplicates, self.loads) if complete else None,
            "observed_duplicate_load_count": self.duplicates,
            "occurrence_load_count": self.loads - self.unverified_occurrences,
            "unverified_occurrence_count": self.unverified_occurrences,
            "occurrence_identity_coverage": ratio(self.loads - self.unverified_occurrences, self.raw_loads),
            "event_replay_count": self.replays,
            "event_identity_conflict_count": self.conflicts,
            "loaded_tokens": sum(self.tokens.values()) if len(self.tokens) <= 1 and not self.conflicts else None,
            "loaded_tokens_by_tokenizer": dict(sorted(self.tokens.items())),
            "token_observation_count": self.loads,
            "token_coverage": ratio(self.loads, self.raw_loads),
            "unverifiable_load_count": self.raw_loads - self.loads,
        }


class _TokenShareState:
    def __init__(self) -> None:
        self.observations = self.invalid = self.conflicts = 0
        self.scopes: Counter[tuple[str, ...]] = Counter()
        self.tokens: Counter[tuple[str, ...]] = Counter()
        self.deliveries: dict[tuple[str, ...], str] = {}

    def update(self, record: dict[str, Any]) -> None:
        if ("input_tokens" not in record and "prompt_tokens" not in record
                and event_type(record) not in {"usage", "token_usage"}
                and "skill_tokens_included" not in record):
            return
        occurrence = _occurrence_id(record)
        if occurrence:
            delivery_key = (_nonempty_string(record, "root_task_id"),
                            _nonempty_string(record, "actor_id"), event_type(record), occurrence)
            fields = ("input_tokens", "prompt_tokens", "token_scope_id", "tokenizer",
                      "token_measurement_basis", "skill_tokens_included", "skill_load_coverage_complete",
                      "token_measurement_status", "token_measurement_error_type")
            fingerprint = json.dumps({field: record[field] for field in fields if field in record}, sort_keys=True)
            if delivery_key in self.deliveries:
                if self.deliveries[delivery_key] != fingerprint:
                    self.invalid += 1
                    self.conflicts += 1
                return
            self.deliveries[delivery_key] = fingerprint
        self.observations += 1
        value = record.get("input_tokens", record.get("prompt_tokens"))
        key = _token_scope_key(record)
        if (not isinstance(value, int) or isinstance(value, bool) or value < 0
                or ("token_measurement_status" in record and record["token_measurement_status"] != "ok")
                or not all(key) or key[-1] != "model_input"
                or record.get("skill_tokens_included") is not True
                or record.get("skill_load_coverage_complete") is not True
                or ("input_tokens" in record and "prompt_tokens" in record
                    and record["input_tokens"] != record["prompt_tokens"])):
            self.invalid += 1
            return
        self.scopes[key] += 1
        self.tokens[key] += value

    def metrics(self, skills: _SkillLoadState, coverage: dict[str, Any]) -> dict[str, Any]:
        reason = "compatible"
        matching = sum(1 for key in self.scopes if key in skills.scoped_tokens)
        if coverage.get("status") != "complete":
            reason = "source_coverage_unverified"
        elif skills.conflicts or skills.unverified_occurrences or skills.raw_loads != skills.loads:
            reason = "skill_occurrence_evidence_incomplete"
        elif not skills.loads or not self.observations:
            reason = "missing_skill_or_input_measurement"
        elif self.invalid:
            reason = "input_measurement_metadata_incomplete"
        elif any(not all(key) or key[-1] != "model_input" for key in skills.scoped_tokens):
            reason = "skill_measurement_basis_incompatible"
        elif set(self.scopes) != set(skills.scoped_tokens):
            reason = "tokenizer_basis_or_scope_mismatch"
        elif len({key[-2:] for key in self.scopes}) != 1:
            reason = "mixed_tokenizers_or_bases"
        elif any(count != 1 for count in self.scopes.values()):
            reason = "multiple_input_measurements_per_scope"
        elif any(skills.scoped_tokens[key] > self.tokens[key] for key in self.scopes):
            reason = "skill_tokens_exceed_input_scope"
        elif not sum(self.tokens.values()):
            reason = "zero_input_tokens"
        compatible = reason == "compatible"
        return {
            "skill_input_token_share": ratio(sum(skills.tokens.values()), sum(self.tokens.values())) if compatible else None,
            "skill_input_token_share_reason": reason,
            "skill_input_token_share_numerator": sum(skills.tokens.values()) if compatible else None,
            "skill_input_token_share_denominator": sum(self.tokens.values()) if compatible else None,
            "skill_input_token_share_coverage": ratio(matching if compatible else 0, self.observations),
            "input_measurement_observation_count": self.observations,
            "compatible_scope_count": matching if compatible else 0,
        }


def _retry_classification(record: dict[str, Any]) -> str:
    fields = ("error_category", "error_type", "failure_type", "error_signature",
              "hypothesis_delta", "changed_variable", "retry_evidence")
    categories = {_nonempty_string(record, field).strip().lower()
                  for field in ("error_category", "error_type", "failure_type")
                  if _nonempty_string(record, field)}
    if len(categories) > 1:
        return "conflicting"
    category = _nonempty_string(record, "error_category") or _nonempty_string(record, "error_type") or _nonempty_string(record, "failure_type")
    signature = _nonempty_string(record, "error_signature")
    hypothesis = _nonempty_string(record, "hypothesis_delta") or _nonempty_string(record, "changed_variable")
    changed = record.get("hypothesis_changed")
    if changed is False and hypothesis:
        return "conflicting"
    if any(field in record and record[field] is not None and not isinstance(record[field], str)
           for field in fields):
        return "unverified"
    if "hypothesis_changed" in record and not isinstance(changed, bool):
        return "unverified"
    if not category or category.strip().lower() == "unknown" or not signature:
        return "unverified"
    if changed is False and _nonempty_string(record, "retry_evidence"):
        return "blind"
    if hypothesis:
        return "rationale_recorded"
    return "unverified"


def _retry_evidence_metrics(classifications: Counter[str], count: int) -> dict[str, Any]:
    classified = classifications["blind"] + classifications["rationale_recorded"]
    return {
        "blind_retry_count": classifications["blind"],
        "blind_retry_rate": ratio(classifications["blind"], classified),
        "rationale_recorded_retry_count": classifications["rationale_recorded"],
        "unverified_retry_count": count - classified,
        "conflicting_retry_evidence_count": classifications["conflicting"],
        "retry_classification_coverage": ratio(classified, count),
    }


class _AuthorizationState:
    def __init__(self) -> None:
        self.writes = self.attempts = self.commits = self.unmatched = self.commit_events = 0
        self.unkeyed_unknown = 0
        self.pending: Counter[tuple[str, ...]] = Counter()
        self.confirmed: set[tuple[str, ...]] = set()
        self.uncertain_commits = 0

    def update(self, record: dict[str, Any]) -> None:
        self.writes += 1
        kind = event_type(record)
        key = tuple(_nonempty_string(record, field) for field in ("root_task_id", "actor_id", "call_id"))
        if kind == "write_attempt":
            self.attempts += 1
        if kind == "write_commit":
            self.commit_events += 1
            if (any(field in record and record[field] not in ("ok", "success", "completed")
                    for field in ("status", "outcome"))
                    or ("side_effect_state" in record and record["side_effect_state"] != "committed")):
                self.uncertain_commits += 1
                return
            self.commits += 1
            if all(key):
                self.confirmed.add(key)
            write_scope = _nonempty_string(record, "write_scope_sha256")
            authorization_scope = _nonempty_string(record, "authorization_scope_sha256")
            if (("authorization_conflict" in record and record["authorization_conflict"] is not False)
                    or not AUTHORIZATION_ID_PATTERN.fullmatch(_nonempty_string(record, "authorization_id"))
                    or not SHA256_PATTERN.fullmatch(write_scope)
                    or write_scope != authorization_scope):
                self.unmatched += 1
        elif record.get("side_effect_state") not in ("none", "not_started", "rolled_back"):
            if all(key):
                self.pending[key] += 1
            else:
                self.unkeyed_unknown += 1

    def metrics(self, coverage: dict[str, Any]) -> dict[str, Any]:
        unknown = self.unkeyed_unknown + self.uncertain_commits + sum(
            count for key, count in self.pending.items() if key not in self.confirmed
        )
        if coverage.get("status") != "complete" or unknown:
            status = "outcome_uncertain"
        elif self.commits:
            status = "confirmed_commits_unmatched" if self.unmatched else "confirmed_commits_matched"
        elif self.writes:
            status = "attempts_without_confirmed_commit"
        else:
            status = "no_write_intent_observed"
        return {
            "write_event_count": self.writes,
            "write_attempt_count": self.attempts,
            "write_commit_event_count": self.commit_events,
            "write_commit_count": self.commits,
            "unmatched_write_count": self.unmatched,
            "unmatched_write_rate": ratio(self.unmatched, self.commits),
            "uncertain_write_outcome_count": unknown,
            "authorization_evidence_status": status,
        }


def _skill_load_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    state = _SkillLoadState()
    for record in records:
        if event_type(record) in {"skill_load", "skill_load_candidate"}:
            state.update(record)
    return state.metrics()


def _retry_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    retries = [record for record in records if event_type(record) == "retry" or record.get("retry_of")]
    classifications: Counter[str] = Counter()
    signatures: Counter[tuple[str, str, str, str]] = Counter()
    connector_eof = 0
    eof_without_fallback = 0
    ambiguous_write_retries = 0

    for record in retries:
        signature = text_value(record, "error_signature")
        classifications[_retry_classification(record)] += 1

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
        **_retry_evidence_metrics(classifications, len(retries)),
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


def _authorization_metrics(records: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    state = _AuthorizationState()
    for record in records:
        if event_type(record) in WRITE_EVENTS:
            state.update(record)
    result = state.metrics(coverage)
    result["readonly_approval_rounds"] = sum(
        1 for record in records if event_type(record) == "approval_request"
        and text_value(record, "task_mode").lower() in {"audit_only", "read_only"}
    )
    return result


def _context_metrics(records: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
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
    skills = _SkillLoadState()
    inputs = _TokenShareState()
    for record in records:
        inputs.update(record)
        if event_type(record) in {"skill_load", "skill_load_candidate"}:
            skills.update(record)
    return {
        "root_task_count": len(root_tasks),
        "context_compaction_count": compactions,
        "compactions_per_10_root_tasks": round(compactions * 10 / len(root_tasks), 4) if root_tasks else None,
        "context_recovery_count": len(recovery_events),
        "matched_context_recovery_count": matched_recoveries,
        "context_recovery_coverage": ratio(matched_recoveries, compactions),
        "semantic_recovery_verified_count": semantic_recoveries,
        "semantic_recovery_coverage": ratio(semantic_recoveries, compactions),
        **inputs.metrics(skills, coverage),
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
        self.skills = _SkillLoadState()
        self.inputs = _TokenShareState()
        self.analysis = CollaborationAnalysis()
        self.retry_count = 0
        self.retry_classifications: Counter[str] = Counter()
        self.retry_signatures: Counter[tuple[str, str, str, str]] = Counter()
        self.connector_eof = self.eof_without_fallback = self.ambiguous_write_retries = 0
        self.root_tokens = self.child_tokens = 0
        self.spawns = self.full_history_forks = self.minimal_packets = 0
        self.authorization = _AuthorizationState()
        self.readonly_approvals = 0
        self.root_tasks: set[str] = set()
        self.compactions: Counter[tuple[str, str]] = Counter()
        self.recovery_keys: set[tuple[str, str]] = set()
        self.semantic_recovery_keys: set[tuple[str, str]] = set()
        self.recovery_count = 0

    def update(self, record: dict[str, Any]) -> None:
        self.record_count += 1
        self.analysis.update(record)
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
        self.inputs.update(record)
        tokens = token_count(record)
        is_child = text_value(record, "actor_type").lower() == "subagent" or bool(record.get("parent_actor_id"))
        if is_child:
            self.child_tokens += tokens
        else:
            self.root_tokens += tokens

        if kind in WAIT_EVENTS:
            self._update_wait(record, root or "unknown-root", actor)
        if kind in {"skill_load", "skill_load_candidate"}:
            self.skills.update(record)
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
            self.authorization.update(record)
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




    def _update_retry(self, record: dict[str, Any]) -> None:
        self.retry_count += 1
        signature = text_value(record, "error_signature")
        self.retry_classifications[_retry_classification(record)] += 1
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
        coverage = _semantic_coverage(coverage, self.skills.conflicts + self.inputs.conflicts,
                                      self.retry_classifications["conflicting"],
                                      self.skills.invalid_candidate_bindings)
        analysis, coverage = self.analysis.finalize(coverage)
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
            "skill_load": self.skills.metrics(),
            "retry": {
                "retry_count": self.retry_count,
                **_retry_evidence_metrics(self.retry_classifications, self.retry_count),
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
                **self.authorization.metrics(coverage),
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
                **self.inputs.metrics(self.skills, coverage),
            },
        }
        report = _report_payload(components, dict(self.failure_types.most_common()), operational, coverage, self.record_count)
        report["collaboration_analysis"] = analysis
        return report


LIMITATIONS = [
    "Only explicit fields in the supplied records were aggregated.",
    "Missing durations, token counts, state versions, and fingerprints are not inferred.",
    "Authorization status describes observed intent, outcomes and fingerprints, never natural-language permission.",
    "Legacy skill receipt IDs do not establish occurrence identity; business-key candidate pairing is only an upper bound.",
    "Blind retry rate uses classified retries only; missing rationale remains unverified and coverage must be shown.",
    "Skill text volume is not billed input or cost; token share requires compatible complete model-input scopes.",
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
        "metric_semantics_version": 2,
        "coverage": coverage,
        "record_count": record_count,
        "component_count": len(components),
        "failure_types": failure_types,
        "components": components,
        "operational_metrics": operational_metrics,
        "limitations": list(LIMITATIONS),
    }


def _semantic_coverage(coverage: dict[str, Any], identity_conflicts: int,
                       retry_conflicts: int, invalid_candidate_bindings: int) -> dict[str, Any]:
    issues = list(coverage.get("issues", []))
    for count, category, detail in (
        (identity_conflicts, "event_identity_conflict", "occurrence delivery payload(s) conflict"),
        (invalid_candidate_bindings, "invalid_candidate_binding", "skill load record(s) have an invalid explicit candidate binding"),
        (retry_conflicts, "conflicting_retry_evidence", "retry record(s) contain contradictory structured evidence"),
    ):
        if count and not any(issue.get("category") == category for issue in issues):
            issues.append(_issue(Path("<records>"), category, f"{count} {detail}"))
    if issues != coverage.get("issues", []):
        return {**coverage, "status": "partial", "issues": issues}
    return coverage


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

    wait = _wait_metrics(materialized)
    if coverage.get("status") in {"complete", "partial"}:
        sequence_issues = []
        for field, category in (("out_of_order_sequence_count", "out_of_order_sequence"),
                                ("missing_sequence_timestamp_count", "missing_sequence_timestamp")):
            if wait[field] and not any(issue.get("category") == category for issue in coverage.get("issues", [])):
                sequence_issues.append(_issue(Path("<records>"), category, f"{wait[field]} wait event(s) have unverified ordering"))
        if sequence_issues:
            coverage = {**coverage, "status": "partial", "issues": [*coverage.get("issues", []), *sequence_issues]}
    skills = _skill_load_metrics(materialized)
    retry = _retry_metrics(materialized)
    inputs = _TokenShareState()
    analysis_state = CollaborationAnalysis()
    for record in materialized:
        inputs.update(record)
        analysis_state.update(record)
    coverage = _semantic_coverage(coverage, skills["event_identity_conflict_count"] + inputs.conflicts,
                                  retry["conflicting_retry_evidence_count"],
                                  sum(_invalid_candidate_binding(record) for record in materialized))
    analysis, coverage = analysis_state.finalize(coverage)
    operational = {
            "wait": wait,
            "skill_load": skills,
            "retry": retry,
            "subagent": _subagent_metrics(materialized),
            "authorization": _authorization_metrics(materialized, coverage),
            "context": _context_metrics(materialized, coverage),
    }
    report = _report_payload(components, failure_types, operational, coverage, len(materialized))
    report["collaboration_analysis"] = analysis
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate explicit collaboration audit JSON or JSONL events.")
    parser.add_argument("--input", required=True, help="Input JSON/JSONL file or directory.")
    parser.add_argument("--output", help="Optional JSON output path. Without it, the report is printed only.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 for incomplete coverage, including sequence or structured evidence conflicts.",
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
