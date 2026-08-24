#!/usr/bin/env python3
"""Render a local, non-diagnostic Garmin trends dashboard."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)

sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import LIVE_SUMMARY_COMPONENTS, fetch_summary, get_date_range
from garmin_intelligence import (
    HAS_SQLITE,
    MIN_PAIRED_BASELINE_DAYS,
    analyze_baseline_change,
    analyze_health_patterns,
    fetch_local_summary,
    generate_chinese_insight,
    parse_period,
)
from report_output import build_report_paths

TEMPLATE_FILE = Path(__file__).parent.parent / "assets" / "dashboard_v2.html"
DASHBOARD_LIVE_OPERATION = "dashboard_live"
DASHBOARD_SCHEMA = "dashboard.v3"
DASHBOARD_MIN_HEATMAP_DAYS = 14
DASHBOARD_DEFAULT_COMPONENTS = (
    "sleep",
    "hrv",
    "body_battery",
    "heart_rate",
    "stress",
)
DASHBOARD_SERIES_FIELDS = (
    "dates",
    "rhr_bpm",
    "hrv_ms",
    "sleep_total_h",
    "sleep_deep_h",
    "sleep_rem_h",
    "sleep_light_h",
    "sleep_respiration_brpm",
    "sleep_spo2_pct",
    "body_battery_high",
    "body_battery_low",
    "steps",
    "stress_avg",
)
DASHBOARD_COMPONENT_DATA_KEYS = {
    "sleep": ("sleep",),
    "hrv": ("hrv",),
    "body_battery": ("body_battery",),
    "heart_rate": ("heart_rate",),
    "activities": ("activities",),
    "stress": ("stress",),
    "training_load_series": ("training_load_series", "pmc", "training_status"),
}
DATE_SERIES = (
    "sleep",
    "hrv",
    "body_battery",
    "heart_rate",
    "activities",
    "stress",
    "training_load_series",
    "biomechanics",
    "daily_summary",
    "pmc",
)


def _normalize_dashboard_components(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        requested = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple)):
        requested = list(value)
    else:
        raise ValueError("dashboard_components_required")
    if not requested or any(not isinstance(item, str) for item in requested):
        raise ValueError("dashboard_components_required")
    if len(set(requested)) != len(requested):
        raise ValueError("dashboard_component_duplicate")
    if set(requested) - set(LIVE_SUMMARY_COMPONENTS):
        raise ValueError("dashboard_component_invalid")
    return tuple(item for item in LIVE_SUMMARY_COMPONENTS if item in requested)


def _validate_live_request_scope(
    days: int, request: dict[str, object] | None
) -> tuple[str, str]:
    required_keys = {"chart", "source", "start", "end", "components"}
    if (
        not isinstance(days, int)
        or isinstance(days, bool)
        or days < 1
        or not isinstance(request, dict)
        or set(request) != required_keys
        or request.get("chart") not in {"dashboard", "overlay"}
        or request.get("source") != "live"
    ):
        raise RuntimeError("LIVE_SCOPE_INVALID")
    try:
        components = _normalize_dashboard_components(request.get("components"))
    except ValueError as exc:
        raise RuntimeError("LIVE_SCOPE_INVALID") from exc
    if request.get("components") != list(components):
        raise RuntimeError("LIVE_SCOPE_INVALID")
    start = request.get("start")
    end = request.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise RuntimeError("LIVE_SCOPE_INVALID")
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
    except ValueError as exc:
        raise RuntimeError("LIVE_SCOPE_INVALID") from exc
    if start_date > end_date or (end_date - start_date).days + 1 != days:
        raise RuntimeError("LIVE_SCOPE_INVALID")
    return start, end


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict("records")
        except (TypeError, ValueError):
            return []
    return []


def _record_date(record: dict[str, Any]) -> str | None:
    for key in ("date", "day", "calendarDate", "calendar_date", "start_time"):
        value = record.get(key)
        if value:
            candidate = str(value).strip()[:10]
            try:
                parsed = datetime.strptime(candidate, "%Y-%m-%d")
            except (TypeError, ValueError):
                continue
            if parsed.strftime("%Y-%m-%d") == candidate:
                return candidate
    return None


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 1) if math.isfinite(value) else None
    return value


def _seconds_to_hours(value: Any) -> float | None:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    try:
        return round(float(cleaned) / 3600, 3)
    except (TypeError, ValueError):
        return None


def _dated_map(records: list[dict[str, Any]], field: str, transform=_clean_value) -> dict:
    """Return one value per day without silently choosing a conflicting duplicate."""
    result = {}
    conflicts = set()
    for record in records:
        date = _record_date(record)
        if not date or date in conflicts:
            continue
        value = transform(record.get(field))
        if date not in result:
            result[date] = value
        elif result[date] is None and value is not None:
            result[date] = value
        elif value is not None and result[date] is not None and value != result[date]:
            result[date] = None
            conflicts.add(date)
    return result


def _all_dates(summary_data: dict[str, Any]) -> list[str]:
    dates = {
        date
        for series_name in DATE_SERIES
        for record in _records(summary_data.get(series_name, []))
        if (date := _record_date(record))
    }
    return sorted(dates)


def build_heatmap_data(summary_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve absent sleep scores as null instead of fabricating zero."""
    scores = _dated_map(_records(summary_data.get("sleep", [])), "sleep_score")
    return [{"date": day, "score": scores[day]} for day in sorted(scores)]


def build_overlay_data(summary_data: dict[str, Any]) -> dict[str, Any] | None:
    """Align every metric to the union of available observation dates."""
    dates = _all_dates(summary_data)
    if not dates:
        return None

    sleep = _records(summary_data.get("sleep", []))
    stress = _records(summary_data.get("stress", []))
    battery = _records(summary_data.get("body_battery", []))
    heart_rate = _records(summary_data.get("heart_rate", []))
    hrv = _records(summary_data.get("hrv", []))
    activities = _records(summary_data.get("activities", []))
    loads = _records(summary_data.get("training_load_series", []))
    biomechanics = _records(summary_data.get("biomechanics", []))
    daily = _records(summary_data.get("daily_summary", []))
    pmc = _records(summary_data.get("pmc", []))

    def complete_duration_hours(record: dict[str, Any]) -> float | None:
        high = _clean_value(record.get("high_stress_duration"))
        medium = _clean_value(record.get("medium_stress_duration"))
        if high is None or medium is None:
            return None
        return round((float(high) + float(medium)) / 3600, 3)

    stress_hours = {
        date: complete_duration_hours(record)
        for record in stress
        if (date := _record_date(record))
    }
    weighted_dissipation = {}
    for record in stress:
        date = _record_date(record)
        high = _clean_value(record.get("high_stress_duration"))
        medium = _clean_value(record.get("medium_stress_duration"))
        if date:
            weighted_dissipation[date] = (
                round((float(high) + float(medium) * 0.5) / 3600, 1)
                if high is not None and medium is not None
                else None
            )

    steps_map = _dated_map(stress, "steps")
    for date, value in _dated_map(daily, "steps").items():
        if value is not None:
            steps_map[date] = value

    calories_map: dict[str, float] = {}
    temperature_map = {}
    activity_maps = {"running": {}, "cycling": {}, "hiking": {}, "hiit": {}}
    for activity in activities:
        date = _record_date(activity)
        if not date:
            continue
        calories = _clean_value(activity.get("calories"))
        temperature = _clean_value(activity.get("temperature"))
        if calories is not None:
            calories_map[date] = calories_map.get(date, 0.0) + float(calories)
            label = (
                str(activity.get("activity_type") or "")
                + " "
                + str(activity.get("activity_name") or "")
            ).lower()
            category = None
            if "run" in label or "jog" in label:
                category = "running"
            elif "cycl" in label or "bik" in label:
                category = "cycling"
            elif any(term in label for term in ("hik", "mountaineer", "walk")):
                category = "hiking"
            elif any(
                term in label
                for term in ("hiit", "training", "fitness", "strength", "elliptical")
            ):
                category = "hiit"
            if category:
                target = activity_maps[category]
                target[date] = target.get(date, 0.0) + float(calories)
        if temperature is not None:
            temperature_map[date] = temperature

    device_records = _records(summary_data.get("device_info", []))
    firmware_versions = sorted(
        {
            str(record["software_version"])
            for record in device_records
            if _clean_value(record.get("software_version")) is not None
        }
    )

    maps = {
        "stress_h": stress_hours,
        "bb_max": _dated_map(battery, "highest"),
        "bb_min": _dated_map(battery, "lowest"),
        "rhr": _dated_map(heart_rate, "resting_hr"),
        "max_hr": _dated_map(heart_rate, "max_hr"),
        "avg_hr": _dated_map(sleep, "avg_hr"),
        "sleep_h": _dated_map(sleep, "sleep_time_seconds", _seconds_to_hours),
        "sleep_deep_h": _dated_map(sleep, "deep_sleep_seconds", _seconds_to_hours),
        "sleep_rem_h": _dated_map(sleep, "rem_sleep_seconds", _seconds_to_hours),
        "sleep_light_h": _dated_map(sleep, "light_sleep_seconds", _seconds_to_hours),
        "sleep_score": _dated_map(sleep, "sleep_score"),
        "sleep_respiration": _dated_map(sleep, "avg_respiration"),
        "hrv": _dated_map(hrv, "last_night_avg"),
        "calories": calories_map,
        "steps": steps_map,
        "acute_load": _dated_map(loads, "acute_load"),
        "act_running": activity_maps["running"],
        "act_cycling": activity_maps["cycling"],
        "act_hiking": activity_maps["hiking"],
        "act_hiit": activity_maps["hiit"],
        "ctl": _dated_map(pmc, "ctl"),
        "atl": _dated_map(pmc, "atl"),
        "tsb": _dated_map(pmc, "tsb"),
        "pmc_load": _dated_map(pmc, "daily_friction_load"),
        "weighted_dissipation": weighted_dissipation,
        "spo2_history": _dated_map(sleep, "avg_spo2"),
        "waking_rr": _dated_map(daily, "rr_waking_avg"),
        "sweat_loss": _dated_map(daily, "sweat_loss"),
        "gct_trend": _dated_map(biomechanics, "avg_ground_contact_time"),
        "temperature_trend": temperature_map,
        "stress_avg": _dated_map(stress, "avg_stress"),
    }
    aligned = {key: [values.get(date) for date in dates] for key, values in maps.items()}
    aligned.update(
        {
            "dates": dates,
            "readiness": [None for _date in dates],
            "software_version": ", ".join(firmware_versions) or None,
        }
    )
    return aligned


def _calendar_dates(start: str, end: str) -> list[str]:
    start_day = datetime.strptime(start, "%Y-%m-%d")
    end_day = datetime.strptime(end, "%Y-%m-%d")
    if start_day > end_day:
        raise ValueError("INVALID_PERIOD_SCOPE")
    return [
        (start_day + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range((end_day - start_day).days + 1)
    ]


def build_dashboard_series(
    summary_data: dict[str, Any], *, requested_start: str, requested_end: str
) -> dict[str, list[Any]]:
    """Project only rendered health series onto every requested calendar date."""
    dates = _calendar_dates(requested_start, requested_end)
    overlay = build_overlay_data(summary_data) or {"dates": []}
    source_dates = overlay.get("dates") or []
    source_indexes = {day: index for index, day in enumerate(source_dates)}
    mapping = {
        "rhr_bpm": "rhr",
        "hrv_ms": "hrv",
        "sleep_total_h": "sleep_h",
        "sleep_deep_h": "sleep_deep_h",
        "sleep_rem_h": "sleep_rem_h",
        "sleep_light_h": "sleep_light_h",
        "sleep_respiration_brpm": "sleep_respiration",
        "sleep_spo2_pct": "spo2_history",
        "body_battery_high": "bb_max",
        "body_battery_low": "bb_min",
        "steps": "steps",
        "stress_avg": "stress_avg",
    }
    series: dict[str, list[Any]] = {"dates": dates}
    for target, source in mapping.items():
        values = overlay.get(source) or []
        series[target] = [
            values[source_indexes[day]]
            if day in source_indexes and source_indexes[day] < len(values)
            else None
            for day in dates
        ]
    return series


def _coverage_entry(
    dates: list[str],
    value_sets: list[list[Any]],
    *,
    require_all: bool = False,
    source_status: str | None = None,
) -> dict[str, Any]:
    observed_dates = []
    observed_zero_dates = []
    for index, day in enumerate(dates):
        cleaned = [
            _clean_value(values[index])
            for values in value_sets
            if index < len(values)
        ]
        observed = [value is not None for value in cleaned]
        if observed and (all(observed) if require_all else any(observed)):
            observed_dates.append(day)
            if any(value == 0 for value in cleaned if value is not None):
                observed_zero_dates.append(day)
    requested_days = len(dates)
    observed_days = len(observed_dates)
    if source_status in {"error", "not_requested"}:
        status = source_status
    else:
        status = (
            "no_data"
            if observed_days == 0
            else "complete"
            if observed_days == requested_days
            else "partial"
        )
    missing_ranges = []
    current_start = None
    for day in dates:
        if day not in observed_dates and current_start is None:
            current_start = day
        if day in observed_dates and current_start is not None:
            prior_day = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime(
                "%Y-%m-%d"
            )
            range_days = (
                datetime.strptime(prior_day, "%Y-%m-%d")
                - datetime.strptime(current_start, "%Y-%m-%d")
            ).days + 1
            missing_ranges.append(
                {"start": current_start, "end": prior_day, "days": range_days}
            )
            current_start = None
    if current_start is not None and dates:
        range_days = (
            datetime.strptime(dates[-1], "%Y-%m-%d")
            - datetime.strptime(current_start, "%Y-%m-%d")
        ).days + 1
        missing_ranges.append(
            {"start": current_start, "end": dates[-1], "days": range_days}
        )
    streaks_are_known = status not in {"error", "not_requested"}
    longest_missing = (
        max((item["days"] for item in missing_ranges), default=0)
        if streaks_are_known
        else None
    )
    current_missing = (
        missing_ranges[-1]["days"]
        if streaks_are_known and missing_ranges and missing_ranges[-1]["end"] == dates[-1]
        else 0
        if streaks_are_known
        else None
    )
    return {
        "status": status,
        "observed_days": observed_days,
        "requested_days": requested_days,
        "coverage_ratio": (
            round(observed_days / requested_days, 3) if requested_days else 0.0
        ),
        "first_date": observed_dates[0] if observed_dates else None,
        "last_date": observed_dates[-1] if observed_dates else None,
        "missing_days": max(0, requested_days - observed_days),
        "observed_zero_days": len(observed_zero_dates),
        "longest_missing_streak_days": longest_missing,
        "current_missing_streak_days": current_missing,
    }


def _latest_kpi(
    dates: list[str], values: list[Any], *, unit: str, source_type: str
) -> dict[str, Any]:
    for day, value in reversed(list(zip(dates, values))):
        cleaned = _clean_value(value)
        if cleaned is not None:
            return {
                "value": cleaned,
                "unit": unit,
                "observed_date": day,
                "source_type": source_type,
            }
    return {
        "value": None,
        "unit": unit,
        "observed_date": None,
        "source_type": source_type,
    }


def _stress_snapshot(
    summary_data: dict[str, Any], *, requested_start: str, requested_end: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_date: dict[str, dict[str, Any] | None] = {}
    for record in _records(summary_data.get("stress", [])):
        day = _record_date(record)
        if not day or day < requested_start or day > requested_end:
            continue
        values = {
            "avg": _clean_value(record.get("avg_stress")),
            "high_h": _seconds_to_hours(record.get("high_stress_duration")),
            "medium_h": _seconds_to_hours(record.get("medium_stress_duration")),
            "rest_h": _seconds_to_hours(record.get("rest_stress_duration")),
        }
        if not any(value is not None for value in values.values()):
            continue
        previous = by_date.get(day)
        if previous is not None and previous != values:
            by_date[day] = None
        elif day not in by_date:
            by_date[day] = values

    observed_dates = sorted(day for day, values in by_date.items() if values is not None)
    requested_dates = _calendar_dates(requested_start, requested_end)
    coverage = _coverage_entry(
        requested_dates,
        [[1 if day in observed_dates else None for day in requested_dates]],
    )
    if not observed_dates:
        return (
            {
                "value": None,
                "unit": "Garmin 分数",
                "observed_date": None,
                "source_type": "garmin_proprietary_metric",
                "details": {"high_h": None, "medium_h": None, "rest_h": None},
            },
            coverage,
        )
    latest_day = observed_dates[-1]
    values = by_date[latest_day] or {}
    return (
        {
            "value": values.get("avg"),
            "unit": "Garmin 分数",
            "observed_date": latest_day,
            "source_type": "garmin_proprietary_metric",
            "details": {
                "high_h": values.get("high_h"),
                "medium_h": values.get("medium_h"),
                "rest_h": values.get("rest_h"),
            },
        },
        coverage,
    )


def _baseline_view(summary_data: dict[str, Any]) -> dict[str, Any]:
    result = analyze_baseline_change(summary_data)
    metrics = result.get("metrics") or {}
    epoch = result.get("epoch_comparability") or {}
    current = _clean_value(metrics.get("current_rhr"))
    baseline = _clean_value(metrics.get("baseline_rhr"))
    algorithm_epoch = epoch.get("analysis_algorithm_epoch")
    qualified = (
        result.get("status") == "ok"
        and epoch.get("comparable") is True
        and algorithm_epoch not in (None, "")
        and baseline not in (None, 0)
        and current is not None
        and int(metrics.get("paired_baseline_days") or 0)
        >= MIN_PAIRED_BASELINE_DAYS
    )
    if qualified:
        status = "qualified"
    elif result.get("status") == "insufficient_baseline":
        status = "insufficient_baseline"
    elif epoch.get("comparable") is False:
        status = "cross_epoch"
    elif epoch.get("comparable") is None:
        status = "epoch_unknown"
    elif result.get("status") == "unclassifiable":
        status = "unclassifiable"
    else:
        status = "not_comparable"
    delta_pct = (
        round((float(current) - float(baseline)) / float(baseline) * 100, 1)
        if qualified
        else None
    )
    return {
        "status": status,
        "qualified": qualified,
        "paired_current_date": result.get("paired_observation_date"),
        "paired_baseline_days": int(metrics.get("paired_baseline_days") or 0),
        "required_days": int(
            metrics.get("required_paired_baseline_days")
            or MIN_PAIRED_BASELINE_DAYS
        ),
        "baseline_start": metrics.get("baseline_start_date"),
        "baseline_end": metrics.get("baseline_end_date"),
        "epoch_status": epoch.get("status") or "epoch_unknown",
        "method": "prior_same_date_mean",
        "analysis_algorithm_epoch": algorithm_epoch,
        "rhr": {
            "current": current,
            "baseline": baseline,
            "delta_bpm": (
                round(float(current) - float(baseline), 1)
                if current is not None and baseline is not None
                else None
            ),
            "delta_pct": delta_pct,
        },
        "hrv": {
            "current": _clean_value(metrics.get("current_hrv")),
            "baseline": _clean_value(metrics.get("baseline_hrv")),
        },
        "limitations": list(result.get("limitations") or []),
    }


def _source_component_status(
    summary_data: dict[str, Any], component: str, selected_components: tuple[str, ...]
) -> str | None:
    if component not in selected_components:
        return "not_requested"
    status = (summary_data.get("component_status") or {}).get(component, {}).get(
        "status"
    )
    return status if status in {"error", "not_requested"} else None


def _safe_integrity(summary_data: dict[str, Any]) -> dict[str, Any]:
    integrity = summary_data.get("data_integrity") or {}
    database_count = sum(
        1
        for item in integrity.get("databases") or []
        if isinstance(item, dict) and item.get("database")
    )
    return {
        "status": integrity.get("status") or "not_available",
        "database_count": database_count,
    }


def _safe_device_epoch(
    summary_data: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    devices = _records(summary_data.get("device_info", []))
    serials = {
        str(item.get("serial_number"))
        for item in devices
        if item.get("serial_number") not in (None, "")
    }
    firmware_versions = sorted(
        {
            str(item.get("software_version"))
            for item in devices
            if item.get("software_version") not in (None, "")
        }
    )
    evidence = summary_data.get("measurement_epoch_evidence") or {}
    return {
        "status": baseline.get("epoch_status") or "epoch_unknown",
        "device_count": len(serials) if serials else len(devices),
        "firmware_versions": firmware_versions,
        "analysis_algorithm_epoch": baseline.get("analysis_algorithm_epoch"),
        "manufacturer_algorithm_epoch": evidence.get(
            "manufacturer_algorithm_epoch", "not_available"
        ),
    }


def _scope_dashboard_source(
    summary_data: dict[str, Any], components: tuple[str, ...]
) -> dict[str, Any]:
    """Drop unrequested and non-rendering source fields before any view logic runs."""
    source_summary = (
        summary_data.get("summary")
        if isinstance(summary_data.get("summary"), dict)
        else {}
    )
    scoped: dict[str, Any] = {
        "status": summary_data.get("status"),
        "summary": {
            "period": source_summary.get("period"),
            "days": source_summary.get("days"),
        },
        "is_stale": summary_data.get("is_stale"),
        "data_integrity": summary_data.get("data_integrity"),
    }
    for component in components:
        for key in DASHBOARD_COMPONENT_DATA_KEYS[component]:
            source_value = summary_data.get(key)
            scoped[key] = (
                source_value
                if source_value is not None
                else {}
                if key == "training_status"
                else []
            )

    source_status = (
        summary_data.get("component_status")
        if isinstance(summary_data.get("component_status"), dict)
        else {}
    )
    scoped["component_status"] = {
        component: {
            key: source_status.get(component, {}).get(key)
            for key in ("status", "coverage_semantics", "zero_semantics")
        }
        for component in components
        if isinstance(source_status.get(component), dict)
    }

    scoped["device_info"] = [
        {
            "serial_number": item.get("serial_number"),
            "software_version": item.get("software_version"),
        }
        for item in _records(summary_data.get("device_info", []))
    ]
    source_epoch = (
        summary_data.get("measurement_epoch_evidence")
        if isinstance(summary_data.get("measurement_epoch_evidence"), dict)
        else {}
    )
    scoped["measurement_epoch_evidence"] = {
        "analysis_algorithm_epoch": source_epoch.get("analysis_algorithm_epoch"),
        "manufacturer_algorithm_epoch": source_epoch.get(
            "manufacturer_algorithm_epoch"
        ),
        "firmware_history": [
            {
                "timestamp": item.get("timestamp"),
                "serial_number": item.get("serial_number"),
                "software_version": item.get("software_version"),
            }
            for item in _records(source_epoch.get("firmware_history", []))
        ],
    }
    return scoped


def _unrequested_baseline() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "qualified": False,
        "paired_current_date": None,
        "paired_baseline_days": 0,
        "required_days": MIN_PAIRED_BASELINE_DAYS,
        "baseline_start": None,
        "baseline_end": None,
        "epoch_status": "not_evaluated",
        "method": "prior_same_date_mean",
        "analysis_algorithm_epoch": None,
        "rhr": {
            "current": None,
            "baseline": None,
            "delta_bpm": None,
            "delta_pct": None,
        },
        "hrv": {"current": None, "baseline": None},
        "limitations": [
            "Baseline comparison requires both heart_rate and hrv components."
        ],
    }


def _dashboard_overall_narrative(
    summary_data: dict[str, Any],
    *,
    coverage: dict[str, dict[str, Any]],
    kpis: dict[str, dict[str, Any]],
    series: dict[str, list[Any]],
    baseline: dict[str, Any],
    requested_start: str,
    requested_end: str,
    legacy_insight: dict[str, Any],
) -> str:
    """Create scope-aware prose without printing unavailable metrics as facts."""
    def display_number(value: Any) -> str | None:
        cleaned = _clean_value(value)
        if cleaned is None:
            return None
        return str(int(cleaned)) if float(cleaned).is_integer() else str(cleaned)

    period = (
        (summary_data.get("summary") or {}).get("period")
        or legacy_insight.get("period")
        or f"{requested_start} to {requested_end}"
    )
    freshness = "源标记可能陈旧" if summary_data.get("is_stale") else "源未标记为陈旧"
    observations = []
    metric_specs = (
        ("rhr", "rhr", "静息心率"),
        ("hrv", "hrv", "HRV"),
        ("sleep", "sleep_total", "睡眠总时长"),
        ("stress", "stress", "Garmin 日均压力"),
    )
    for kpi_key, coverage_key, label in metric_specs:
        entry = coverage[coverage_key]
        if entry["status"] == "not_requested":
            continue
        item = kpis[kpi_key]
        value = display_number(item.get("value"))
        observations.append(
            f"{label}无有效观测"
            if value is None
            else f"{label} {value} {item.get('unit') or ''}（{item.get('observed_date')}）"
        )

    battery_coverage = coverage["body_battery"]
    if battery_coverage["status"] != "not_requested":
        battery_observation = None
        for day, high, low in reversed(
            list(
                zip(
                    series["dates"],
                    series["body_battery_high"],
                    series["body_battery_low"],
                )
            )
        ):
            high_value = display_number(high)
            low_value = display_number(low)
            if high_value is not None or low_value is not None:
                battery_observation = (
                    f"Body Battery 最高 {high_value if high_value is not None else '缺失'}、"
                    f"最低 {low_value if low_value is not None else '缺失'}（{day}）"
                )
                break
        observations.append(battery_observation or "Body Battery 无有效观测")

    steps_coverage = coverage["steps"]
    if steps_coverage["status"] != "not_requested":
        steps_observation = next(
            (
                f"每日步数 {display_number(value)} 步（{day}）"
                for day, value in reversed(list(zip(series["dates"], series["steps"])))
                if display_number(value) is not None
            ),
            None,
        )
        observations.append(steps_observation or "每日步数无有效观测")

    gaps = []
    for label, key in (
        ("静息心率", "rhr"),
        ("HRV", "hrv"),
        ("睡眠总时长", "sleep_total"),
        ("睡眠阶段", "sleep_stages"),
        ("Body Battery", "body_battery"),
        ("每日步数", "steps"),
        ("Garmin 压力", "stress"),
        ("睡眠评分", "sleep_score"),
    ):
        entry = coverage[key]
        if entry["status"] == "partial":
            gaps.append(f"{label}仅覆盖 {entry['observed_days']}/{entry['requested_days']} 天")
        elif entry["status"] == "no_data":
            gaps.append(f"{label}没有有效观测")
        elif entry["status"] == "error":
            gaps.append(f"{label}组件读取失败")

    if baseline["qualified"]:
        baseline_text = (
            f"静息心率相对可比个人基线为 {baseline['rhr']['delta_pct']:+.1f}%"
            f"（{baseline['paired_baseline_days']} 个基线日）"
        )
    elif baseline["status"] == "not_requested":
        baseline_text = "本次未同时请求静息心率与 HRV，未评估个人基线"
    else:
        baseline_text = (
            f"个人基线门禁未通过（{baseline['status']}），未显示百分比变化"
        )

    return "\n\n".join(
        (
            f"【数据范围】{period}；{freshness}。",
            "【可观察指标】" + ("；".join(observations) if observations else "本次没有请求可展示指标") + "。",
            "【覆盖限制】" + ("；".join(gaps) if gaps else "所请求的展示指标均有完整日覆盖") + "。",
            f"【基线比较】{baseline_text}。",
            "【方法边界】只描述消费级可穿戴设备观测，不生成诊断、准备度分数、活动处方或强制安排；不能据此推断感染、炎症、免疫状态、认知能力或职业表现。",
        )
    )


def build_dashboard_payload(
    summary_data: dict[str, Any],
    *,
    days: int,
    requested_source: str,
    effective_source: str,
    selected_components: tuple[str, ...] | list[str],
    live_fallback_attempted: bool,
    requested_start: str | None = None,
    requested_end: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the allowlisted, audit-oriented dashboard.v3 view model."""
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("INVALID_PERIOD_SCOPE")
    components = _normalize_dashboard_components(selected_components)
    summary_data = _scope_dashboard_source(summary_data, components)
    if requested_start is None or requested_end is None:
        requested_start, requested_end = get_date_range(days)
    dates = _calendar_dates(requested_start, requested_end)
    if len(dates) != days:
        raise ValueError("INVALID_PERIOD_SCOPE")

    series = build_dashboard_series(
        summary_data,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    coverage = {
        "rhr": _coverage_entry(
            dates,
            [series["rhr_bpm"]],
            source_status=_source_component_status(
                summary_data, "heart_rate", components
            ),
        ),
        "hrv": _coverage_entry(
            dates,
            [series["hrv_ms"]],
            source_status=_source_component_status(summary_data, "hrv", components),
        ),
        "sleep_total": _coverage_entry(
            dates,
            [series["sleep_total_h"]],
            source_status=_source_component_status(summary_data, "sleep", components),
        ),
        "sleep_stages": _coverage_entry(
            dates,
            [
                series["sleep_deep_h"],
                series["sleep_rem_h"],
                series["sleep_light_h"],
            ],
            require_all=True,
            source_status=_source_component_status(summary_data, "sleep", components),
        ),
        "sleep_respiration": _coverage_entry(
            dates,
            [series["sleep_respiration_brpm"]],
            source_status=_source_component_status(summary_data, "sleep", components),
        ),
        "sleep_spo2": _coverage_entry(
            dates,
            [series["sleep_spo2_pct"]],
            source_status=_source_component_status(summary_data, "sleep", components),
        ),
        "body_battery": _coverage_entry(
            dates,
            [series["body_battery_high"], series["body_battery_low"]],
            require_all=True,
            source_status=_source_component_status(
                summary_data, "body_battery", components
            ),
        ),
        "steps": _coverage_entry(
            dates,
            [series["steps"]],
            source_status=_source_component_status(summary_data, "stress", components),
        ),
    }
    stress_kpi, _stress_record_coverage = _stress_snapshot(
        summary_data,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    stress_source_status = _source_component_status(summary_data, "stress", components)
    coverage["stress"] = _coverage_entry(
        dates,
        [series["stress_avg"]],
        source_status=stress_source_status,
    )

    sleep_score_map = {
        item["date"]: item["score"] for item in build_heatmap_data(summary_data)
    }
    heatmap_items = [
        {"date": day, "score": sleep_score_map.get(day)} for day in dates
    ]
    sleep_score_values = [item["score"] for item in heatmap_items]
    coverage["sleep_score"] = _coverage_entry(
        dates,
        [sleep_score_values],
        source_status=_source_component_status(summary_data, "sleep", components),
    )
    heatmap_eligible = days >= DASHBOARD_MIN_HEATMAP_DAYS
    heatmap_status = (
        "not_requested"
        if "sleep" not in components
        else "insufficient_window"
        if not heatmap_eligible
        else "available"
        if coverage["sleep_score"]["observed_days"] > 0
        else "no_data"
    )

    kpis = {
        "rhr": _latest_kpi(
            dates,
            series["rhr_bpm"],
            unit="bpm",
            source_type="wearable_device_metric",
        ),
        "hrv": _latest_kpi(
            dates,
            series["hrv_ms"],
            unit="ms",
            source_type="wearable_device_metric",
        ),
        "sleep": _latest_kpi(
            dates,
            series["sleep_total_h"],
            unit="h",
            source_type="device_algorithm_estimate",
        ),
        "stress": stress_kpi,
    }

    baseline = (
        _baseline_view(summary_data)
        if {"heart_rate", "hrv"}.issubset(components)
        else _unrequested_baseline()
    )
    patterns = analyze_health_patterns(
        summary_data,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    observed_ranges = [
        (entry["first_date"], entry["last_date"])
        for entry in coverage.values()
        if entry.get("first_date") and entry.get("last_date")
    ]
    first_observation = (
        min(item[0] for item in observed_ranges) if observed_ranges else None
    )
    last_observation = (
        max(item[1] for item in observed_ranges) if observed_ranges else None
    )
    lag_days = (
        (datetime.strptime(requested_end, "%Y-%m-%d") - datetime.strptime(last_observation, "%Y-%m-%d")).days
        if last_observation
        else None
    )
    insight = generate_chinese_insight(summary_data)
    coverage_labels = {
        "rhr": "静息心率",
        "hrv": "HRV",
        "sleep_total": "睡眠总时长",
        "sleep_stages": "睡眠阶段",
        "sleep_respiration": "夜间呼吸率",
        "sleep_spo2": "夜间 Pulse Ox",
        "body_battery": "Body Battery",
        "steps": "每日步数",
        "stress": "Garmin 压力",
        "sleep_score": "睡眠评分",
    }
    data_gaps = []
    for key, label in coverage_labels.items():
        entry = coverage[key]
        if entry["status"] == "no_data":
            data_gaps.append(f"{label}在请求窗口内没有有效观测。")
        elif entry["status"] == "partial":
            data_gaps.append(
                f"{label}仅覆盖 {entry['observed_days']}/{entry['requested_days']} 天。"
            )
        elif entry["status"] == "error":
            data_gaps.append(f"{label}组件读取失败，面板没有把错误当作零值。")
    overall_narrative = _dashboard_overall_narrative(
        summary_data,
        coverage=coverage,
        kpis=kpis,
        series=series,
        baseline=baseline,
        requested_start=requested_start,
        requested_end=requested_end,
        legacy_insight=insight,
    )
    payload = {
        "schema_version": DASHBOARD_SCHEMA,
        "meta": {
            "generated_at": generated_at
            or datetime.now().astimezone().replace(microsecond=0).isoformat(),
            "requested_range": {
                "start": requested_start,
                "end": requested_end,
                "days": days,
                "date_semantics": "inclusive_source_calendar_days",
                "timezone": None,
                "timezone_status": "not_available_in_source",
            },
            "observation_range": {
                "start": first_observation,
                "end": last_observation,
            },
            "source": {
                "requested": requested_source,
                "effective": effective_source,
                "fallback_attempted": bool(live_fallback_attempted),
                "components": list(components),
            },
            "freshness": {
                "latest_observation_date": last_observation,
                "lag_days": max(0, lag_days) if lag_days is not None else None,
                "source_marked_stale": summary_data.get("is_stale"),
            },
            "integrity": _safe_integrity(summary_data),
            "device_epoch": _safe_device_epoch(summary_data, baseline),
            "payload_scope": "rendered_fields_only",
        },
        "coverage": coverage,
        "baseline": baseline,
        "kpis": kpis,
        "series": series,
        "heatmap": {
            "minimum_window_days": DASHBOARD_MIN_HEATMAP_DAYS,
            "eligible_by_window": heatmap_eligible,
            "status": heatmap_status,
            "items": heatmap_items if heatmap_eligible else [],
        },
        "patterns": patterns,
        "narrative": {
            "overall": overall_narrative,
            "unknowns": [
                *data_gaps,
                "未收集症状、病史、药物和生活情境，不能仅凭设备数据判断原因或急迫性。",
            ],
            "optional_considerations": [
                "可核对佩戴连续性，并记录旅行、饮酒、活动、睡眠和主观感受。",
                "面板不生成训练、休息或日程建议；任何后续行动由用户自行决定。",
            ],
            "escalation": [
                "出现急症信号时，不等待设备分数变化，立即联系当地急救服务。",
                "变化持续、伴随明显症状或影响生活时，携带原始数据咨询合格医疗人员。",
            ],
        },
    }
    return _project_dashboard_payload(payload)


def _project_coverage(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        key: source.get(key)
        for key in (
            "status",
            "observed_days",
            "requested_days",
            "coverage_ratio",
            "first_date",
            "last_date",
            "missing_days",
            "observed_zero_days",
            "longest_missing_streak_days",
            "current_missing_streak_days",
        )
    }


def _project_kpi(value: Any, *, include_details: bool = False) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result = {
        key: source.get(key)
        for key in ("value", "unit", "observed_date", "source_type")
    }
    if include_details:
        details = source.get("details") if isinstance(source.get("details"), dict) else {}
        result["details"] = {
            key: details.get(key) for key in ("high_h", "medium_h", "rest_h")
        }
    return result


def _project_pattern_trend(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    eligible = source.get("status") == "eligible"
    result = {
        key: source.get(key)
        for key in (
            "status",
            "label",
            "unit",
            "epoch_comparable",
            "epoch_status",
            "baseline_min_days",
            "recent_window_days",
            "historical_sample_days",
            "recent_sample_days",
        )
    }
    result.update(
        {
            key: _clean_value(source.get(key)) if eligible else None
            for key in (
                "baseline_median",
                "baseline_mad",
                "recent_median",
                "absolute_delta",
                "robust_z",
            )
        }
    )
    result["direction"] = source.get("direction") if eligible else None
    result["limitations"] = [str(item) for item in source.get("limitations") or []]
    return result


def _project_pattern_continuity(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        key: _clean_value(source.get(key))
        for key in (
            "status",
            "requested_days",
            "observed_days",
            "derived_value_days",
            "missing_days",
            "coverage_fraction",
            "longest_missing_streak_days",
            "current_missing_streak_days",
        )
    } | {
        "conflicting_duplicate_count": len(
            source.get("conflicting_duplicate_dates") or []
        ),
        "limitations": [str(item) for item in source.get("limitations") or []],
    }


def _project_patterns(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    requested = (
        source.get("requested_range")
        if isinstance(source.get("requested_range"), dict)
        else {}
    )
    trends = source.get("trends") if isinstance(source.get("trends"), dict) else {}
    continuity = (
        source.get("continuity")
        if isinstance(source.get("continuity"), dict)
        else {}
    )
    sleep = (
        source.get("sleep_regularity")
        if isinstance(source.get("sleep_regularity"), dict)
        else {}
    )
    associations = (
        source.get("lagged_associations")
        if isinstance(source.get("lagged_associations"), dict)
        else {}
    )
    trend_ids = (
        "rhr",
        "hrv",
        "sleep_duration",
        "sleep_respiration",
        "sleep_spo2",
    )
    association_ids = ("rhr", "hrv", "sleep_duration")
    duration_eligible = sleep.get("duration_status") == "eligible"
    timing_eligible = sleep.get("timing_status") == "eligible"
    return {
        "analysis_type": source.get("analysis_type"),
        "status": source.get("status"),
        "method_version": source.get("method_version"),
        "medical_interpretation": False,
        "requested_range": {
            key: requested.get(key)
            for key in ("start", "end", "days", "expanded_beyond_request")
        },
        "eligibility": [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "label",
                    "status",
                    "observed_days",
                    "required_days",
                    "paired_days",
                    "required_pairs",
                    "epoch_status",
                    "reason",
                )
            }
            for item in source.get("eligibility") or []
            if isinstance(item, dict)
        ],
        "continuity": {
            key: _project_pattern_continuity(continuity.get(key))
            for key in trend_ids
        },
        "trends": {
            key: _project_pattern_trend(trends.get(key)) for key in trend_ids
        },
        "sleep_regularity": {
            key: sleep.get(key)
            for key in (
                "status",
                "epoch_comparable",
                "epoch_status",
                "window_days",
                "min_valid_nights",
                "valid_nights",
                "duration_status",
                "duration_source",
                "duration_valid_nights",
                "timing_status",
                "timing_valid_nights",
            )
        }
        | {
            "duration_sd_hours": (
                _clean_value(sleep.get("duration_sd_hours"))
                if duration_eligible
                else None
            ),
            "utc_offset_minutes": (
                _clean_value(sleep.get("utc_offset_minutes"))
                if timing_eligible
                else None
            ),
            "bedtime_circular_sd_hours": (
                _clean_value(sleep.get("bedtime_circular_sd_hours"))
                if timing_eligible
                else None
            ),
            "midpoint_circular_sd_hours": (
                _clean_value(sleep.get("midpoint_circular_sd_hours"))
                if timing_eligible
                else None
            ),
            "wake_time_circular_sd_hours": (
                _clean_value(sleep.get("wake_time_circular_sd_hours"))
                if timing_eligible
                else None
            ),
            "limitations": [str(item) for item in sleep.get("limitations") or []],
        },
        "lagged_associations": {
            key: {
                field: associations.get(key, {}).get(field)
                for field in (
                    "status",
                    "exposure_field",
                    "outcome_field",
                    "lag_calendar_days",
                    "join_semantics",
                    "exposure_coverage_semantics",
                    "epoch_comparable",
                    "epoch_status",
                    "min_pairs",
                    "pair_count",
                )
            }
            | {
                "spearman_rho": (
                    _clean_value(associations.get(key, {}).get("spearman_rho"))
                    if associations.get(key, {}).get("status") == "eligible"
                    else None
                ),
                "causal_interpretation": False,
                "limitations": [
                    str(item)
                    for item in associations.get(key, {}).get("limitations") or []
                ],
            }
            for key in association_ids
        },
        "metric_lineage": [
            {
                "metric": item.get("metric"),
                "shared_upstream_inputs": [
                    str(field) for field in item.get("shared_upstream_inputs") or []
                ],
                "independent_corroboration": False,
            }
            for item in source.get("metric_lineage") or []
            if isinstance(item, dict)
        ],
        "lineage_warning": source.get("lineage_warning"),
        "limitations": [str(item) for item in source.get("limitations") or []],
    }


def _project_dashboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a recursive allowlist before health data becomes a persistent HTML file."""
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    requested = (
        meta.get("requested_range")
        if isinstance(meta.get("requested_range"), dict)
        else {}
    )
    observed = (
        meta.get("observation_range")
        if isinstance(meta.get("observation_range"), dict)
        else {}
    )
    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    freshness = (
        meta.get("freshness") if isinstance(meta.get("freshness"), dict) else {}
    )
    integrity = (
        meta.get("integrity") if isinstance(meta.get("integrity"), dict) else {}
    )
    epoch = (
        meta.get("device_epoch")
        if isinstance(meta.get("device_epoch"), dict)
        else {}
    )
    coverage_source = (
        payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    )
    baseline = (
        payload.get("baseline") if isinstance(payload.get("baseline"), dict) else {}
    )
    baseline_rhr = (
        baseline.get("rhr") if isinstance(baseline.get("rhr"), dict) else {}
    )
    baseline_hrv = (
        baseline.get("hrv") if isinstance(baseline.get("hrv"), dict) else {}
    )
    baseline_qualified = baseline.get("qualified") is True
    kpis = payload.get("kpis") if isinstance(payload.get("kpis"), dict) else {}
    series = payload.get("series") if isinstance(payload.get("series"), dict) else {}
    heatmap = (
        payload.get("heatmap") if isinstance(payload.get("heatmap"), dict) else {}
    )
    narrative = (
        payload.get("narrative")
        if isinstance(payload.get("narrative"), dict)
        else {}
    )
    patterns = _project_patterns(payload.get("patterns"))
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "meta": {
            "generated_at": meta.get("generated_at"),
            "requested_range": {
                key: requested.get(key)
                for key in (
                    "start",
                    "end",
                    "days",
                    "date_semantics",
                    "timezone",
                    "timezone_status",
                )
            },
            "observation_range": {
                "start": observed.get("start"),
                "end": observed.get("end"),
            },
            "source": {
                key: source.get(key)
                for key in (
                    "requested",
                    "effective",
                    "fallback_attempted",
                    "components",
                )
            },
            "freshness": {
                key: freshness.get(key)
                for key in (
                    "latest_observation_date",
                    "lag_days",
                    "source_marked_stale",
                )
            },
            "integrity": {
                key: integrity.get(key)
                for key in ("status", "database_count")
            },
            "device_epoch": {
                key: epoch.get(key)
                for key in (
                    "status",
                    "device_count",
                    "firmware_versions",
                    "analysis_algorithm_epoch",
                    "manufacturer_algorithm_epoch",
                )
            },
            "payload_scope": meta.get("payload_scope"),
        },
        "coverage": {
            key: _project_coverage(coverage_source.get(key))
            for key in (
                "rhr",
                "hrv",
                "sleep_total",
                "sleep_stages",
                "sleep_respiration",
                "sleep_spo2",
                "body_battery",
                "steps",
                "stress",
                "sleep_score",
            )
        },
        "baseline": {
            key: baseline.get(key)
            for key in (
                "status",
                "paired_current_date",
                "paired_baseline_days",
                "required_days",
                "baseline_start",
                "baseline_end",
                "epoch_status",
                "method",
                "analysis_algorithm_epoch",
            )
        }
        | {
            "qualified": baseline_qualified,
            "rhr": {
                "baseline": (
                    _clean_value(baseline_rhr.get("baseline"))
                    if baseline_qualified
                    else None
                ),
                "delta_pct": (
                    _clean_value(baseline_rhr.get("delta_pct"))
                    if baseline_qualified
                    else None
                ),
            },
            "hrv": {
                "baseline": (
                    _clean_value(baseline_hrv.get("baseline"))
                    if baseline_qualified
                    else None
                )
            },
            "limitations": [str(item) for item in baseline.get("limitations") or []],
        },
        "kpis": {
            "rhr": _project_kpi(kpis.get("rhr")),
            "hrv": _project_kpi(kpis.get("hrv")),
            "sleep": _project_kpi(kpis.get("sleep")),
            "stress": _project_kpi(kpis.get("stress"), include_details=True),
        },
        "series": {
            key: list(series.get(key) or []) for key in DASHBOARD_SERIES_FIELDS
        },
        "heatmap": {
            "minimum_window_days": heatmap.get("minimum_window_days"),
            "eligible_by_window": heatmap.get("eligible_by_window"),
            "status": heatmap.get("status"),
            "items": [
                {"date": item.get("date"), "score": item.get("score")}
                for item in heatmap.get("items") or []
                if isinstance(item, dict)
            ],
        },
        "patterns": patterns,
        "narrative": {
            "overall": narrative.get("overall"),
            "unknowns": [str(item) for item in narrative.get("unknowns") or []],
            "optional_considerations": [
                str(item) for item in narrative.get("optional_considerations") or []
            ],
            "escalation": [str(item) for item in narrative.get("escalation") or []],
        },
    }


def _legacy_dashboard_payload(charts_data: dict[str, Any]) -> dict[str, Any]:
    overlay = charts_data.get("overlay_data") or {}
    dates = [str(item) for item in overlay.get("dates") or []]
    series = {
        "dates": dates,
        "rhr_bpm": list(overlay.get("rhr") or []),
        "hrv_ms": list(overlay.get("hrv") or []),
        "sleep_total_h": list(overlay.get("sleep_h") or []),
        "sleep_deep_h": list(overlay.get("sleep_deep_h") or []),
        "sleep_rem_h": list(overlay.get("sleep_rem_h") or []),
        "sleep_light_h": list(overlay.get("sleep_light_h") or []),
        "sleep_respiration_brpm": list(overlay.get("sleep_respiration") or []),
        "sleep_spo2_pct": list(overlay.get("spo2_history") or []),
        "body_battery_high": list(overlay.get("bb_max") or []),
        "body_battery_low": list(overlay.get("bb_min") or []),
        "steps": list(overlay.get("steps") or []),
        "stress_avg": list(overlay.get("stress_avg") or []),
    }
    requested_days = len(dates)
    coverage = {
        "rhr": _coverage_entry(dates, [series["rhr_bpm"]]),
        "hrv": _coverage_entry(dates, [series["hrv_ms"]]),
        "sleep_total": _coverage_entry(dates, [series["sleep_total_h"]]),
        "sleep_stages": _coverage_entry(
            dates,
            [
                series["sleep_deep_h"],
                series["sleep_rem_h"],
                series["sleep_light_h"],
            ],
            require_all=True,
        ),
        "sleep_respiration": _coverage_entry(
            dates, [series["sleep_respiration_brpm"]]
        ),
        "sleep_spo2": _coverage_entry(dates, [series["sleep_spo2_pct"]]),
        "body_battery": _coverage_entry(
            dates,
            [series["body_battery_high"], series["body_battery_low"]],
            require_all=True,
        ),
        "steps": _coverage_entry(dates, [series["steps"]]),
        "stress": _coverage_entry(dates, [series["stress_avg"]]),
        "sleep_score": _coverage_entry(
            [str(item.get("date")) for item in charts_data.get("heatmap") or []],
            [[item.get("score") for item in charts_data.get("heatmap") or []]],
        ),
    }
    payload = {
        "schema_version": DASHBOARD_SCHEMA,
        "meta": {
            "generated_at": None,
            "requested_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
                "days": requested_days,
                "date_semantics": "legacy_unknown",
                "timezone": None,
                "timezone_status": "not_available_in_source",
            },
            "observation_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
            },
            "source": {
                "requested": "unknown",
                "effective": "unknown",
                "fallback_attempted": False,
                "components": [],
            },
            "freshness": {
                "latest_observation_date": dates[-1] if dates else None,
                "lag_days": None,
                "source_marked_stale": None,
            },
            "integrity": {
                "status": "not_available",
                "database_count": 0,
                "databases": [],
            },
            "device_epoch": {
                "status": "epoch_unknown",
                "device_count": 0,
                "firmware_versions": [],
                "analysis_algorithm_epoch": None,
                "manufacturer_algorithm_epoch": "not_available",
            },
            "payload_scope": "rendered_fields_only",
        },
        "coverage": coverage,
        "baseline": {
            "status": "insufficient_baseline",
            "qualified": False,
            "paired_current_date": None,
            "paired_baseline_days": 0,
            "required_days": MIN_PAIRED_BASELINE_DAYS,
            "baseline_start": None,
            "baseline_end": None,
            "epoch_status": "epoch_unknown",
            "method": "prior_same_date_mean",
            "analysis_algorithm_epoch": None,
            "rhr": {
                "current": None,
                "baseline": None,
                "delta_bpm": None,
                "delta_pct": None,
            },
            "hrv": {"current": None, "baseline": None},
            "limitations": ["Legacy payload does not contain a qualified baseline gate."],
        },
        "kpis": {
            "rhr": _latest_kpi(
                dates,
                series["rhr_bpm"],
                unit="bpm",
                source_type="wearable_device_metric",
            ),
            "hrv": _latest_kpi(
                dates,
                series["hrv_ms"],
                unit="ms",
                source_type="wearable_device_metric",
            ),
            "sleep": _latest_kpi(
                dates,
                series["sleep_total_h"],
                unit="h",
                source_type="device_algorithm_estimate",
            ),
            "stress": {
                "value": None,
                "unit": "Garmin 分数",
                "observed_date": None,
                "source_type": "garmin_proprietary_metric",
                "details": {"high_h": None, "medium_h": None, "rest_h": None},
            },
        },
        "series": series,
        "heatmap": {
            "minimum_window_days": DASHBOARD_MIN_HEATMAP_DAYS,
            "eligible_by_window": bool(charts_data.get("heatmap")),
            "status": "available" if charts_data.get("heatmap") else "no_data",
            "items": charts_data.get("heatmap") or [],
        },
        "patterns": {
            "analysis_type": "descriptive_health_patterns",
            "status": "not_available",
            "method_version": "patterns.v1",
            "medical_interpretation": False,
            "requested_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
                "days": requested_days,
                "expanded_beyond_request": False,
            },
            "eligibility": [],
            "continuity": {},
            "trends": {},
            "sleep_regularity": {},
            "lagged_associations": {},
            "metric_lineage": [],
            "lineage_warning": "旧版载荷没有深入分析资格信息。",
            "limitations": ["legacy_payload_without_pattern_analysis"],
        },
        "narrative": {
            "overall": charts_data.get("overall_insight") or "暂无趋势说明。",
            "unknowns": ["旧版载荷缺少结构化来源、覆盖率和设备时期。"],
            "optional_considerations": [],
            "escalation": [],
        },
    }
    return _project_dashboard_payload(payload)


def _sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(key): _sanitize_obj(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_obj(value) for value in obj]
    return _clean_value(obj)


def render_report(charts_data: dict[str, Any]) -> str:
    if not TEMPLATE_FILE.exists():
        raise FileNotFoundError(f"Dashboard template is missing: {TEMPLATE_FILE}")
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    dashboard_payload = (
        _project_dashboard_payload(charts_data)
        if charts_data.get("schema_version") == DASHBOARD_SCHEMA
        else _legacy_dashboard_payload(charts_data)
    )
    payload = json.dumps(
        _sanitize_obj(dashboard_payload), ensure_ascii=False, allow_nan=False
    )
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    replacements = {
        "%%TITLE%%": "Garmin 健康审计面板",
        "%%B64_DATA%%": encoded,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def _load_summary(
    days: int,
    source: str,
    *,
    components: tuple[str, ...] | list[str] | None = None,
    network_capability: object = None,
    health_data_capability: object = None,
    request: dict[str, object] | None = None,
) -> dict[str, Any]:
    if source == "local":
        if not HAS_SQLITE:
            raise RuntimeError("LOCAL_DATA_UNAVAILABLE")
        result = fetch_local_summary(days, components=components)
    else:
        try:
            require_capability(
                network_capability,
                scope="network",
                operation=DASHBOARD_LIVE_OPERATION,
                request=request,
            )
        except CapabilityError:
            raise RuntimeError("NETWORK_ACCESS_NOT_AUTHORIZED")
        try:
            require_capability(
                health_data_capability,
                scope="health_data",
                operation=DASHBOARD_LIVE_OPERATION,
                request=request,
            )
        except CapabilityError:
            raise RuntimeError("HEALTH_DATA_ACCESS_NOT_AUTHORIZED")
        start_date, end_date = _validate_live_request_scope(days, request)
        client = get_client(
            network_capability=network_capability,
            operation=DASHBOARD_LIVE_OPERATION,
            request=request,
        )
        if not client:
            raise RuntimeError("LIVE_AUTH_UNAVAILABLE")
        consume_capability(
            health_data_capability,
            scope="health_data",
            operation=DASHBOARD_LIVE_OPERATION,
            request=request,
        )
        result = fetch_summary(
            client,
            start=start_date,
            end=end_date,
            components=request["components"],
        )
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError("HEALTH_DATA_LOAD_FAILED")
    return result


def _atomic_write_text(
    output_path: Path,
    content: str,
    *,
    overwrite: bool = False,
) -> None:
    """Publish a complete report atomically without clobbering by default."""
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and output_path.exists():
        raise FileExistsError(f"OUTPUT_EXISTS: {output_path}")

    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        if overwrite:
            os.replace(temporary_path, output_path)
        else:
            # A hard-link install is atomic and fails if another writer created
            # the destination after the initial check.
            os.link(temporary_path, output_path)
            temporary_path.unlink()
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a non-diagnostic Garmin dashboard.")
    parser.add_argument("chart", choices=["dashboard", "overlay"])
    parser.add_argument("--days", type=int)
    parser.add_argument("--period")
    parser.add_argument("--output")
    parser.add_argument(
        "--source",
        choices=["local", "live"],
        default="local",
        help="Data source. Live access requires two grants and an explicit period.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Second, explicit authorization required before live client initialization.",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize health-data reads for this exact chart and period.",
    )
    parser.add_argument(
        "--fallback-live",
        action="store_true",
        help=(
            "If an authorized local read returns exactly no_data, use the explicitly "
            "authorized live source for the same window and components."
        ),
    )
    parser.add_argument(
        "--components",
        help=(
            "Comma-separated live component allowlist. Required for --fallback-live; "
            "allowed values are sleep,hrv,body_battery,heart_rate,activities,stress,"
            "training_load_series."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly allow replacement of an existing output file.",
    )
    args = parser.parse_args(argv)
    if args.fallback_live and args.source != "local":
        print(json.dumps({"status": "INVALID_FALLBACK_SOURCE"}), file=sys.stderr)
        return 2
    if args.days is not None and args.period:
        print(json.dumps({"status": "INVALID_PERIOD_SCOPE"}), file=sys.stderr)
        return 2
    if (args.source == "live" or args.fallback_live) and args.days is None and not args.period:
        print(json.dumps({"status": "EXPLICIT_LIVE_PERIOD_REQUIRED"}), file=sys.stderr)
        return 2
    try:
        days = parse_period(args.period, 7 if args.days is None else args.days)
        requested_start, requested_end = get_date_range(days)
    except (TypeError, ValueError):
        print(json.dumps({"status": "INVALID_PERIOD_SCOPE"}), file=sys.stderr)
        return 2
    if args.source == "local" and not args.allow_health_data:
        print(json.dumps({"status": "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"}), file=sys.stderr)
        return 2
    try:
        selected_components = (
            _normalize_dashboard_components(args.components)
            if args.components is not None
            else DASHBOARD_DEFAULT_COMPONENTS
        )
    except ValueError:
        print(json.dumps({"status": "INVALID_COMPONENT_SCOPE"}), file=sys.stderr)
        return 2
    if args.fallback_live and args.components is None:
        print(json.dumps({"status": "EXPLICIT_COMPONENT_SCOPE_REQUIRED"}), file=sys.stderr)
        return 2
    network_capability = None
    health_data_capability = None
    request = None
    if (args.source == "live" or args.fallback_live) and (
        not args.allow_network or not args.allow_health_data
    ):
        status = (
            "NETWORK_ACCESS_NOT_AUTHORIZED"
            if not args.allow_network
            else "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"
        )
        print(json.dumps({"status": status}), file=sys.stderr)
        return 2
    if args.source == "live":
        start_date, end_date = requested_start, requested_end
        request = {
            "chart": args.chart,
            "source": "live",
            "start": start_date,
            "end": end_date,
            "components": list(selected_components),
        }
        network_capability = issue_capability(
            scope="network",
            operation=DASHBOARD_LIVE_OPERATION,
            request=request,
        )
        health_data_capability = issue_capability(
            scope="health_data",
            operation=DASHBOARD_LIVE_OPERATION,
            request=request,
        )
    effective_source = args.source
    live_fallback_attempted = False
    try:
        summary_data = _load_summary(
            days,
            args.source,
            components=selected_components,
            network_capability=network_capability,
            health_data_capability=health_data_capability,
            request=request,
        )
        if (
            args.source == "local"
            and args.fallback_live
            and summary_data.get("status") == "no_data"
        ):
            live_fallback_attempted = True
            effective_source = "live"
            start_date, end_date = requested_start, requested_end
            request = {
                "chart": args.chart,
                "source": "live",
                "start": start_date,
                "end": end_date,
                "components": list(selected_components),
            }
            network_capability = issue_capability(
                scope="network",
                operation=DASHBOARD_LIVE_OPERATION,
                request=request,
            )
            health_data_capability = issue_capability(
                scope="health_data",
                operation=DASHBOARD_LIVE_OPERATION,
                request=request,
            )
            summary_data = _load_summary(
                days,
                "live",
                components=selected_components,
                network_capability=network_capability,
                health_data_capability=health_data_capability,
                request=request,
            )
    except Exception as exc:
        known_codes = {
            "LOCAL_DATA_UNAVAILABLE",
            "NETWORK_ACCESS_NOT_AUTHORIZED",
            "HEALTH_DATA_ACCESS_NOT_AUTHORIZED",
            "LIVE_AUTH_UNAVAILABLE",
            "HEALTH_DATA_LOAD_FAILED",
            "LIVE_SCOPE_INVALID",
        }
        print(
            json.dumps(
                {
                    "status": "DATA_SOURCE_UNAVAILABLE",
                    "source": effective_source,
                    "error_code": str(exc) if str(exc) in known_codes else "DATA_SOURCE_FAILURE",
                    "error_type": type(exc).__name__,
                    "live_fallback_attempted": live_fallback_attempted,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    charts_data = build_dashboard_payload(
        summary_data,
        days=days,
        requested_source=args.source,
        effective_source=effective_source,
        selected_components=selected_components,
        live_fallback_attempted=live_fallback_attempted,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    html = render_report(charts_data)
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = build_report_paths(days=days, create_dir=True)["html"]
    try:
        _atomic_write_text(output_path, html, overwrite=args.overwrite)
    except FileExistsError as exc:
        print(
            json.dumps(
                {
                    "status": "OUTPUT_EXISTS",
                    "path": str(output_path),
                    "error": str(exc),
                    "overwrite_attempted": args.overwrite,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "OUTPUT_WRITE_FAILED",
                    "path": str(output_path),
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(f"Report: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
