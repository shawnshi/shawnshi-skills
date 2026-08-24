#!/usr/bin/env python3
"""Build a bounded, local-only Garmin multidimensional health profile."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import statistics
import sys
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import garmin_sqlite_adapter as adapter


MAX_DAYS = 366


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
    for row in rows:
        try:
            start = datetime.fromisoformat(str(row.get("sleep_start")))
            end = datetime.fromisoformat(str(row.get("sleep_end")))
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
    duration_values = [
        value / 3600
        for row in rows
        if (value := _duration_seconds(row.get("total_sleep"))) is not None and value > 0
    ]
    continuity_values = []
    for row in rows:
        total = _duration_seconds(row.get("total_sleep"))
        awake_seconds = _duration_seconds(row.get("awake"))
        if total is not None and total > 0 and awake_seconds is not None and awake_seconds >= 0:
            denominator = total + awake_seconds
            if denominator > 0:
                continuity_values.append(total / denominator * 100)
    regularity = {
        "status": "eligible" if len(duration_values) >= 3 else "insufficient_observations",
        "observed_nights": len(duration_values),
        "duration_sd_hours": round(statistics.stdev(duration_values), 2)
        if len(duration_values) >= 3
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
    return {
        "duration": duration,
        "device_score": score,
        "device_estimated_awake_time": awake,
        "duration_regularity": regularity,
        "timing_regularity": _sleep_timing(rows, timezone_name),
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


def build_profile(
    days: int,
    timezone_name: str | None,
    adult_guideline: bool,
) -> dict[str, Any]:
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    dates = [(start_date + timedelta(days=index)).isoformat() for index in range(days)]
    start = start_date.isoformat()
    end = end_date.isoformat()

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
    return {
        "schema": "garmin-health-profile.v2",
        "status": "ok" if latest_observed else "no_data",
        "data_status": data_status,
        "source": "local",
        "requested_window": requested,
        "latest_observation_date": latest_observed,
        "freshness_days": freshness_days,
        "modules": modules,
        "guidance_contract": {
            "priority_order": [
                "Verify data coverage and freshness before interpreting change.",
                "Use sleep timing and duration variability as modifiable observation targets, not diagnoses.",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded local Garmin health profile")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--source", choices=["local"], required=True)
    parser.add_argument("--timezone", help="IANA timezone for naive sleep timestamps")
    parser.add_argument("--adult-18-64-guideline", action="store_true")
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
            result = build_profile(args.days, args.timezone, args.adult_18_64_guideline)
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
