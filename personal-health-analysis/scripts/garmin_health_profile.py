#!/usr/bin/env python3
"""Build a bounded, local-only Garmin multidimensional health profile."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import stat
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import garmin_sqlite_adapter as adapter
from garmin_patterns import normalize_daily_numeric, sleep_regularity_snapshot


MAX_DAYS = 366
MAX_CONTEXT_BYTES = 131072
CONTEXT_ACTION = "observe_sleep_opportunity"


class ContextValidationError(ValueError):
    """Invalid user input; never include caller paths or values in diagnostics."""


def _context_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextValidationError("CONTEXT_INVALID")
        result[key] = value
    return result


def _validate_context(payload: object, dates: list[str]) -> list[dict[str, Any]]:
    """Validate a small closed schema; absence, false and zero remain distinct."""
    def require(condition):
        if not condition:
            raise ContextValidationError("CONTEXT_INVALID")

    if not isinstance(payload, dict) or set(payload) != {"schema_version", "records"}:
        raise ContextValidationError("CONTEXT_INVALID")
    require(type(payload["schema_version"]) is int and payload["schema_version"] == 1)
    records = payload["records"]
    if not isinstance(records, list) or len(records) > min(MAX_DAYS, len(dates)):
        raise ContextValidationError("CONTEXT_INVALID")
    seen = set()
    fields = {"date", "sleep_opportunity_minutes", "subjective_daytime_sleepiness", "caffeine_last_time", "user_selected_action", "performed", "phase"}
    for row in records:
        require(type(row) is dict and set(row) <= fields and "date" in row)
        day = row["date"]
        require(type(day) is str and day in dates and day not in seen)
        seen.add(day)
        if "sleep_opportunity_minutes" in row:
            value = row["sleep_opportunity_minutes"]
            require(type(value) is int and 0 <= value <= 1440)
        if "subjective_daytime_sleepiness" in row:
            value = row["subjective_daytime_sleepiness"]
            require(type(value) is str and value in {"low", "moderate", "high"})
        if "caffeine_last_time" in row:
            value = row["caffeine_last_time"]
            require(type(value) is str and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is not None)
        if "user_selected_action" in row:
            require(row["user_selected_action"] == CONTEXT_ACTION)
        if "performed" in row:
            require("user_selected_action" in row and type(row["performed"]) is bool)
        if "phase" in row:
            require("user_selected_action" in row and type(row["phase"]) is str and row["phase"] in {"baseline", "observation"})
    ordered = sorted(records, key=lambda row: row["date"])
    action_rows = [row for row in ordered if "user_selected_action" in row]
    if any("phase" in row for row in action_rows):
        require(all("phase" in row for row in action_rows))
        phases = [row["phase"] for row in action_rows]
        require(phases == sorted(phases))  # Baseline cannot resume after observation.
    return ordered


class ContextReadError(OSError):
    """Retain native error classification without exposing path or input content."""

    def __init__(self, cause: OSError):
        super().__init__(cause.errno, "CONTEXT_READ_ERROR")
        self.error_type = type(cause).__name__


def _load_context(path_text: str, dates: list[str]) -> list[dict[str, Any]]:
    try:
        return _read_context_file(path_text, dates)
    except OSError as exc:
        raise ContextReadError(exc) from exc
    except ValueError as exc:
        raise ContextValidationError("CONTEXT_INVALID") from exc


def _read_context_file(path_text: str, dates: list[str]) -> list[dict[str, Any]]:
    """Read only an explicitly selected regular local file, at most limit + 1 bytes."""
    portable = path_text.replace("\\", "/")
    if portable.startswith("//") or ":" in portable[2:] or (":" in portable and not re.match(r"^[A-Za-z]:/", portable)):
        raise ContextValidationError("CONTEXT_INVALID")
    path = Path(path_text).absolute()
    if os.name == "nt":
        import ctypes
        # Reject mapped network drives before touching any path components.
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) not in {2, 3, 5, 6}:
            raise ContextValidationError("CONTEXT_INVALID")
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ContextValidationError("CONTEXT_INVALID")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ContextValidationError("CONTEXT_INVALID")
    with path.open("rb") as handle:
        raw = handle.read(MAX_CONTEXT_BYTES + 1)
    if len(raw) > MAX_CONTEXT_BYTES:
        raise ContextValidationError("CONTEXT_INVALID")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_context_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContextValidationError("CONTEXT_INVALID") from exc
    return _validate_context(payload, dates)


def _context_review(records: list[dict[str, Any]], dates: list[str], sleep_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate user reports only; never turn them into objective comparability."""
    normalized = normalize_daily_numeric(
        [{"date": row.get("date"), "seconds": _duration_seconds(row.get("total_sleep"))} for row in sleep_rows],
        "seconds", dates, allow_zero=False,
    )
    duration_by_date = {row["date"]: row["value"] / 60 for row in normalized["values"]}

    def aggregate(rows, expected_days):
        opportunity = [row["sleep_opportunity_minutes"] for row in rows if "sleep_opportunity_minutes" in row]
        sleepiness = [row["subjective_daytime_sleepiness"] for row in rows if "subjective_daytime_sleepiness" in row]
        paired = [row for row in rows if "sleep_opportunity_minutes" in row and row["date"] in duration_by_date]
        action_rows = [row for row in rows if "user_selected_action" in row]
        recorded = sum("performed" in row for row in action_rows)
        return {
            "context_recorded_days": len(rows), "context_missing_days": expected_days - len(rows),
            "action_selected_days": len(action_rows), "action_recorded_days": recorded,
            "action_completed_days": sum(row.get("performed") is True for row in action_rows),
            "action_not_completed_days": sum(row.get("performed") is False for row in action_rows),
            "action_missing_days": expected_days - recorded,
            "sleep_opportunity_recorded_days": len(opportunity),
            "sleep_opportunity_median_minutes": statistics.median(opportunity) if opportunity else None,
            "sleepiness_recorded_days": len(sleepiness),
            "sleepiness_category_counts": {key: sleepiness.count(key) for key in ("low", "moderate", "high")},
            "caffeine_time_recorded_days": sum("caffeine_last_time" in row for row in rows),
            "paired_sleep_duration_days": len(paired),
            "paired_sleep_opportunity_median_minutes": statistics.median(row["sleep_opportunity_minutes"] for row in paired) if paired else None,
            "paired_device_sleep_duration_median_minutes": round(statistics.median(duration_by_date[row["date"]] for row in paired), 2) if paired else None,
            "pairing_status": "descriptive_co_observation_only" if paired else "insufficient_evidence",
        }

    phases = {}
    for phase in ("baseline", "observation"):
        rows = [row for row in records if row.get("phase") == phase]
        if rows:
            start, end = rows[0]["date"], rows[-1]["date"]
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            phases[phase] = {"start": start, "end": end, "span_days": span, **aggregate(rows, span)}
    comparisons = {}
    for field, count_key in (("sleep_opportunity", "sleep_opportunity_recorded_days"), ("sleepiness", "sleepiness_recorded_days")):
        comparisons[field] = "descriptive_side_by_side_only" if len(phases) == 2 and all(part[count_key] > 0 for part in phases.values()) else "insufficient_evidence"
    return {
        "schema": "user-context-review.v1", "source": "USER-REPORTED",
        "window": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "selected_action_id": CONTEXT_ACTION if any("user_selected_action" in row for row in records) else None,
        "action_review_status": "descriptive_counts_only" if any("performed" in row for row in records) else "not_evaluated",
        "summary": aggregate(records, len(dates)), "phases": phases,
        "phase_comparison": comparisons,
        "objective_outcome_comparison": "not_evaluated", "effectiveness": "not_evaluated",
        "evidence_pointers": ["/problem_insights/items/0", "/modules/sleep_health/qualified_regularity"],
        "limitations": [
            "USER-REPORTED context is not device or clinical evidence; no causal inference or efficacy claim.",
            "Counts describe reporting/completion, not physiological improvement; missing is not false or zero.",
            "Phase bounds are first/last explicitly labeled records, not inferred plans; unlabeled dates are not assigned phases.",
            "Same-date co-observations are descriptive only; device epochs, regularity and trend gates remain unchanged.",
            "Caffeine clock times are counted only, with no timezone effects or cutoff advice.",
        ],
        "privacy": {"persisted": False, "raw_records_included": False, "additional_database_reads": False},
    }


def _finite(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _duration_seconds(value: object) -> float | None:
    number = _finite(value)
    if number is not None:
        return number
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    except ValueError:
        return None
    if hours < 0 or minutes not in range(60) or not (0 <= seconds < 60):
        return None
    return hours * 3600 + minutes * 60 + seconds


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _table_columns(connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _read_supported_rows(
    connection,
    table: str,
    date_column: str,
    requested: dict[str, str],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    columns = _table_columns(connection, table)
    if date_column not in columns:
        raise adapter.LocalDatabaseReadError(f"{table}_date_column_missing")
    expressions = [f'date("{date_column}") AS "date"']
    for source, target in requested.items():
        if source in columns:
            expressions.append(f'"{source}" AS "{target}"')
        else:
            expressions.append(f'NULL AS "{target}"')
    query = (
        f'SELECT {", ".join(expressions)} FROM "{table}" '
        f'WHERE date("{date_column}") BETWEEN ? AND ? '
        f'ORDER BY date("{date_column}") ASC'
    )
    cursor = connection.execute(query, (start, end))
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _read_latest_supported_row(
    connection,
    table: str,
    date_column: str,
    requested: dict[str, str],
    end: str,
) -> dict[str, Any] | None:
    columns = _table_columns(connection, table)
    if date_column not in columns:
        return None
    expressions = [f'date("{date_column}") AS "date"']
    for source, target in requested.items():
        if source in columns:
            expressions.append(f'"{source}" AS "{target}"')
        else:
            expressions.append(f'NULL AS "{target}"')
    query = (
        f'SELECT {", ".join(expressions)} FROM "{table}" '
        f'WHERE date("{date_column}") <= ? '
        f'ORDER BY "{date_column}" DESC LIMIT 1'
    )
    cursor = connection.execute(query, (end,))
    row = cursor.fetchone()
    if row is None:
        return None
    names = [item[0] for item in cursor.description]
    return dict(zip(names, row))


def _coverage(
    rows: list[dict[str, Any]],
    key: str,
    requested_dates: list[str],
    transform: Callable[[object], float | None] = _finite,
) -> tuple[dict[str, Any], list[tuple[str, float]]]:
    observed = []
    for row in rows:
        value = transform(row.get(key))
        if value is not None:
            observed.append((str(row.get("date") or ""), value))
    observed_dates = {item[0] for item in observed}
    missing = [item for item in requested_dates if item not in observed_dates]
    longest = 0
    current = 0
    for item in requested_dates:
        if item in observed_dates:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    trailing = 0
    for item in reversed(requested_dates):
        if item in observed_dates:
            break
        trailing += 1
    count = len(observed_dates)
    if count == len(requested_dates):
        status = "complete"
    elif count:
        status = "partial"
    else:
        status = "no_observations"
    return (
        {
            "status": status,
            "requested_days": len(requested_dates),
            "observed_days": count,
            "coverage_fraction": round(count / len(requested_dates), 3),
            "latest_observation_date": max(observed_dates) if observed_dates else None,
            "missing_days": len(missing),
            "longest_missing_run_days": longest,
            "trailing_missing_days": trailing,
        },
        observed,
    )


def _series_summary(
    rows: list[dict[str, Any]],
    key: str,
    requested_dates: list[str],
    unit: str,
    transform: Callable[[object], float | None] = _finite,
    scale: float = 1.0,
) -> dict[str, Any]:
    coverage, observed = _coverage(rows, key, requested_dates, transform)
    values = [(day, value * scale) for day, value in observed]
    latest = max(values, key=lambda item: item[0]) if values else None
    numbers = [item[1] for item in values]
    return {
        "unit": unit,
        "latest": round(latest[1], 2) if latest else None,
        "latest_date": latest[0] if latest else None,
        "median": round(statistics.median(numbers), 2) if numbers else None,
        "minimum": round(min(numbers), 2) if numbers else None,
        "maximum": round(max(numbers), 2) if numbers else None,
        "coverage": coverage,
    }


def _circular_clock_summary(values: list[datetime]) -> dict[str, Any]:
    if len(values) < 3:
        return {"status": "insufficient_observations", "observed_nights": len(values)}
    angles = [2 * math.pi * ((item.hour * 60 + item.minute + item.second / 60) / 1440) for item in values]
    mean_sin = statistics.mean(math.sin(item) for item in angles)
    mean_cos = statistics.mean(math.cos(item) for item in angles)
    resultant = math.hypot(mean_sin, mean_cos)
    mean_angle = math.atan2(mean_sin, mean_cos) % (2 * math.pi)
    clock_minutes = mean_angle * 1440 / (2 * math.pi)
    hours = int(clock_minutes // 60) % 24
    minutes = int(round(clock_minutes % 60))
    if minutes == 60:
        hours = (hours + 1) % 24
        minutes = 0
    variability = (
        math.sqrt(-2 * math.log(resultant)) * 24 / (2 * math.pi)
        if 0 < resultant <= 1
        else None
    )
    return {
        "status": "eligible",
        "observed_nights": len(values),
        "circular_mean_clock_time": f"{hours:02d}:{minutes:02d}",
        "circular_sd_hours": round(variability, 2) if variability is not None else None,
        "classification": "descriptive_only_no_threshold",
    }


def _sleep_timing(rows: list[dict[str, Any]], timezone_name: str | None) -> dict[str, Any]:
    if not timezone_name:
        return {
            "status": "timezone_required",
            "reason": "Naive GarminDB timestamps require an explicit IANA timezone.",
        }
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return {"status": "timezone_invalid", "timezone": timezone_name}
    starts: list[datetime] = []
    ends: list[datetime] = []
    aware_semantics: set[str] = set()
    pairs_by_date: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        if row.get("sleep_start") is not None and row.get("sleep_end") is not None:
            pairs_by_date.setdefault(str(row.get("date")), set()).add(
                (str(row["sleep_start"]), str(row["sleep_end"]))
            )
    if any(len(pairs) > 1 for pairs in pairs_by_date.values()):
        return {"status": "duplicate_conflict", "timezone": timezone_name}
    for pairs in pairs_by_date.values():
        start_raw, end_raw = next(iter(pairs))
        try:
            start = datetime.fromisoformat(start_raw)
            end = datetime.fromisoformat(end_raw)
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None and end.tzinfo is None:
            start = start.replace(tzinfo=timezone)
            end = end.replace(tzinfo=timezone)
            aware_semantics.add("caller_timezone_applied_to_naive_source")
        elif start.tzinfo is not None and end.tzinfo is not None:
            start = start.astimezone(timezone)
            end = end.astimezone(timezone)
            aware_semantics.add("source_offsets_converted")
        else:
            aware_semantics.add("mixed_pair")
            continue
        if end <= start or end - start > timedelta(hours=24):
            continue
        starts.append(start)
        ends.append(end)
    if "mixed_pair" in aware_semantics or len(aware_semantics) > 1:
        return {"status": "mixed_timezone_semantics", "timezone": timezone_name}
    return {
        "status": "eligible" if len(starts) >= 3 else "insufficient_observations",
        "timezone": timezone_name,
        "timing_basis": next(iter(aware_semantics), "no_valid_pairs"),
        "sleep_onset": _circular_clock_summary(starts),
        "wake_time": _circular_clock_summary(ends),
    }


def _latest_row(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any] | None:
    eligible = [row for row in rows if any(row.get(key) is not None for key in keys)]
    return max(eligible, key=lambda row: str(row.get("date") or "")) if eligible else None


def _sleep_module(rows: list[dict[str, Any]], dates: list[str], timezone_name: str | None) -> dict[str, Any]:
    duration = _series_summary(rows, "total_sleep", dates, "hours", _duration_seconds, 1 / 3600)
    awake = _series_summary(rows, "awake", dates, "minutes", _duration_seconds, 1 / 60)
    score = _series_summary(rows, "sleep_score", dates, "Garmin score")
    sleep_records = [
        {
            "date": row.get("date"),
            "sleep_time_seconds": _duration_seconds(row.get("total_sleep")),
            "sleep_start": row.get("sleep_start"),
            "sleep_end": row.get("sleep_end"),
        }
        for row in rows
    ]
    normalized_duration = normalize_daily_numeric(
        sleep_records, "sleep_time_seconds", dates, allow_zero=False
    )
    duration_conflicts = normalized_duration["conflicting_duplicate_dates"]
    duration_values = [item["value"] / 3600 for item in normalized_duration["values"]]
    continuity_values = []
    for row in rows:
        total = _duration_seconds(row.get("total_sleep"))
        awake_seconds = _duration_seconds(row.get("awake"))
        if total is not None and total > 0 and awake_seconds is not None and awake_seconds >= 0:
            denominator = total + awake_seconds
            if denominator > 0:
                continuity_values.append(total / denominator * 100)
    regularity = {
        "status_scope": "descriptive_availability_only",
        "label": "睡眠时长窗口描述（非合格规律性）",
        "status": "duplicate_conflict" if duration_conflicts else "eligible" if len(duration_values) >= 3 else "insufficient_observations",
        "observed_nights": len(duration_values),
        "conflicting_duplicate_dates": duration_conflicts,
        "duration_sd_hours": round(statistics.stdev(duration_values), 2)
        if len(duration_values) >= 3 and not duration_conflicts
        else None,
        "classification": "descriptive_only_no_threshold",
    }
    continuity = {
        "status": "eligible" if len(continuity_values) >= 3 else "insufficient_observations",
        "observed_nights": len(continuity_values),
        "median_percent": round(statistics.median(continuity_values), 1)
        if continuity_values
        else None,
        "metric_name": "device_estimated_sleep_continuity",
        "clinical_sleep_efficiency": False,
    }
    timing = _sleep_timing(rows, timezone_name)
    timing.update(
        status_scope="descriptive_availability_only",
        label="睡眠时点窗口描述（非合格规律性）",
    )
    # Reuse the formal method without converting caller-supplied timezone
    # assumptions into source offsets or inventing local device attribution.
    qualified = sleep_regularity_snapshot(
        sleep_records,
        dates,
        epoch_comparable=None,
        epoch_status="device_attribution_unknown",
        window_days=14,
        min_valid_nights=7,
    )
    qualified["qualified"] = False
    qualified["baseline_comparable"] = None
    qualified["sample_status"] = {
        dimension: (
            "insufficient_window" if len(dates) < 14
            else "sufficient_observed_nights" if qualified[f"{dimension}_observed_nights"] >= 7
            else "insufficient_valid_nights"
        )
        for dimension in ("duration", "timing")
    }
    qualified["limitations"].extend([
        "device_attribution_unknown",
        "manufacturer_algorithm_epoch_unknown",
        "source_offsets_required_for_formal_timing",
    ])
    if len(dates) < 14:
        qualified.update(
            status="insufficient_window",
            duration_status="insufficient_window",
            timing_status="insufficient_window",
        )
    return {
        "duration": duration,
        "device_score": score,
        "device_estimated_awake_time": awake,
        "duration_regularity": regularity,
        "timing_regularity": timing,
        "qualified_regularity": qualified,
        "device_estimated_continuity": continuity,
        "stage_interpretation": "device_estimates_descriptive_only",
    }


def _hrv_module(rows: list[dict[str, Any]], dates: list[str]) -> dict[str, Any]:
    latest = _latest_row(rows, ("weekly_average", "last_night_average", "status"))
    weekly = _finite(latest.get("weekly_average")) if latest else None
    low = _finite(latest.get("baseline_low")) if latest else None
    upper = _finite(latest.get("baseline_upper")) if latest else None
    if weekly is None or low is None or upper is None or low > upper:
        alignment = "not_available"
    elif weekly < low:
        alignment = "below_vendor_baseline"
    elif weekly > upper:
        alignment = "above_vendor_baseline"
    else:
        alignment = "within_vendor_baseline"
    return {
        "last_night": _series_summary(rows, "last_night_average", dates, "ms"),
        "latest_vendor_context": {
            "date": latest.get("date") if latest else None,
            "weekly_average_ms": weekly,
            "last_night_5min_high_ms": _finite(latest.get("last_night_5min_high")) if latest else None,
            "baseline_low_ms": low,
            "baseline_upper_ms": upper,
            "vendor_status": str(latest.get("status")) if latest and latest.get("status") is not None else None,
            "derived_alignment": alignment,
            "interpretation": "Garmin-provided personal baseline context; not a diagnosis.",
        },
    }


def _body_battery_module(rows: list[dict[str, Any]], dates: list[str]) -> dict[str, Any]:
    high = _series_summary(rows, "body_battery_high", dates, "Garmin score")
    low = _series_summary(rows, "body_battery_low", dates, "Garmin score")
    charged = _series_summary(rows, "body_battery_charged", dates, "Garmin score")
    spans = []
    for row in rows:
        upper = _finite(row.get("body_battery_high"))
        lower = _finite(row.get("body_battery_low"))
        if upper is not None and lower is not None and upper >= lower:
            spans.append(upper - lower)
    return {
        "high": high,
        "low": low,
        "charged": charged,
        "median_daily_span": round(statistics.median(spans), 1) if spans else None,
        "lineage_warning": "Body Battery shares upstream HRV, stress, sleep and activity inputs.",
        "independent_evidence": False,
    }


def _movement_module(
    rows: list[dict[str, Any]],
    dates: list[str],
    adult_guideline: bool,
) -> dict[str, Any]:
    moderate_series = _series_summary(
        rows,
        "moderate_activity_time",
        dates,
        "minutes",
        _duration_seconds,
        1 / 60,
    )
    vigorous_series = _series_summary(
        rows,
        "vigorous_activity_time",
        dates,
        "minutes",
        _duration_seconds,
        1 / 60,
    )
    week_start = dates[-7] if len(dates) >= 7 else dates[0]
    weekly_rows = [row for row in rows if str(row.get("date") or "") >= week_start]
    moderate = sum(
        value / 60
        for row in weekly_rows
        if (value := _duration_seconds(row.get("moderate_activity_time"))) is not None
    )
    vigorous = sum(
        value / 60
        for row in weekly_rows
        if (value := _duration_seconds(row.get("vigorous_activity_time"))) is not None
    )
    latest_goal_row = _latest_row(weekly_rows, ("intensity_time_goal",))
    goal_seconds = _duration_seconds(latest_goal_row.get("intensity_time_goal")) if latest_goal_row else None
    goal_minutes = goal_seconds / 60 if goal_seconds is not None else None
    equivalent = moderate + 2 * vigorous
    guideline = {
        "status": "not_evaluated_population_not_confirmed",
        "reference_population": "adults_18_64",
        "minimum_equivalent_minutes": 150,
    }
    if adult_guideline:
        guideline["status"] = (
            "observed_at_or_above_minimum_equivalent"
            if equivalent >= 150
            else "observed_below_minimum_equivalent"
        )
        guideline["classification_scope"] = "public_health_reference_not_training_clearance"
    return {
        "steps": _series_summary(rows, "steps", dates, "steps"),
        "active_calories": _series_summary(rows, "active_calories", dates, "kcal"),
        "moderate_activity": moderate_series,
        "vigorous_activity": vigorous_series,
        "latest_7_days": {
            "window_start": week_start,
            "window_end": dates[-1],
            "moderate_minutes": round(moderate, 1),
            "vigorous_minutes": round(vigorous, 1),
            "garmin_equivalent_intensity_minutes": round(equivalent, 1),
            "vendor_goal_minutes": round(goal_minutes, 1) if goal_minutes is not None else None,
            "vendor_goal_date": latest_goal_row.get("date") if latest_goal_row else None,
            "moderate_coverage": _coverage(weekly_rows, "moderate_activity_time", dates[-7:], _duration_seconds)[0],
            "vigorous_coverage": _coverage(weekly_rows, "vigorous_activity_time", dates[-7:], _duration_seconds)[0],
            "vendor_goal_progress_percent": round(equivalent / goal_minutes * 100, 1)
            if goal_minutes and goal_minutes > 0
            else None,
            "device_semantics_warning": "Garmin calculation method and device generation can affect intensity-minute credit.",
        },
        "who_guideline_comparison": guideline,
        "step_threshold_classification": "not_performed",
    }


def _weight_module(
    rows: list[dict[str, Any]],
    dates: list[str],
    latest_as_of_end: dict[str, Any] | None,
    source_status: str,
) -> dict[str, Any]:
    series = _series_summary(rows, "weight_kg", dates, "kg")
    observed = sorted(
        (
            date.fromisoformat(str(row["date"])),
            value,
        )
        for row in rows
        if row.get("date")
        and (value := _finite(row.get("weight_kg"))) is not None
    )
    span_days = (observed[-1][0] - observed[0][0]).days if len(observed) >= 2 else 0
    trend: dict[str, Any] = {
        "status": "insufficient_observations_or_span",
        "observations": len(observed),
        "span_days": span_days,
        "minimum_observations": 3,
        "minimum_span_days": 14,
    }
    if len(observed) >= 3 and span_days >= 14:
        origin = observed[0][0]
        x_values = [(item[0] - origin).days for item in observed]
        y_values = [item[1] for item in observed]
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)
        denominator = sum((item - x_mean) ** 2 for item in x_values)
        slope_per_day = (
            sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, y_values))
            / denominator
            if denominator > 0
            else None
        )
        trend = {
            "status": "eligible_descriptive_only",
            "observations": len(observed),
            "span_days": span_days,
            "first_kg": round(y_values[0], 2),
            "last_kg": round(y_values[-1], 2),
            "absolute_change_kg": round(y_values[-1] - y_values[0], 2),
            "linear_slope_kg_per_week": round(slope_per_day * 7, 3)
            if slope_per_day is not None
            else None,
            "classification": "measurement_trend_not_body_composition_or_health_outcome",
        }
    latest_value = _finite(latest_as_of_end.get("weight_kg")) if latest_as_of_end else None
    latest_date = str(latest_as_of_end.get("date")) if latest_as_of_end and latest_as_of_end.get("date") else None
    freshness_days = (date.fromisoformat(dates[-1]) - date.fromisoformat(latest_date)).days if latest_date else None
    if source_status != "available":
        status = source_status
    elif observed:
        status = "available"
    elif latest_value is not None:
        status = "no_window_observations_prior_available"
    else:
        status = "no_observations"
    return {
        "status": status,
        "window_series": series,
        "window_measurement_count": len(observed),
        "window_trend": trend,
        "latest_as_of_window_end": {
            "date": latest_date,
            "weight_kg": round(latest_value, 2) if latest_value is not None else None,
            "freshness_days": freshness_days,
            "outside_requested_window": bool(latest_date and latest_date < dates[0]),
            "measurement_source": "not_provided_by_source",
        },
        "interpretation": "Descriptive scale-weight observations only; no BMI, body-composition, diagnosis or target weight is inferred.",
    }


def _recorded_activity_module(
    rows: list[dict[str, Any]],
    dates: list[str],
    latest_as_of_end: dict[str, Any] | None,
    source_status: str,
) -> dict[str, Any]:
    active_dates = sorted({str(row.get("date")) for row in rows if row.get("date")})
    duration_minutes = [
        value / 60
        for row in rows
        if (value := _duration_seconds(row.get("elapsed_time"))) is not None
    ]
    moving_minutes = [
        value / 60
        for row in rows
        if (value := _duration_seconds(row.get("moving_time"))) is not None
    ]
    distances_km = [
        value / 1000
        for row in rows
        if (value := _finite(row.get("distance"))) is not None and value >= 0
    ]
    calories = [
        value for row in rows if (value := _finite(row.get("calories"))) is not None and value >= 0
    ]
    average_heart_rates = [
        value for row in rows if (value := _finite(row.get("average_heart_rate"))) is not None
    ]
    maximum_heart_rates = [
        value for row in rows if (value := _finite(row.get("maximum_heart_rate"))) is not None
    ]
    training_loads = [
        value for row in rows if (value := _finite(row.get("training_load"))) is not None
    ]
    aerobic_effects = [
        value for row in rows if (value := _finite(row.get("aerobic_training_effect"))) is not None
    ]
    anaerobic_effects = [
        value for row in rows if (value := _finite(row.get("anaerobic_training_effect"))) is not None
    ]
    type_counts: dict[str, int] = {}
    for row in rows:
        activity_type = str(row.get("activity_type") or "unknown")
        type_counts[activity_type] = type_counts.get(activity_type, 0) + 1
    latest_date = str(latest_as_of_end.get("date")) if latest_as_of_end and latest_as_of_end.get("date") else None
    freshness_days = (date.fromisoformat(dates[-1]) - date.fromisoformat(latest_date)).days if latest_date else None
    if source_status != "available":
        status = source_status
    elif rows:
        status = "available"
    elif latest_as_of_end:
        status = "no_window_records_prior_available"
    else:
        status = "no_records"
    latest_duration = _duration_seconds(latest_as_of_end.get("elapsed_time")) if latest_as_of_end else None
    return {
        "status": status,
        "window_summary": {
            "record_count": len(rows),
            "active_days_with_records": len(active_dates),
            "requested_days": len(dates),
            "total_elapsed_minutes": round(sum(duration_minutes), 1),
            "total_moving_minutes": round(sum(moving_minutes), 1) if moving_minutes else None,
            "total_distance_km": round(sum(distances_km), 2) if distances_km else None,
            "total_calories": round(sum(calories), 1) if calories else None,
            "activity_type_counts": dict(sorted(type_counts.items())),
            "session_average_hr_median_bpm": round(statistics.median(average_heart_rates), 1)
            if average_heart_rates
            else None,
            "maximum_recorded_hr_bpm": round(max(maximum_heart_rates), 1) if maximum_heart_rates else None,
            "vendor_training_load_total": round(sum(training_loads), 1) if training_loads else None,
            "vendor_aerobic_training_effect_median": round(statistics.median(aerobic_effects), 2)
            if aerobic_effects
            else None,
            "vendor_anaerobic_training_effect_median": round(statistics.median(anaerobic_effects), 2)
            if anaerobic_effects
            else None,
            "event_stream_semantics": "days_without_records_are_not_inferred_as_zero_activity",
        },
        "latest_as_of_window_end": {
            "date": latest_date,
            "activity_type": str(latest_as_of_end.get("activity_type"))
            if latest_as_of_end and latest_as_of_end.get("activity_type") is not None
            else None,
            "elapsed_minutes": round(latest_duration / 60, 1) if latest_duration is not None else None,
            "freshness_days": freshness_days,
            "outside_requested_window": bool(latest_date and latest_date < dates[0]),
        },
        "privacy": {
            "location_fields_read": False,
            "activity_identifiers_read": False,
            "activity_names_or_descriptions_read": False,
            "raw_activity_files_read": False,
        },
        "interpretation": "Recorded-session summary only; absence of an activity record is not proof of inactivity or a training recommendation.",
    }
def _nightly_module(sleep_rows: list[dict[str, Any]], daily_rows: list[dict[str, Any]], dates: list[str]) -> dict[str, Any]:
    return {
        "sleep_respiration": _series_summary(sleep_rows, "sleep_respiration", dates, "breaths/min"),
        "waking_respiration": _series_summary(daily_rows, "waking_respiration", dates, "breaths/min"),
        "sleep_spo2_average": _series_summary(sleep_rows, "sleep_spo2_average", dates, "%"),
        "sleep_spo2_minimum": _series_summary(daily_rows, "spo2_minimum", dates, "%"),
        "interpretation": "Consumer-device trends only; no hypoxia or respiratory-disease threshold is applied.",
    }


def _fitness_estimates(connection, end: str) -> dict[str, Any]:
    columns = _table_columns(connection, "attributes")
    if not {"timestamp", "key", "value"}.issubset(columns):
        return {"status": "source_not_supported"}
    rows = connection.execute(
        "SELECT timestamp, key, value FROM attributes "
        "WHERE key IN ('vo2max_running', 'vo2max_cycling') "
        "ORDER BY timestamp DESC",
    ).fetchall()
    estimates: dict[str, dict[str, Any]] = {}
    for timestamp, key, value in rows:
        if key in estimates:
            continue
        number = _finite(value)
        if number is None:
            continue
        observed_at = str(timestamp)
        try:
            observed_date = datetime.fromisoformat(observed_at).date()
            age_days = (date.fromisoformat(end) - observed_date).days
        except ValueError:
            age_days = None
        estimates[str(key)] = {
            "estimate": round(number, 1),
            "unit": "ml/kg/min",
            "observed_at": observed_at,
            "age_days": age_days,
        }
    return {
        "status": "available" if estimates else "no_observations",
        "estimates": estimates,
        "trend_status": "single_latest_estimate_per_modality",
        "interpretation": "Garmin device estimate; modality-specific and not a laboratory measurement.",
    }


def _insight_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _insight_coverage(source: dict[str, Any]) -> dict[str, Any]:
    """Project numeric coverage only; never echo arbitrary source prose."""
    return {
        "status": source.get("status") if source.get("status") in {"complete", "partial", "no_observations"} else "unknown",
        **{key: _finite(source.get(key)) for key in (
            "requested_days", "observed_days", "missing_days", "coverage_fraction", "trailing_missing_days",
        )},
        "latest_observation_date": _insight_date(source.get("latest_observation_date")),
    }


def _problem_insights(modules: dict[str, Any], requested: dict[str, Any], data_status: str) -> dict[str, Any]:
    """Answer three bounded questions from summaries, without reading new data."""
    window = {"start": _insight_date(requested.get("start")), "end": _insight_date(requested.get("end"))}

    def observation(metric, pointer, value, unit, *, day=None, coverage=None, sample_count=None):
        return {
            "metric": metric, "value": _finite(value), "unit": unit,
            "observed_date": _insight_date(day), "window": dict(window),
            "coverage": _insight_coverage(coverage or {}),
            "sample_count": _finite(sample_count), "evidence_pointer": pointer,
        }

    def series(metric, pointer, source, unit):
        coverage = source.get("coverage") or {}
        day = _insight_date(source.get("latest_date"))
        has_evidence = (_finite(coverage.get("observed_days")) or 0) > 0 and day is not None
        return observation(metric, pointer, source.get("latest") if has_evidence else None, unit, day=day, coverage=coverage)

    def coverage_incomplete(observations):
        return any(item["coverage"]["status"] != "complete" for item in observations)

    def availability(observations, daily_observations):
        if not any(item["value"] is not None for item in observations):
            return "no_observations"
        return "partial_observation" if coverage_incomplete(daily_observations) else "descriptive_available"

    def item(identifier, question, observations, interpretation, qualification, explanations, missing, verification):
        return {
            "id": identifier, "question": question, "observations": observations,
            "interpretation": interpretation, "qualification": qualification,
            "possible_explanations": [{"status": "unverified_possibility", "text": text} for text in explanations],
            "missing_evidence": missing, "optional_action_ids": [],
            "next_observation_criteria": verification,
            "escalation_ref": "#/problem_insights/escalation",
            "provenance": {"method": "problem-insights.v1", "source": "existing_in_memory_profile_summaries", "reference": "references/health_profile.md"},
        }

    sleep = modules.get("sleep_health") or {}
    duration = series("sleep_duration", "/modules/sleep_health/duration", sleep.get("duration") or {}, "hours")
    regularity = sleep.get("duration_regularity") or {}
    timing = sleep.get("timing_regularity") or {}
    timing_status = timing.get("status") if timing.get("status") in {"eligible", "insufficient_observations", "timezone_required", "timezone_invalid", "duplicate_conflict", "mixed_timezone_semantics"} else "unknown"
    timing_basis = timing.get("timing_basis") if timing.get("timing_basis") in {"caller_timezone_applied_to_naive_source", "source_offsets_converted", "no_valid_pairs"} else "unknown"
    continuity = sleep.get("device_estimated_continuity") or {}
    formal = sleep.get("qualified_regularity") or {}
    formal_status = formal.get("status")
    if formal.get("epoch_comparable") is False:
        formal_status = "cross_epoch"
    elif formal_status in {"eligible", "partial_available"} and formal.get("epoch_comparable") is not True:
        formal_status = "epoch_unknown"
    elif formal_status not in {"eligible", "partial_available", "insufficient_window", "epoch_unknown", "cross_epoch", "duplicate_conflict", "insufficient_valid_nights", "source_not_supported", "timezone_unknown", "mixed_utc_offset"}:
        formal_status = "epoch_unknown"
    sleep_observations = [duration,
        observation("sleep_duration_dispersion", "/modules/sleep_health/duration_regularity", regularity.get("duration_sd_hours") if regularity.get("status") == "eligible" else None, "hours", sample_count=regularity.get("observed_nights")),
        observation("device_estimated_sleep_continuity", "/modules/sleep_health/device_estimated_continuity", continuity.get("median_percent") if (_finite(continuity.get("observed_nights")) or 0) > 0 else None, "percent", sample_count=continuity.get("observed_nights")),
    ]
    for metric, key in (("sleep_onset_dispersion", "sleep_onset"), ("wake_time_dispersion", "wake_time")):
        clock = timing.get(key) or {}
        sleep_observations.append(observation(metric, "/modules/sleep_health/timing_regularity", clock.get("circular_sd_hours") if timing_status == "eligible" else None, "hours", sample_count=clock.get("observed_nights")))
    sleep_available = duration["value"] is not None
    sleep_item = item(
        "sleep_opportunity_and_continuity", "记录能区分睡眠机会、作息离散度与设备估算连续性吗？", sleep_observations,
        "可描述本窗口的睡眠时长和设备估算值；记录时长不等于本人留给睡眠的机会，不能据此归因为睡眠机会不足或睡眠障碍。" if sleep_available else "缺少可核验的睡眠时长观测，不能判断睡眠机会或正式规律性；其他可用时点或设备估算仅按原字段描述。",
        {"status": availability(sleep_observations, [duration]), "formal_regularity_status": formal_status, "timing_description_status": timing_status, "timing_basis": timing_basis, "baseline_comparable": formal.get("epoch_comparable") if isinstance(formal.get("epoch_comparable"), bool) else None, "scope": "window_description_not_stable_trend"},
        ["睡眠机会安排与设备估算口径都可能影响记录，目前没有证据区分。"] if sleep_available else [],
        ["user_reported_sleep_opportunity", "subjective_daytime_sleepiness", "user_reported_sleep_schedule_context"] + (["qualified_regularity_evidence"] if formal_status not in {"eligible", "partial_available"} else []),
        ["下一次获授权观察时，分别核对时长、有效夜数和正式资格；本人如愿意补充睡眠机会与主观困倦，再讨论是否相符。"],
    )

    recovery = modules.get("autonomic_recovery") or {}
    hrv = recovery.get("hrv") or {}
    rhr_observation = series("resting_heart_rate", "/modules/autonomic_recovery/resting_heart_rate", recovery.get("resting_heart_rate") or {}, "bpm")
    hrv_observation = series("last_night_hrv", "/modules/autonomic_recovery/hrv/last_night", hrv.get("last_night") or {}, "ms")
    vendor = hrv.get("latest_vendor_context") or {}
    vendor_day = _insight_date(vendor.get("date"))
    vendor_values = [_finite(vendor.get(key)) for key in ("weekly_average_ms", "baseline_low_ms", "baseline_upper_ms")]
    vendor_available = vendor_day is not None and all(value is not None for value in vendor_values)
    if vendor_values[1] is not None and vendor_values[2] is not None and vendor_values[1] > vendor_values[2]:
        vendor_available = False
    vendor_observations = [
        observation(metric, "/modules/autonomic_recovery/hrv/latest_vendor_context/" + key, value if vendor_available else None, "ms", day=vendor_day)
        for metric, key, value in zip(("vendor_weekly_hrv", "vendor_baseline_low", "vendor_baseline_upper"), ("weekly_average_ms", "baseline_low_ms", "baseline_upper_ms"), vendor_values, strict=True)
    ]
    recovery_observations = [rhr_observation, hrv_observation, *vendor_observations]
    recovery_item = item(
        "recovery_observation", "HRV 与静息心率能说明恢复变化，还是仅有设备观察？", recovery_observations,
        "同日完整的 Garmin 7 日 HRV 与厂商区间可并列查看；它们不等于本技能的合格恢复比较。" if vendor_available else "目前不能展示完整的同日厂商区间；HRV 与静息心率各自可用值仍按各自日期描述。",
        {"status": availability(recovery_observations, [rhr_observation, hrv_observation]), "comparison_status": "epoch_unknown", "baseline_comparable": None, "scope": "source_observations_not_recovery_classification"},
        ["测量条件和生活情境可能与记录变化同时出现；当前不能区分，更不能从区间位置推断已经恢复。"] if any(obs["value"] is not None for obs in recovery_observations) else [],
        ["hrv_rhr_observation_attribution", "manufacturer_algorithm_epoch", "paired_historical_baseline", "analysis_comparability_evidence"] + (["same_date_vendor_interval"] if not vendor_available else []),
        ["下一次分别核对 HRV、静息心率观测日期与覆盖；只有同日历史样本和设备/算法证据都齐全后才重新评估比较资格。"],
    )

    movement = modules.get("movement") or {}
    week = movement.get("latest_7_days") or {}
    moderate_cov, vigorous_cov = week.get("moderate_coverage") or {}, week.get("vigorous_coverage") or {}
    moderate = _finite(week.get("moderate_minutes")) if (_finite(moderate_cov.get("observed_days")) or 0) > 0 else None
    vigorous = _finite(week.get("vigorous_minutes")) if (_finite(vigorous_cov.get("observed_days")) or 0) > 0 else None
    week_window = {"start": _insight_date(week.get("window_start")), "end": _insight_date(week.get("window_end"))}
    week_complete = all(cov.get("status") == "complete" and cov.get("observed_days") == 7 and cov.get("requested_days") == 7 for cov in (moderate_cov, vigorous_cov))
    goal_day = _insight_date(week.get("vendor_goal_date"))
    goal = _finite(week.get("vendor_goal_minutes")) if goal_day else None
    goal_comparable = week_complete and goal is not None and goal > 0 and moderate is not None and moderate >= 0 and vigorous is not None and vigorous >= 0
    activity_observations = [
        observation("moderate_activity", "/modules/movement/latest_7_days/moderate_minutes", moderate, "minutes", coverage=moderate_cov),
        observation("vigorous_activity", "/modules/movement/latest_7_days/vigorous_minutes", vigorous, "minutes", coverage=vigorous_cov),
        observation("device_goal", "/modules/movement/latest_7_days/vendor_goal_minutes", goal, "minutes", day=goal_day),
        observation("device_goal_progress", "/modules/movement/latest_7_days/vendor_goal_progress_percent", week.get("vendor_goal_progress_percent") if goal_comparable else None, "percent"),
    ]
    for obs in activity_observations:
        obs["window"] = dict(week_window)
    recorded = modules.get("recorded_activities") or {}
    record_summary = recorded.get("window_summary") or {}
    activity_observations.append(observation("days_with_recorded_activities", "/modules/recorded_activities/window_summary/active_days_with_records", record_summary.get("active_days_with_records") if recorded.get("status") in {"available", "no_records", "no_window_records_prior_available"} else None, "recorded_days"))
    # Empty event streams retain a record count of zero, not evidence of zero activity.
    movement_evidence = activity_observations if recorded.get("status") == "available" else activity_observations[:-1]
    activity_item = item(
        "activity_records_and_goal", "强度分钟分布和活动记录足以与设备中的个人目标对照吗？", activity_observations,
        "完整 7 日记录可与当前可见的设备目标作数值对照；这不是训练许可，也不代表本人仍采用该目标。" if goal_comparable else "当前不能作完整周目标进度判断；仅展示已有中等/剧烈分钟与有记录日数，不把空白活动日当成没有活动。",
        {"status": availability(movement_evidence, activity_observations[:2]), "goal_comparison_status": "eligible_device_goal_observation" if goal_comparable else "insufficient_week_coverage" if not week_complete else "goal_unavailable", "scope": "recorded_minutes_not_total_activity_or_prescription"},
        ["记录空白可能反映记录覆盖，而不是没有活动；有记录日数也不能证明每日活动分布完整。"] if not week_complete or recorded.get("status") != "available" else [],
        (["complete_seven_day_field_coverage"] if not week_complete else []) + (["dated_positive_device_goal"] if goal is None or goal <= 0 else ["confirmation_device_goal_is_still_intended"]) + ["daily_activity_distribution_context", "recorded_activity_completeness"],
        ["下一获授权窗口分别核对两类分钟覆盖、目标日期及活动记录完整性；请求不足 7 日时保留不足，不回读补窗。"],
    )

    items = [sleep_item, recovery_item, activity_item]
    # Coverage checks use daily fields and source availability, not optional goals
    # or event-stream blank days; valid descriptions do not remove source gaps.
    quality_ids = []
    for entry, daily_observations in (
        (sleep_item, [duration]),
        (recovery_item, [rhr_observation, hrv_observation]),
        (activity_item, activity_observations[:2]),
    ):
        if coverage_incomplete(daily_observations):
            quality_ids.append(entry["id"])
    if recorded.get("status") == "source_unavailable" and activity_item["id"] not in quality_ids:
        quality_ids.append(activity_item["id"])
    if regularity.get("status") == "duplicate_conflict" or formal_status == "duplicate_conflict" or timing_status == "duplicate_conflict":
        if sleep_item["id"] not in quality_ids:
            quality_ids.insert(0, sleep_item["id"])
    actions = []
    if quality_ids:
        actions.append({"id": "verify_observation_coverage", "optional": True, "applies_to": quality_ids, "text": "若愿意，可先核对缺口或冲突日期的来源记录及佩戴覆盖；缺口本身不证明未佩戴或同步失败，不自动同步。", "verification": "仅在来源确有观测后更新相应字段覆盖；缺失仍保留为空。"})
    if sleep_available and regularity.get("status") != "duplicate_conflict":
        actions.append({"id": "observe_sleep_opportunity", "optional": True, "applies_to": [sleep_item["id"]], "text": "如愿意，下次观察时补充本人可用于睡眠的时间与主观困倦，再对照设备时长；不以设备分数为目标。", "verification": "需要本人主动提供情境；当前不假定存在某种习惯，也不自动保存。"})
    if goal is not None and goal > 0 and (moderate is not None or vigorous is not None):
        actions.append({"id": "review_device_goal_context", "optional": True, "applies_to": [activity_item["id"]], "text": "如果设备中的目标仍是您愿意参考的目标，可对照已记录分钟及覆盖查看；不据此增加或减少训练。", "verification": "先确认目标含义与记录覆盖；不足整周不解释为未达目标。"})
    actions = actions[:2]
    for entry in items:
        entry["optional_action_ids"] = [action["id"] for action in actions if entry["id"] in action["applies_to"]]
    return {
        "schema": "problem-insights.v1", "data_status": data_status if data_status in {"complete", "partial", "no_data"} else "unknown",
        "items": items, "optional_actions": actions,
        "action_selection": "coverage_first_then_available_sleep_and_goal_evidence_max_two",
        "escalation": [
            {"condition": "若本人报告胸痛、严重呼吸困难、晕厥或疑似中风等急症信号", "response": "停止常规分析并立即联系当地急救服务。"},
            {"condition": "若变化持续且伴随明显症状或影响日常生活", "response": "可携带原始记录咨询合格医疗人员；不依据设备分数诊断。"},
        ],
        "privacy": {"additional_data_reads": False, "persisted": False, "raw_source_text_included": False},
    }


def build_profile(
    days: int,
    timezone_name: str | None,
    adult_guideline: bool,
    context_file: str | None = None,
) -> dict[str, Any]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    dates = [(start_date + timedelta(days=index)).isoformat() for index in range(days)]
    start = start_date.isoformat()
    end = end_date.isoformat()
    # Validate context against this exact window before any DB path resolution/read.
    context_records = _load_context(context_file, dates) if context_file is not None else None

    database_paths = [adapter.GARMIN_DB]
    try:
        adapter.resolve_database_path(adapter.ACTIVITIES_DB)
        activity_source_status = "available"
        database_paths.append(adapter.ACTIVITIES_DB)
    except FileNotFoundError:
        activity_source_status = "source_unavailable"

    with adapter.verified_database_read_window(database_paths) as read_window:
        connection = adapter.get_connection(adapter.GARMIN_DB)
        try:
            summary_table = adapter._get_summary_table_name(connection)
            if not summary_table:
                raise adapter.LocalDatabaseReadError("summary_table_missing")
            daily = _read_supported_rows(
                connection,
                summary_table,
                "day",
                {
                    "rhr": "resting_heart_rate",
                    "stress_avg": "stress_average",
                    "steps": "steps",
                    "moderate_activity_time": "moderate_activity_time",
                    "vigorous_activity_time": "vigorous_activity_time",
                    "intensity_time_goal": "intensity_time_goal",
                    "calories_active": "active_calories",
                    "distance": "distance",
                    "floors_up": "floors_up",
                    "bb_charged": "body_battery_charged",
                    "bb_max": "body_battery_high",
                    "bb_min": "body_battery_low",
                    "spo2_avg": "spo2_average",
                    "spo2_min": "spo2_minimum",
                    "rr_waking_avg": "waking_respiration",
                },
                start,
                end,
            )
            sleep = _read_supported_rows(
                connection,
                "sleep",
                "day",
                {
                    "start": "sleep_start",
                    "end": "sleep_end",
                    "total_sleep": "total_sleep",
                    "awake": "awake",
                    "deep_sleep": "deep_sleep",
                    "light_sleep": "light_sleep",
                    "rem_sleep": "rem_sleep",
                    "score": "sleep_score",
                    "avg_spo2": "sleep_spo2_average",
                    "avg_rr": "sleep_respiration",
                    "avg_stress": "sleep_stress_average",
                },
                start,
                end,
            )
            hrv = _read_supported_rows(
                connection,
                "hrv",
                "day",
                {
                    "weekly_avg": "weekly_average",
                    "last_night_avg": "last_night_average",
                    "last_night_5min_high": "last_night_5min_high",
                    "baseline_low": "baseline_low",
                    "baseline_upper": "baseline_upper",
                    "status": "status",
                },
                start,
                end,
            )
            weight_columns = _table_columns(connection, "weight")
            if {"day", "weight"}.issubset(weight_columns):
                weight = _read_supported_rows(
                    connection,
                    "weight",
                    "day",
                    {"weight": "weight_kg"},
                    start,
                    end,
                )
                latest_weight = _read_latest_supported_row(
                    connection,
                    "weight",
                    "day",
                    {"weight": "weight_kg"},
                    end,
                )
                weight_source_status = "available"
            else:
                weight = []
                latest_weight = None
                weight_source_status = "source_not_supported"
            fitness = _fitness_estimates(connection, end)
        finally:
            connection.close()
        if activity_source_status == "available":
            activity_connection = adapter.get_connection(adapter.ACTIVITIES_DB)
            try:
                activity_columns = _table_columns(activity_connection, "activities")
                if "start_time" in activity_columns:
                    activity_fields = {
                        "type": "activity_type",
                        "elapsed_time": "elapsed_time",
                        "moving_time": "moving_time",
                        "distance": "distance",
                        "avg_hr": "average_heart_rate",
                        "max_hr": "maximum_heart_rate",
                        "calories": "calories",
                        "training_load": "training_load",
                        "training_effect": "aerobic_training_effect",
                        "anaerobic_training_effect": "anaerobic_training_effect",
                    }
                    activities = _read_supported_rows(
                        activity_connection,
                        "activities",
                        "start_time",
                        activity_fields,
                        start,
                        end,
                    )
                    latest_activity = _read_latest_supported_row(
                        activity_connection,
                        "activities",
                        "start_time",
                        activity_fields,
                        end,
                    )
                else:
                    activities = []
                    latest_activity = None
                    activity_source_status = "source_not_supported"
            finally:
                activity_connection.close()
        else:
            activities = []
            latest_activity = None
    integrity = read_window.public_summary()

    requested = {"start": start, "end": end, "days": days}
    latest_observed = max(
        (
            str(row.get("date"))
            for collection in (daily, sleep, hrv, weight, activities)
            for row in collection
            if row.get("date")
        ),
        default=None,
    )
    modules = {
        "sleep_health": _sleep_module(sleep, dates, timezone_name),
        "autonomic_recovery": {
            "resting_heart_rate": _series_summary(daily, "resting_heart_rate", dates, "bpm"),
            "hrv": _hrv_module(hrv, dates),
            "interpretation": "Within-person descriptive context; no causal or disease attribution.",
        },
        "energy_dynamics": _body_battery_module(daily, dates),
        "movement": _movement_module(daily, dates, adult_guideline),
        "body_weight": _weight_module(weight, dates, latest_weight, weight_source_status),
        "recorded_activities": _recorded_activity_module(
            activities,
            dates,
            latest_activity,
            activity_source_status,
        ),
        "nightly_physiology": _nightly_module(sleep, daily, dates),
        "fitness_estimates": fitness,
    }
    core_coverages = [
        modules["sleep_health"]["duration"]["coverage"]["status"],
        modules["autonomic_recovery"]["resting_heart_rate"]["coverage"]["status"],
        modules["autonomic_recovery"]["hrv"]["last_night"]["coverage"]["status"],
        modules["energy_dynamics"]["high"]["coverage"]["status"],
        modules["movement"]["steps"]["coverage"]["status"],
        modules["nightly_physiology"]["sleep_respiration"]["coverage"]["status"],
    ]
    if not latest_observed:
        data_status = "no_data"
    elif all(item == "complete" for item in core_coverages):
        data_status = "complete"
    else:
        data_status = "partial"
    freshness_days = (
        (end_date - date.fromisoformat(latest_observed)).days
        if latest_observed
        else None
    )
    result = {
        "schema": "garmin-health-profile.v2",
        "status": "ok" if latest_observed else "no_data",
        "data_status": data_status,
        "source": "local",
        "requested_window": requested,
        "latest_observation_date": latest_observed,
        "freshness_days": freshness_days,
        "modules": modules,
        "problem_insights": _problem_insights(modules, requested, data_status),
        "guidance_contract": {
            "priority_order": [
                "Verify data coverage and freshness before interpreting change.",
                "Legacy sleep regularity status describes availability only; use qualified_regularity for formal eligibility. Short-window variability is not qualified regularity or a comparable baseline.",
                "Use weekly movement distribution and the user's Garmin goal before population thresholds.",
                "Treat body weight as a sparse measurement series and disclose freshness before describing change.",
                "Summarize recorded activities without reading identifiers, names, descriptions, coordinates or raw tracks.",
                "Interpret HRV, stress and Body Battery together because their upstream signals overlap.",
                "Escalate persistent changes with symptoms to a qualified clinician using raw records.",
            ],
            "composite_health_score": "not_scored",
            "training_clearance": "not_provided",
            "diagnosis": "not_provided",
            "medication_or_supplement_advice": "not_provided",
        },
        "provenance": {
            "network_accessed": False,
            "persisted": False,
            "database_integrity": {
                "status": integrity["status"],
                "databases": [item["database"] for item in integrity["databases"]],
            },
            "method_version": "health-profile.v2",
        },
    }
    if context_records is not None:
        review = _context_review(context_records, dates, sleep)
        result["user_context_review"] = review
        result["problem_insights"]["privacy"].update(additional_data_reads=True, explicit_user_context_read=True, additional_database_reads=False)
        sleep_insight = result["problem_insights"]["items"][0]
        sleep_insight["user_context_ref"] = "/user_context_review"
        for missing, count_key in (("user_reported_sleep_opportunity", "sleep_opportunity_recorded_days"), ("subjective_daytime_sleepiness", "sleepiness_recorded_days")):
            count = review["summary"][count_key]
            if count:
                sleep_insight["missing_evidence"].remove(missing)
                if count < days:
                    sleep_insight["missing_evidence"].append("complete_" + missing)
        if review["summary"]["paired_sleep_duration_days"]:
            sleep_insight["interpretation"] = "本人提供的睡眠机会与同日设备时长仅作描述性并列；主观记录不证明设备可比，也不能据此判断睡眠障碍、因果或行动效果。"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded local Garmin health profile")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--source", choices=["local"], required=True)
    parser.add_argument("--timezone", help="IANA timezone for naive sleep timestamps")
    parser.add_argument("--adult-18-64-guideline", action="store_true")
    parser.add_argument("--context-file", help="Explicitly selected local user-context JSON; not saved")
    parser.add_argument("--allow-health-data", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_health_data:
        print(json.dumps({"status": "authorization_error", "error_code": "HEALTH_DATA_AUTH_REQUIRED"}), file=sys.stderr)
        return 2
    if args.allow_network:
        print(json.dumps({"status": "authorization_error", "error_code": "NETWORK_NOT_ALLOWED_FOR_LOCAL_SOURCE"}), file=sys.stderr)
        return 2
    if args.days < 1 or args.days > MAX_DAYS:
        print(json.dumps({"status": "invalid_window", "error_code": "DAYS_OUT_OF_RANGE", "maximum_days": MAX_DAYS}), file=sys.stderr)
        return 2

    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = build_profile(args.days, args.timezone, args.adult_18_64_guideline, args.context_file)
    except ContextValidationError:
        print(json.dumps({"status": "invalid_context", "error_code": "CONTEXT_INVALID"}), file=sys.stderr)
        return 2
    except ContextReadError as exc:
        print(json.dumps({"status": "read_error", "error_code": "CONTEXT_READ_ERROR", "error_type": exc.error_type, "errno": exc.errno}), file=sys.stderr)
        return 4
    except FileNotFoundError as exc:
        result = {"status": "no_data", "error_code": "LOCAL_DATABASE_UNAVAILABLE", "error_type": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 3
    except (adapter.LocalDatabaseReadError, adapter.LocalDatabaseChangedError) as exc:
        result = {"status": "read_error", "error_code": str(exc), "error_type": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 4

    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "ok" else 3


if __name__ == "__main__":
    raise SystemExit(main())
