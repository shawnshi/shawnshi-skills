"""Canonical usage ledger; component/context estimates are never added to usage."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re
from typing import Any

WORK_TYPES = {
    "coding", "debugging", "testing", "review", "research", "writing",
    "data_analysis", "planning", "operations", "skill_maintenance", "other",
}
OPTIONAL_TOKENS = ("cached_input_tokens", "cache_creation_input_tokens", "reasoning_tokens")


def fixed_timezone(value: str) -> timezone:
    if not isinstance(value, str) or not re.fullmatch(r"[+-]\d{2}:\d{2}", value):
        raise ValueError("token timezone must be a fixed offset such as +08:00")
    hours, minutes = map(int, value[1:].split(":"))
    if hours > 23 or minutes > 59:
        raise ValueError("invalid token timezone offset")
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if value[0] == "-" else 1)))


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class TokenAnalysis:
    def __init__(self, *, timezone_offset: str = "+08:00", bucket_hours: int = 1,
                 start: str | None = None, end: str | None = None) -> None:
        self.tz = fixed_timezone(timezone_offset)
        if isinstance(bucket_hours, bool) or bucket_hours not in (1, 2, 3, 4, 6, 8, 12, 24):
            raise ValueError("token bucket hours must divide 24")
        self.bucket_hours = bucket_hours
        self.start = self._boundary(start)
        self.end = self._boundary(end)
        if self.start and self.end and self.start >= self.end:
            raise ValueError("token start must precede token end")
        self.timezone_offset = timezone_offset
        self.records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.conflicts: set[tuple[str, str, str]] = set()
        self.invalid_keys: set[tuple[str, str, str]] = set()
        self.issues: Counter[str] = Counter()
        self.event_count = self.duplicates = 0

    def _boundary(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).replace(tzinfo=self.tz)
        parsed = timestamp(value)
        if parsed is None:
            raise ValueError("token boundaries require an ISO date or timezone-aware timestamp")
        return parsed

    def update(self, record: dict[str, Any]) -> None:
        if record.get("event_type", record.get("type")) != "token_usage":
            return
        self.event_count += 1
        session, root = _text(record.get("session_id")), _text(record.get("root_task_id"))
        scope = "session:" + session if session else "task:" + root if root and root != "unbound-root" else ""
        identity = _text(record.get("usage_id")) or _text(record.get("event_id"))
        actor = _text(record.get("actor_id"))
        key = (scope, actor, identity)
        # A root and a child may have the same local usage ID; scope/actor are part of identity.
        if not scope or not identity or not actor:
            self.issues["missing_usage_identity"] += 1
            return
        if record.get("usage_mode", "delta") != "delta":
            self.issues["non_delta_usage"] += 1
            self.invalid_keys.add(key)
            return
        if not all(_count(record.get(field)) for field in ("input_tokens", "output_tokens")):
            self.issues["invalid_token_counts"] += 1
            self.invalid_keys.add(key)
            return
        kind = record.get("measurement_kind", "reported")
        if kind not in {"reported", "estimated"}:
            self.issues["invalid_measurement_kind"] += 1
            self.invalid_keys.add(key)
            return
        optional = {field: record.get(field) for field in OPTIONAL_TOKENS}
        if any(value is not None and not _count(value) for value in optional.values()):
            self.issues["invalid_token_breakdown"] += 1
            self.invalid_keys.add(key)
            return
        cached = optional["cached_input_tokens"] or 0
        created = optional["cache_creation_input_tokens"] or 0
        if cached + created > record["input_tokens"] or (optional["reasoning_tokens"] or 0) > record["output_tokens"]:
            self.issues["invalid_token_breakdown"] += 1
            self.invalid_keys.add(key)
            return
        parsed = timestamp(record.get("timestamp"))
        model = _text(record.get("model")) or "unknown"
        provider = _text(record.get("provider")) or "unknown"
        work_type = _text(record.get("work_type")) or "unknown"
        if work_type not in WORK_TYPES | {"unknown"}:
            self.issues["invalid_work_type"] += 1
            work_type = "unknown"
        usage = {
            "timestamp": parsed.astimezone(timezone.utc).isoformat() if parsed else None,
            "provider": provider, "model": model, "work_type": work_type,
            "measurement_kind": kind, "input_tokens": record["input_tokens"],
            "output_tokens": record["output_tokens"], **optional,
            "root_task_id": _text(record.get("root_task_id")),
        }
        previous = self.records.get(key)
        if previous is not None:
            if previous == usage:
                self.duplicates += 1
            else:
                self.conflicts.add(key)
        else:
            self.records[key] = usage

    @staticmethod
    def _summary(rows: list[dict[str, Any]], denominator: int) -> dict[str, Any]:
        input_tokens = sum(row["input_tokens"] for row in rows)
        output_tokens = sum(row["output_tokens"] for row in rows)
        total = input_tokens + output_tokens
        roots = {row["root_task_id"] for row in rows if row["root_task_id"]}
        result = {
            "usage_count": len(rows), "root_task_count": len(roots),
            "input_tokens": input_tokens if rows else None, "output_tokens": output_tokens if rows else None,
            "total_tokens": total if rows else None,
            "share": round(total / denominator, 6) if denominator else None,
            "tokens_per_usage": round(total / len(rows), 3) if rows else None,
        }
        for field in OPTIONAL_TOKENS:
            values = [row[field] for row in rows if row[field] is not None]
            result[field] = sum(values) if rows and len(values) == len(rows) else None
            result[field + "_observed_sum"] = sum(values) if values else None
            result[field + "_coverage_count"] = len(values)
        return result

    def finalize(self, source_coverage: dict[str, Any]) -> dict[str, Any]:
        selected: dict[str, list[dict[str, Any]]] = {"reported": [], "estimated": []}
        excluded = missing_time = 0
        for key, row in self.records.items():
            if key in self.conflicts or key in self.invalid_keys:
                continue
            dt = timestamp(row["timestamp"])
            if dt is None:
                missing_time += 1
                if self.start or self.end:
                    excluded += 1
                    continue
            if dt and ((self.start and dt < self.start) or (self.end and dt >= self.end)):
                excluded += 1
                continue
            selected[row["measurement_kind"]].append(row)
        ledgers = {kind: self._ledger(rows) for kind, rows in selected.items()}
        issues = dict(sorted(self.issues.items()))
        if self.conflicts:
            issues["conflicting_usage_identity"] = len(self.conflicts)
        selected_rows = selected["reported"] + selected["estimated"]
        unknown_model = sum(row["model"] == "unknown" for row in selected_rows)
        unknown_work = sum(row["work_type"] == "unknown" for row in selected_rows)
        status = "complete"
        if not self.event_count:
            status = "unavailable"
        elif not selected_rows:
            status = "partial" if issues or missing_time else "empty_window"
        elif issues or missing_time or unknown_model or unknown_work or source_coverage.get("status") != "complete":
            status = "partial"
        return {
            "semantics_version": 1, "status": status,
            "source_coverage_status": source_coverage.get("status", "not_provided"),
            "scope": {"timezone": self.timezone_offset, "bucket_hours": self.bucket_hours,
                      "start_inclusive": self.start.isoformat() if self.start else None,
                      "end_exclusive": self.end.isoformat() if self.end else None,
                      "filter_applies_to": "token_analysis_only"},
            "coverage": {"token_usage_event_count": self.event_count,
                         "unique_usage_identity_count": len(set(self.records) | self.invalid_keys),
                         "duplicate_delivery_count": self.duplicates,
                         "conflicting_identity_count": len(self.conflicts),
                         "invalid_identity_count": len(self.invalid_keys),
                         "excluded_by_window_or_missing_time_count": excluded,
                         "missing_timestamp_count": missing_time,
                         "selected_usage_count": len(selected_rows),
                         "unknown_model_count": unknown_model, "unknown_work_type_count": unknown_work,
                         "issues": issues},
            **ledgers,
            "limitations": [
                "Only canonical token_usage deltas are included; other events and parent summaries are excluded.",
                "Reported usage and estimates are separate; neither establishes invoice cost or billing completeness.",
                "Input includes cache read/creation; output includes reasoning. Subsets are never added again.",
                "Each dimension partitions the same ledger; totals across different dimensions must not be added.",
                "Time is attributed to the usage observation timestamp, not apportioned across request duration.",
                "Work labels must be explicit; mixed work must be tagged per usage or retained as unknown.",
                "Absent buckets are unobserved, not proof of zero usage. High usage is not proof of avoidable waste.",
                "Legacy component and subagent token metrics use a different scope; use this ledger for usage totals.",
            ],
        }

    def _ledger(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        total = sum(row["input_tokens"] + row["output_tokens"] for row in rows)
        dimensions: dict[str, dict[tuple[str, ...], list[dict[str, Any]]]] = {
            name: defaultdict(list) for name in
            ("by_date", "by_time_bucket", "by_time_period", "by_model", "by_work_type", "by_model_work_type")
        }
        for row in rows:
            dt = timestamp(row["timestamp"])
            if dt:
                local = dt.astimezone(self.tz)
                hour = local.hour // self.bucket_hours * self.bucket_hours
                begin = local.replace(hour=hour, minute=0, second=0, microsecond=0)
                finish = begin + timedelta(hours=self.bucket_hours)
                date = (local.date().isoformat(),)
                bucket = (begin.isoformat(), finish.isoformat())
                period = (f"{hour:02d}:00", f"{hour + self.bucket_hours:02d}:00")
            else:
                date, bucket, period = ("unknown",), ("unknown", "unknown"), ("unknown", "unknown")
            keys = {"by_date": date, "by_time_bucket": bucket, "by_time_period": period,
                    "by_model": (row["provider"], row["model"]), "by_work_type": (row["work_type"],),
                    "by_model_work_type": (row["provider"], row["model"], row["work_type"])}
            for name, key in keys.items():
                dimensions[name][key].append(row)
        names = {"by_date": ("date",), "by_time_bucket": ("start", "end"),
                 "by_time_period": ("start_hour", "end_hour"), "by_model": ("provider", "model"),
                 "by_work_type": ("work_type",), "by_model_work_type": ("provider", "model", "work_type")}
        result: dict[str, Any] = {"totals": self._summary(rows, total)}
        for name, groups in dimensions.items():
            keys = sorted(groups)
            if name in {"by_model", "by_work_type", "by_model_work_type"}:
                keys.sort(key=lambda key: -sum(r["input_tokens"] + r["output_tokens"] for r in groups[key]))
            result[name] = [{**dict(zip(names[name], key)), **self._summary(groups[key], total)} for key in keys]
        return result
