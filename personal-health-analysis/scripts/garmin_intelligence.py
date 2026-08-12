#!/usr/bin/env python3
"""Non-diagnostic analysis of user-authorized Garmin data."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    from garmin_sqlite_adapter import (
        ACTIVITIES_DB,
        DB_DIR,
        GARMIN_DB,
        LocalDatabaseChangedError,
        get_activities_data as sqlite_activities,
        get_biomechanics_data as sqlite_biomechanics,
        get_body_composition_detailed,
        get_daily_friction_matrix,
        get_device_firmware_history,
        get_devices_info,
        get_hrv_data as sqlite_hrv,
        get_max_metrics,
        get_sleep_data as sqlite_sleep,
        get_summary as sqlite_summary,
        verified_database_read_window,
    )

    HAS_SQLITE = DB_DIR.exists()
except ImportError:
    HAS_SQLITE = False

    class LocalDatabaseChangedError(RuntimeError):
        """Fallback type when the optional local adapter cannot be imported."""

from garmin_auth import get_client
from garmin_capabilities import consume_capability, issue_capability
from garmin_data import fetch_summary, get_date_range
from garmin_patterns import (
    METHOD_VERSION as PATTERN_METHOD_VERSION,
    lagged_rank_association,
    normalize_daily_numeric,
    observation_continuity,
    robust_personal_trend,
    sleep_regularity_snapshot,
)

LocalDataChangedError = LocalDatabaseChangedError

LIVE_ANALYSIS_COMPONENTS = {
    "baseline_change": ("sleep", "hrv", "heart_rate"),
    "readiness": ("sleep", "hrv", "body_battery", "stress"),
    "insight_cn": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "audit": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "env_stress": ("activities",),
}
LIVE_UNSUPPORTED_ANALYSES = frozenset(
    {"long_term_load", "device_audit", "patterns"}
)

LOCAL_ANALYSIS_COMPONENTS = {
    "baseline_change": ("sleep", "hrv", "heart_rate"),
    "readiness": ("sleep", "hrv", "body_battery", "stress"),
    "insight_cn": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "audit": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "env_stress": ("activities",),
    "long_term_load": ("training_load_series",),
    # Reserved for the separately implemented descriptive pattern analysis.
    "patterns": ("sleep", "hrv", "heart_rate", "training_load_series"),
    # Device audit is the explicit metadata-only exception. It reads no health
    # metric component, but may read the device and firmware metadata below.
    "device_audit": (),
}
LOCAL_ANALYSIS_METADATA = {
    "baseline_change": ("firmware_history",),
    "insight_cn": ("firmware_history",),
    "audit": ("firmware_history",),
    "patterns": ("firmware_history",),
    "device_audit": ("device_info", "firmware_history"),
}
LOCAL_METADATA_COMPONENTS = ("device_info", "firmware_history")


_CLINICAL_GUIDELINES: dict[str, Any] | None = None
REQUIRED_PROVENANCE_FIELDS = (
    "source_type",
    "source",
    "published_at",
    "retrieved_at",
    "region",
    "population",
    "intended_use",
)
MIN_PAIRED_BASELINE_DAYS = 21
BASELINE_ALGORITHM_EPOCH = "personal-health-analysis:baseline-change:v2"
LIVE_SUMMARY_OPERATION = "garmin_intelligence_live"
LOCAL_SUMMARY_COMPONENTS = (
    "sleep",
    "hrv",
    "body_battery",
    "heart_rate",
    "activities",
    "stress",
    "training_load_series",
)
ALLOWED_SOURCE_TYPES = {
    "authoritative_guideline",
    "peer_reviewed_method",
    "manufacturer_method",
    "clinician_supplied",
    "user_supplied",
    "method_assumption",
}
SECTION_INTENDED_USE = {
    "screening_signal": "non_diagnostic_screening",
    "training_load_model": "descriptive_experimental_index",
}
HARD_DISABLED_METHOD_SECTIONS = {"readiness_index"}


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_provenance(section_name: str, provenance: Any) -> bool:
    if not isinstance(provenance, dict):
        return False
    if any(provenance.get(field) in (None, "") for field in REQUIRED_PROVENANCE_FIELDS):
        return False
    if provenance.get("source_type") not in ALLOWED_SOURCE_TYPES:
        return False
    source = str(provenance.get("source", ""))
    parsed = urlparse(source)
    if not parsed.scheme or not (parsed.netloc or parsed.path):
        return False
    try:
        published = datetime.strptime(provenance["published_at"], "%Y-%m-%d").date()
        retrieved = datetime.strptime(provenance["retrieved_at"], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    if published > retrieved or retrieved > date.today():
        return False
    if provenance.get("intended_use") != SECTION_INTENDED_USE.get(section_name):
        return False
    return all(
        isinstance(provenance.get(field), str) and provenance[field].strip()
        for field in ("region", "population")
    )


def _valid_method_parameters(section_name: str, section: dict[str, Any]) -> bool:
    if section_name == "screening_signal":
        baseline_days = section.get("baseline_min_days")
        thresholds = section.get("thresholds", {})
        return (
            isinstance(baseline_days, int)
            and not isinstance(baseline_days, bool)
            and baseline_days >= MIN_PAIRED_BASELINE_DAYS
            and _finite_number(thresholds.get("rhr_z_score_min"))
            and float(thresholds["rhr_z_score_min"]) > 0
            and _finite_number(thresholds.get("hrv_z_score_max"))
            and float(thresholds["hrv_z_score_max"]) < 0
            and _finite_number(thresholds.get("respiration_delta_min"))
            and float(thresholds["respiration_delta_min"]) > 0
        )
    if section_name == "training_load_model":
        acute = section.get("acute_span_days")
        chronic = section.get("chronic_span_days")
        derivation = section.get("daily_load_derivation", {})
        return (
            isinstance(acute, int)
            and not isinstance(acute, bool)
            and isinstance(chronic, int)
            and not isinstance(chronic, bool)
            and 1 <= acute < chronic
            and derivation.get("input_field") == "training_load"
            and _finite_number(derivation.get("scale"))
            and float(derivation["scale"]) > 0
        )
    return False


def load_clinical_guidelines() -> dict[str, Any]:
    global _CLINICAL_GUIDELINES
    if _CLINICAL_GUIDELINES is None:
        path = Path(__file__).parent.parent / "resources" / "clinical_guidelines.json"
        _CLINICAL_GUIDELINES = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
    return _CLINICAL_GUIDELINES


def usable_method_config(
    section_name: str, required_values: list[str]
) -> dict[str, Any] | None:
    """Return an enabled, traceable method section or ``None``."""
    if section_name in HARD_DISABLED_METHOD_SECTIONS:
        return None
    section = load_clinical_guidelines().get(section_name, {})
    if section.get("enabled") is not True:
        return None
    if not _valid_provenance(section_name, section.get("provenance")):
        return None
    for key_path in required_values:
        current: Any = section
        for key in key_path.split("."):
            if not isinstance(current, dict) or current.get(key) is None:
                return None
            current = current[key]
    if not _valid_method_parameters(section_name, section):
        return None
    return section


def parse_time_to_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return int(value)
    try:
        parts = [int(part) for part in str(value).split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] if len(parts) == 1 else None


def _is_observed(value: Any) -> bool:
    """Return true only for a scalar, non-missing observation."""
    if value is None:
        return False
    try:
        return bool(pd.notna(value))
    except (TypeError, ValueError):
        return False


def _records_without_missing(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert pandas missing values to JSON-safe ``None`` values."""
    if frame.empty:
        return []
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict("records")


def _hours_or_none(seconds: Any) -> float | None:
    if not _is_observed(seconds):
        return None
    return round(float(seconds) / 3600, 1)


class DataStaleError(Exception):
    pass


def calc_pmc_metrics(friction_matrix: pd.DataFrame) -> pd.DataFrame:
    """Calculate an experimental load curve only from traceable opt-in config."""
    if friction_matrix.empty:
        return friction_matrix
    config = usable_method_config(
        "training_load_model",
        [
            "acute_span_days",
            "chronic_span_days",
            "daily_load_derivation.input_field",
            "daily_load_derivation.scale",
        ],
    )
    if config is None:
        return friction_matrix.iloc[0:0].copy()
    if "daily_friction_load" not in friction_matrix.columns:
        return friction_matrix.iloc[0:0].copy()
    acute_span = int(config["acute_span_days"])
    chronic_span = int(config["chronic_span_days"])
    if acute_span <= 0 or chronic_span <= acute_span:
        return friction_matrix.iloc[0:0].copy()
    result = friction_matrix.copy()
    result["daily_friction_load"] = pd.to_numeric(
        result["daily_friction_load"], errors="coerce"
    )
    result = result.dropna(subset=["daily_friction_load"]).sort_values("date")
    if result.empty:
        return result
    result["ctl"] = result["daily_friction_load"].ewm(
        span=chronic_span, adjust=False
    ).mean()
    result["atl"] = result["daily_friction_load"].ewm(
        span=acute_span, adjust=False
    ).mean()
    result["tsb"] = result["ctl"] - result["atl"]
    result["TSB_Zone"] = "experimental_unclassified"
    return result


def _fetch_local_summary_unverified(
    days: int,
    *,
    components: tuple[str, ...] | list[str] | None = None,
    metadata_components: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    if not HAS_SQLITE:
        raise DataStaleError("Local Garmin database is unavailable.")
    fetch_days = max(int(days), 1)
    requested_components = (
        tuple(LOCAL_SUMMARY_COMPONENTS) if components is None else tuple(components)
    )
    if set(requested_components) - set(LOCAL_SUMMARY_COMPONENTS):
        raise ValueError("local_summary_component_invalid")
    scoped_request = components is not None
    requested_metadata = (
        tuple(LOCAL_METADATA_COMPONENTS)
        if metadata_components is None
        else tuple(metadata_components)
    )
    if set(requested_metadata) - set(LOCAL_METADATA_COMPONENTS):
        raise ValueError("local_summary_metadata_component_invalid")
    requested_set = set(requested_components)
    empty = pd.DataFrame()

    summary_columns_by_component = {
        "heart_rate": ("resting_heart_rate", "max_hr"),
        "stress": (
            "stress_avg",
            "high_stress_duration",
            "medium_stress_duration",
            "rest_stress_duration",
        ),
        "body_battery": (
            "body_battery_highest",
            "body_battery_lowest",
            "body_battery_charged",
        ),
    }
    requested_summary_columns = {
        column
        for component, columns in summary_columns_by_component.items()
        if component in requested_set
        for column in columns
    }
    summary_df = (
        sqlite_summary(fetch_days) if requested_summary_columns else empty.copy()
    )

    summary_observation_columns = [
        column
        for column in requested_summary_columns
        if column in summary_df.columns
    ]
    if summary_observation_columns:
        observed_summary_rows = summary_df[summary_observation_columns].notna().any(axis=1)
    else:
        observed_summary_rows = pd.Series(False, index=summary_df.index)

    sleep_df = sqlite_sleep(fetch_days) if "sleep" in requested_set else empty.copy()
    hrv_df = sqlite_hrv(fetch_days) if "hrv" in requested_set else empty.copy()
    activities_df = (
        sqlite_activities(fetch_days)
        if requested_set & {"activities", "training_load_series"}
        else empty.copy()
    )
    biomechanics_df = (
        sqlite_biomechanics(fetch_days) if not scoped_request else empty.copy()
    )
    activity_source_records = _records_without_missing(activities_df)
    for activity in activity_source_records:
        activity["duration"] = parse_time_to_seconds(activity.get("duration"))

    daily_loads: dict[str, float] = {}
    for activity in activity_source_records:
        day = activity.get("date")
        load = activity.get("training_load")
        if day and _is_observed(load):
            daily_loads[day] = daily_loads.get(day, 0.0) + float(load)
    activities = activity_source_records if "activities" in requested_set else []

    load_config = (
        usable_method_config(
            "training_load_model",
            [
                "acute_span_days",
                "chronic_span_days",
                "daily_load_derivation.input_field",
                "daily_load_derivation.scale",
            ],
        )
        if "training_load_series" in requested_set
        else None
    )
    pmc = pd.DataFrame()
    if load_config:
        load_window = int(load_config["chronic_span_days"])
        load_read_days = fetch_days if scoped_request else max(fetch_days, load_window)
        derivation = {
            **load_config["daily_load_derivation"],
            "provenance": load_config["provenance"],
        }
        pmc = calc_pmc_metrics(
            get_daily_friction_matrix(
                load_read_days, derivation_config=derivation
            )
        )
    max_metrics = get_max_metrics() if not scoped_request else {}

    hrv_records = _records_without_missing(
        hrv_df.rename(columns={"hrv_avg": "last_night_avg"})
    )
    for entry in hrv_records:
        entry.setdefault("status", None)

    sleep_records = _records_without_missing(sleep_df)
    summary_records = (
        _records_without_missing(summary_df) if not scoped_request else []
    )

    def selected_frame(columns: tuple[str, ...]) -> pd.DataFrame:
        selected = ["date"] if "date" in summary_df.columns else []
        selected.extend(column for column in columns if column in summary_df.columns)
        return summary_df.loc[:, selected].copy() if selected else empty.copy()

    heart_rate_records = (
        _records_without_missing(
            selected_frame(summary_columns_by_component["heart_rate"]).rename(
                columns={"resting_heart_rate": "resting_hr"}
            )
        )
        if "heart_rate" in requested_set
        else []
    )
    stress_records = (
        _records_without_missing(
            selected_frame(summary_columns_by_component["stress"]).rename(
                columns={"stress_avg": "avg_stress"}
            )
        )
        if "stress" in requested_set
        else []
    )
    body_battery_records = (
        _records_without_missing(
            selected_frame(summary_columns_by_component["body_battery"]).rename(
                columns={
                    "body_battery_highest": "highest",
                    "body_battery_lowest": "lowest",
                    "body_battery_charged": "charged",
                }
            )
        )
        if "body_battery" in requested_set
        else []
    )
    training_load_records = (
        [
            {"date": day, "acute_load": value}
            for day, value in sorted(daily_loads.items())
        ]
        if "training_load_series" in requested_set
        else []
    )

    component_specs = {
        "sleep": (
            sleep_records,
            (
                "sleep_time_seconds",
                "sleep_score",
                "avg_respiration",
                "avg_spo2",
            ),
        ),
        "hrv": (hrv_records, ("last_night_avg",)),
        "body_battery": (
            body_battery_records,
            ("highest", "lowest", "charged"),
        ),
        "heart_rate": (heart_rate_records, ("resting_hr", "max_hr")),
        "activities": (
            activities,
            ("activity_id", "duration", "calories", "training_load"),
        ),
        "stress": (
            stress_records,
            (
                "avg_stress",
                "high_stress_duration",
                "medium_stress_duration",
                "rest_stress_duration",
            ),
        ),
        "training_load_series": (training_load_records, ("acute_load",)),
    }

    def component_coverage(
        records: list[dict[str, Any]], fields: tuple[str, ...]
    ) -> dict[str, Any]:
        observed_records = [
            item
            for item in records
            if any(_is_observed(item.get(field)) for field in fields)
        ]
        observed_dates = {
            str(item.get("date"))[:10]
            for item in observed_records
            if item.get("date")
        }
        observed_days = len(observed_dates)
        return {
            "status": (
                "no_data"
                if observed_days == 0
                else "complete"
                if observed_days >= fetch_days
                else "partial"
            ),
            "observed_days": observed_days,
            "observed_records": len(observed_records),
        }

    component_status = {
        name: (
            component_coverage(*component_specs[name])
            if name in requested_components
            else {"status": "not_requested", "observed_days": 0, "observed_records": 0}
        )
        for name in LOCAL_SUMMARY_COMPONENTS
    }
    component_status["training_load_series"].update(
        {
            "coverage_semantics": "event_stream",
            "zero_semantics": "unknown",
        }
    )
    if (
        "training_load_series" in requested_components
        and component_status["training_load_series"]["status"] != "no_data"
    ):
        # An activity event stream is not expected to contain one record per day.
        component_status["training_load_series"]["status"] = "observed"
    requested_statuses = [
        component_status[name]["status"] for name in requested_components
    ]
    overall_status = (
        "metadata_only"
        if not requested_statuses
        else "no_data"
        if all(status == "no_data" for status in requested_statuses)
        else "complete"
        if all(status == "complete" for status in requested_statuses)
        else "partial"
    )

    observed_dates = []
    for component in requested_components:
        records, fields = component_specs[component]
        for item in records:
            if not any(_is_observed(item.get(field)) for field in fields):
                continue
            day = item.get("date")
            if not day:
                continue
            try:
                observed_dates.append(datetime.strptime(str(day)[:10], "%Y-%m-%d"))
            except ValueError:
                continue
    is_stale = (
        True
        if not observed_dates
        else (datetime.now() - max(observed_dates)).days >= 1
    )

    if scoped_request:
        data_gaps = [
            f"No observed {component} metrics in the requested range."
            for component in requested_components
            if component_status[component]["status"] == "no_data"
        ]
    else:
        data_gaps = []
        if not observed_summary_rows.any():
            data_gaps.append(
                "No observed daily-summary metrics in the requested range."
            )
        if not any(
            _is_observed(item.get("sleep_time_seconds")) for item in sleep_records
        ):
            data_gaps.append("No observed sleep duration in the requested range.")
        if not any(_is_observed(item.get("last_night_avg")) for item in hrv_records):
            data_gaps.append("No observed HRV in the requested range.")

    device_info = (
        _records_without_missing(get_devices_info())
        if "device_info" in requested_metadata
        else []
    )
    firmware_history = (
        _records_without_missing(get_device_firmware_history())
        if "firmware_history" in requested_metadata
        else []
    )
    if scoped_request:
        device_info = [
            {
                "serial_number": item.get("serial_number"),
                "software_version": item.get("software_version"),
            }
            for item in device_info
        ]
        firmware_history = [
            {
                "timestamp": item.get("timestamp"),
                "serial_number": item.get("serial_number"),
                "software_version": item.get("software_version"),
            }
            for item in firmware_history
        ]
    body_composition_detailed = (
        _records_without_missing(get_body_composition_detailed(fetch_days))
        if not scoped_request
        else []
    )
    return {
        "status": overall_status,
        "summary": {"days": fetch_days},
        "heart_rate": heart_rate_records,
        "stress": stress_records,
        "body_battery": body_battery_records,
        "sleep": sleep_records,
        "hrv": hrv_records,
        "activities": activities,
        "biomechanics": _records_without_missing(biomechanics_df),
        "daily_summary": summary_records,
        "training_load_series": training_load_records,
        "pmc": _records_without_missing(pmc),
        "device_info": device_info,
        "measurement_epoch_evidence": {
            "analysis_algorithm_epoch": BASELINE_ALGORITHM_EPOCH,
            "manufacturer_algorithm_epoch": "not_available_in_local_schema",
            "firmware_epoch_proxy": "serial_number_and_software_version",
            "firmware_history": firmware_history,
        },
        "body_composition_detailed": body_composition_detailed,
        "training_status": {
            "vo2_max": max_metrics.get("vo2_max"),
            "load_status": "experimental_unclassified" if not pmc.empty else "not_computed",
            "load_ratio": (
                round(float(pmc.iloc[-1]["atl"]) / float(pmc.iloc[-1]["ctl"]), 2)
                if (
                    not pmc.empty
                    and _is_observed(pmc.iloc[-1]["ctl"])
                    and float(pmc.iloc[-1]["ctl"]) > 0
                )
                else None
            ),
        },
        "max_metrics": max_metrics,
        "body_composition": {},
        "is_stale": is_stale,
        "data_gaps": data_gaps,
        "coverage": {
            "requested_days": fetch_days,
            "components": component_status,
            "metadata_components": list(requested_metadata),
        },
        "component_status": component_status,
    }


def _verified_local_read_window(database_paths=None, *, components=None):
    if database_paths is not None:
        # Explicit caller scope always wins over inferred component scope.
        paths = list(database_paths)
    elif components is not None:
        requested = set(components)
        paths = [GARMIN_DB]
        if requested & {"activities", "training_load_series"}:
            paths.append(ACTIVITIES_DB)
    else:
        paths = [GARMIN_DB, ACTIVITIES_DB]
    return verified_database_read_window(paths)


def fetch_local_summary(
    days: int,
    database_paths: list[str | Path] | None = None,
    *,
    components: tuple[str, ...] | list[str] | None = None,
    metadata_components: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Read local data only if all used databases remain byte-for-byte stable."""
    if not HAS_SQLITE:
        raise DataStaleError("Local Garmin database is unavailable.")
    window = _verified_local_read_window(database_paths, components=components)
    with window:
        summary = _fetch_local_summary_unverified(
            days,
            components=components,
            metadata_components=metadata_components,
        )
    summary["data_integrity"] = window.public_summary()
    return summary


def parse_period(period_str: str | None, days_int: int) -> int:
    if period_str is not None:
        if period_str == "YTD":
            today = date.today()
            return (today - date(today.year, 1, 1)).days + 1
        match = re.fullmatch(r"([1-9][0-9]*)d", period_str)
        if not match:
            raise ValueError("INVALID_PERIOD_SCOPE")
        return int(match.group(1))
    if (
        not isinstance(days_int, int)
        or isinstance(days_int, bool)
        or days_int < 1
    ):
        raise ValueError("INVALID_PERIOD_SCOPE")
    return days_int


def _records_with_value(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [record for record in records if _is_observed(record.get(key))]


def _normalize_dated_numeric_values(
    records: list[dict[str, Any]], key: str
) -> tuple[dict[str, float], list[str]]:
    """Normalize one value per day and surface conflicting duplicates.

    Repeated identical observations are idempotent. If two different finite
    values claim the same date, that date is removed from the normalized series
    and returned as a conflict instead of silently accepting the last record.
    """
    values: dict[str, float] = {}
    conflicts: set[str] = set()
    for record in records:
        day = record.get("date")
        value = record.get(key)
        if not day or not _is_observed(value):
            continue
        day_text = str(day)
        try:
            datetime.strptime(day_text, "%Y-%m-%d")
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(numeric) or day_text in conflicts:
            continue
        if day_text in values and values[day_text] != numeric:
            conflicts.add(day_text)
            values.pop(day_text, None)
        else:
            values[day_text] = numeric
    return values, sorted(conflicts)


def _epoch_comparability(
    summary_data: dict[str, Any], observation_dates: list[str]
) -> dict[str, Any]:
    """Conservatively test whether one baseline crosses known firmware epochs."""
    evidence = summary_data.get("measurement_epoch_evidence") or {}
    algorithm_epoch = evidence.get("analysis_algorithm_epoch")
    manufacturer_epoch = evidence.get("manufacturer_algorithm_epoch")

    def known_epoch(value: Any) -> bool:
        return str(value or "").strip().casefold() not in {
            "",
            "unknown",
            "unverified",
            "not_available",
            "not_available_in_local_schema",
        }

    analysis_epoch_known = known_epoch(algorithm_epoch)
    manufacturer_epoch_known = known_epoch(manufacturer_epoch)
    history = evidence.get("firmware_history") or []
    events_by_serial: dict[str, list[tuple[datetime, str]]] = {}
    for item in history:
        serial = item.get("serial_number")
        firmware = item.get("software_version")
        timestamp = item.get("timestamp")
        if not serial or not firmware or not timestamp:
            continue
        try:
            observed_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if observed_at.tzinfo is not None:
                observed_at = observed_at.replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        events_by_serial.setdefault(str(serial), []).append(
            (observed_at, str(firmware))
        )
    for events in events_by_serial.values():
        events.sort(key=lambda item: (item[0], item[1]))

    observed_epochs = set()
    unknown_dates = []
    for day in observation_dates:
        try:
            day_end = datetime.fromisoformat(f"{day}T23:59:59.999999")
        except ValueError:
            unknown_dates.append(day)
            continue
        matched = False
        for serial, events in events_by_serial.items():
            effective = [item for item in events if item[0] <= day_end]
            if effective:
                observed_epochs.add(f"{serial}|{effective[-1][1]}")
                matched = True
        if not matched:
            unknown_dates.append(day)

    cross_epoch = len(observed_epochs) > 1
    comparable = False if cross_epoch else None
    if (
        not cross_epoch
        and len(observed_epochs) == 1
        and not unknown_dates
        and analysis_epoch_known
        and manufacturer_epoch_known
    ):
        comparable = True
    status = "epoch_unknown"
    if cross_epoch:
        status = "cross_epoch"
    elif not manufacturer_epoch_known:
        status = "manufacturer_algorithm_epoch_unknown"
    elif not analysis_epoch_known:
        status = "analysis_algorithm_epoch_unknown"
    elif comparable is True:
        status = "single_known_epoch"
    return {
        "comparable": comparable,
        "status": status,
        "observed_epochs": sorted(observed_epochs),
        "analysis_algorithm_epoch": algorithm_epoch,
        "analysis_algorithm_epoch_known": analysis_epoch_known,
        "manufacturer_algorithm_epoch": manufacturer_epoch or "not_available",
        "manufacturer_algorithm_epoch_known": manufacturer_epoch_known,
        "unknown_observation_dates": unknown_dates,
    }


PATTERN_METRICS = {
    "rhr": {
        "label": "静息心率趋势",
        "component": "heart_rate",
        "records_key": "heart_rate",
        "field": "resting_hr",
        "unit": "bpm",
    },
    "hrv": {
        "label": "HRV 趋势",
        "component": "hrv",
        "records_key": "hrv",
        "field": "last_night_avg",
        "unit": "ms",
    },
    "sleep_duration": {
        "label": "睡眠总时长趋势",
        "component": "sleep",
        "records_key": "sleep",
        "field": "sleep_time_seconds",
        "unit": "s",
    },
    "sleep_respiration": {
        "label": "夜间呼吸率趋势",
        "component": "sleep",
        "records_key": "sleep",
        "field": "avg_respiration",
        "unit": "brpm",
    },
    "sleep_spo2": {
        "label": "夜间 Pulse Ox 趋势",
        "component": "sleep",
        "records_key": "sleep",
        "field": "avg_spo2",
        "unit": "%",
    },
}
PATTERN_COMPARISON_FIELDS = (
    "baseline_median",
    "baseline_mad",
    "recent_median",
    "absolute_delta",
    "robust_z",
    "direction",
)


def _pattern_requested_dates(
    summary_data: dict[str, Any],
    requested_start: str | None,
    requested_end: str | None,
) -> list[str]:
    if bool(requested_start) != bool(requested_end):
        raise ValueError("PATTERN_RANGE_REQUIRES_START_AND_END")
    if requested_start is None:
        days = (summary_data.get("summary") or {}).get("days")
        days = parse_period(None, days)
        requested_start, requested_end = get_date_range(days)
    try:
        start = datetime.strptime(str(requested_start), "%Y-%m-%d").date()
        end = datetime.strptime(str(requested_end), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("INVALID_PATTERN_RANGE") from exc
    if end < start:
        raise ValueError("INVALID_PATTERN_RANGE")
    return [
        (start + timedelta(days=offset)).isoformat()
        for offset in range((end - start).days + 1)
    ]


def _pattern_component_requested(
    summary_data: dict[str, Any], component: str
) -> bool:
    component_status = summary_data.get("component_status") or {}
    status = (
        component_status.get(component, {}).get("status")
        if isinstance(component_status.get(component), dict)
        else None
    )
    if status == "not_requested":
        return False
    data_keys = {
        "sleep": ("sleep",),
        "hrv": ("hrv",),
        "heart_rate": ("heart_rate",),
        "training_load_series": ("training_load_series",),
    }
    return status is not None or any(key in summary_data for key in data_keys[component])


def _withhold_pattern_comparison(
    result: dict[str, Any], status: str, limitation: str
) -> dict[str, Any]:
    withheld = dict(result)
    withheld["status"] = status
    for field in PATTERN_COMPARISON_FIELDS:
        withheld[field] = None
    withheld["limitations"] = list(
        dict.fromkeys([*(result.get("limitations") or []), limitation])
    )
    return withheld


def _pattern_reason(result: dict[str, Any]) -> str:
    status = result.get("status")
    if status == "eligible" and result.get("absolute_delta") is not None:
        delta = round(float(result["absolute_delta"]), 3)
        robust_z = result.get("robust_z")
        z_text = "未标准化" if robust_z is None else f"稳健 z={float(robust_z):.2f}"
        return (
            f"最近 7 日中位数相对历史中位数变化 {delta:+g}；{z_text}；"
            "方向只描述高低，不代表健康好坏。"
        )
    if status == "eligible" and result.get("paired_days") is not None:
        return "满足精确日期配对门槛；只报告探索性关联，相关不代表因果。"
    if status == "eligible" and result.get("observed_days") is not None:
        return "满足有效夜晚门槛；只描述离散度，不作睡眠疾病判断。"
    reasons = {
        "not_requested": "本次授权范围未包含该数据组件。",
        "duplicate_conflict": "同一日期存在冲突值，衍生比较已停用。",
        "epoch_unknown": "设备或固件时期证据不足，衍生比较已停用。",
        "cross_epoch": "观测跨设备或固件时期，衍生比较已停用。",
        "historical_baseline_insufficient": "需要至少 21 个历史有效日。",
        "insufficient_window": "请求窗口需要覆盖至少 14 个自然日。",
        "recent_window_incomplete": "最近 7 个自然日必须都有有效观测。",
        "zero_baseline_mad": "历史中位绝对偏差为零，不能标准化。",
        "partial_available": "时长离散度可计算；睡眠时点仍受来源限制。",
        "source_not_supported": "当前来源没有所需字段。",
        "timezone_unknown": "时间戳缺少可核验时区。",
        "mixed_utc_offset": "窗口内 UTC 偏移不一致。",
        "insufficient_valid_nights": "需要至少 7 个有效夜晚。",
        "load_coverage_unknown": "空白日不能证明为零训练负荷，相关系数已停用。",
        "insufficient_pairs": "需要至少 28 个精确的 t→t+1 日期配对。",
        "constant_series": "序列没有可用于秩相关的变异。",
        "no_requested_dates": "请求窗口为空。",
    }
    return reasons.get(str(status), "当前数据不满足该分析的计算条件。")


def analyze_health_patterns(
    summary_data: dict[str, Any],
    *,
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> dict[str, Any]:
    """Run scoped, descriptive wearable pattern analyses with explicit gates."""
    requested_dates = _pattern_requested_dates(
        summary_data, requested_start, requested_end
    )
    trends: dict[str, dict[str, Any]] = {}
    continuity: dict[str, dict[str, Any]] = {}
    normalized_by_metric: dict[str, dict[str, Any]] = {}

    for metric_id, spec in PATTERN_METRICS.items():
        records = summary_data.get(spec["records_key"]) or []
        normalized = normalize_daily_numeric(
            records,
            spec["field"],
            requested_dates,
            allow_zero=False,
        )
        normalized_by_metric[metric_id] = normalized
        observed_dates = [str(item["date"]) for item in normalized["facts"]]
        continuity_result = observation_continuity(requested_dates, observed_dates)
        continuity_result.update(
            {
                "derived_value_days": normalized["derived_value_days"],
                "conflicting_duplicate_dates": normalized[
                    "conflicting_duplicate_dates"
                ],
            }
        )
        requested = _pattern_component_requested(summary_data, spec["component"])
        if not requested:
            continuity_result["status"] = "not_requested"
            continuity_result["limitations"] = ["component_not_requested"]
            epoch = {"comparable": None, "status": "not_requested"}
        else:
            epoch = _epoch_comparability(summary_data, observed_dates)
        trend = robust_personal_trend(
            records,
            spec["field"],
            requested_dates,
            epoch_comparable=epoch["comparable"],
            epoch_status=epoch["status"],
            baseline_min_days=21,
            recent_window_days=7,
            allow_zero=False,
        )
        trend.update({"label": spec["label"], "unit": spec["unit"]})
        if not requested:
            trend = _withhold_pattern_comparison(
                trend, "not_requested", "component_not_requested"
            )
        elif normalized["conflicting_duplicate_dates"]:
            trend = _withhold_pattern_comparison(
                trend, "duplicate_conflict", "conflicting_duplicates_fail_closed"
            )
        trends[metric_id] = trend
        continuity[metric_id] = continuity_result

    sleep_requested = _pattern_component_requested(summary_data, "sleep")
    sleep_observation_dates = sorted(
        {
            str(record.get("date"))
            for record in summary_data.get("sleep") or []
            if isinstance(record, dict)
            and str(record.get("date")) in set(requested_dates)
        }
    )
    sleep_epoch = (
        _epoch_comparability(summary_data, sleep_observation_dates)
        if sleep_requested
        else {"comparable": None, "status": "not_requested"}
    )
    sleep_regularity = sleep_regularity_snapshot(
        summary_data.get("sleep") or [],
        requested_dates,
        epoch_comparable=sleep_epoch["comparable"],
        epoch_status=sleep_epoch["status"],
        window_days=14,
        min_valid_nights=7,
    )
    if not sleep_requested:
        sleep_regularity.update(
            {
                "status": "not_requested",
                "duration_status": "not_requested",
                "timing_status": "not_requested",
                "limitations": ["component_not_requested"],
            }
        )
    elif len(requested_dates) < 14:
        sleep_regularity.update(
            {
                "status": "insufficient_window",
                "duration_status": "insufficient_window",
                "timing_status": "insufficient_window",
                "duration_sd_hours": None,
                "bedtime_circular_sd_hours": None,
                "midpoint_circular_sd_hours": None,
                "wake_time_circular_sd_hours": None,
                "limitations": list(
                    dict.fromkeys(
                        [
                            *(sleep_regularity.get("limitations") or []),
                            "fourteen_calendar_day_window_required",
                        ]
                    )
                ),
            }
        )
    elif normalized_by_metric["sleep_duration"]["conflicting_duplicate_dates"]:
        sleep_regularity.update(
            {
                "status": "duplicate_conflict",
                "duration_status": "duplicate_conflict",
                "duration_sd_hours": None,
                "limitations": list(
                    dict.fromkeys(
                        [
                            *(sleep_regularity.get("limitations") or []),
                            "conflicting_sleep_duration_duplicates_fail_closed",
                        ]
                    )
                ),
            }
        )

    load_requested = _pattern_component_requested(
        summary_data, "training_load_series"
    )
    load_status = (summary_data.get("component_status") or {}).get(
        "training_load_series", {}
    )
    load_semantics = (
        "explicit_daily_zero"
        if load_status.get("zero_semantics") == "explicit_daily_zero"
        else "unknown"
    )
    load_records = summary_data.get("training_load_series") or []
    outcome_specs = {
        "rhr": (summary_data.get("heart_rate") or [], "resting_hr"),
        "hrv": (summary_data.get("hrv") or [], "last_night_avg"),
        "sleep_duration": (
            summary_data.get("sleep") or [],
            "sleep_time_seconds",
        ),
    }
    lagged_associations: dict[str, dict[str, Any]] = {}
    for outcome_id, (outcome_records, outcome_field) in outcome_specs.items():
        outcome_requested = _pattern_component_requested(
            summary_data, PATTERN_METRICS[outcome_id]["component"]
        )
        outcome_dates = [
            str(item["date"])
            for item in normalized_by_metric[outcome_id]["values"]
        ]
        load_dates = [
            str(item["date"])
            for item in normalize_daily_numeric(
                load_records,
                "acute_load",
                requested_dates,
                allow_zero=True,
            )["values"]
        ]
        association_epoch = _epoch_comparability(
            summary_data, sorted(set(load_dates) | set(outcome_dates))
        )
        association = lagged_rank_association(
            load_records,
            "acute_load",
            outcome_records,
            outcome_field,
            requested_dates,
            exposure_coverage_semantics=load_semantics,
            epoch_comparable=association_epoch["comparable"],
            epoch_status=association_epoch["status"],
            min_pairs=28,
            outcome_allow_zero=False,
        )
        if not load_requested or not outcome_requested:
            association.update(
                {
                    "status": "not_requested",
                    "spearman_rho": None,
                    "limitations": [
                        "training_load_component_not_requested"
                        if not load_requested
                        else "outcome_component_not_requested"
                    ],
                }
            )
        lagged_associations[outcome_id] = association

    eligibility: list[dict[str, Any]] = []
    for metric_id, result in trends.items():
        eligibility.append(
            {
                "id": f"trend_{metric_id}",
                "label": result["label"],
                "status": result["status"],
                "observed_days": result["historical_sample_days"]
                + result["recent_sample_days"],
                "required_days": 28,
                "epoch_status": result["epoch_status"],
                "reason": _pattern_reason(result),
            }
        )
    for regularity_id, label, status_field, observed_field in (
        (
            "sleep_duration_regularity",
            "睡眠时长离散度",
            "duration_status",
            "duration_valid_nights",
        ),
        (
            "sleep_timing_regularity",
            "睡眠时点离散度",
            "timing_status",
            "timing_valid_nights",
        ),
    ):
        item = {
            "id": regularity_id,
            "label": label,
            "status": sleep_regularity[status_field],
            "observed_days": sleep_regularity[observed_field],
            "required_days": 7,
            "epoch_status": sleep_regularity["epoch_status"],
        }
        item["reason"] = _pattern_reason(item)
        eligibility.append(item)
    for outcome_id, result in lagged_associations.items():
        label = PATTERN_METRICS[outcome_id]["label"].removesuffix("趋势")
        item = {
            "id": f"load_to_next_day_{outcome_id}",
            "label": f"训练负荷→次日{label}",
            "status": result["status"],
            "paired_days": result["pair_count"],
            "required_pairs": result["min_pairs"],
            "epoch_status": result["epoch_status"],
        }
        item["reason"] = _pattern_reason(item)
        eligibility.append(item)

    eligible_count = sum(item["status"] == "eligible" for item in eligibility)
    overall_status = (
        "available"
        if eligible_count == len(eligibility)
        else "partial_available"
        if eligible_count
        else "no_eligible_analyses"
    )
    return {
        "analysis_type": "descriptive_health_patterns",
        "status": overall_status,
        "method_version": PATTERN_METHOD_VERSION,
        "medical_interpretation": False,
        "requested_range": {
            "start": requested_dates[0],
            "end": requested_dates[-1],
            "days": len(requested_dates),
            "expanded_beyond_request": False,
        },
        "eligibility": eligibility,
        "continuity": continuity,
        "trends": trends,
        "sleep_regularity": sleep_regularity,
        "lagged_associations": lagged_associations,
        "metric_lineage": [
            {
                "metric": "sleep_score",
                "shared_upstream_inputs": [
                    "sleep_duration",
                    "sleep_stages",
                    "night_stress",
                    "hrv",
                ],
                "independent_corroboration": False,
            },
            {
                "metric": "body_battery",
                "shared_upstream_inputs": [
                    "hrv",
                    "stress",
                    "sleep",
                    "activity",
                ],
                "independent_corroboration": False,
            },
        ],
        "lineage_warning": (
            "睡眠评分与 Body Battery 共享睡眠、HRV、压力等上游输入，"
            "不能把它们当作独立证据叠加，也不生成健康总分。"
        ),
        "limitations": [
            "所有结果仅描述消费级可穿戴设备的个人内变化，不作医疗解释。",
            "缺失值不填零；冲突重复、时期未知和跨时期比较均失败关闭。",
            "秩相关仅在明确的每日零值语义与精确 t→t+1 配对下计算，相关不代表因果。",
        ],
    }


def analyze_baseline_change(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Describe personal-baseline changes without assigning disease risk."""
    hrv_by_date, hrv_conflicts = _normalize_dated_numeric_values(
        summary_data.get("hrv", []), "last_night_avg"
    )
    rhr_by_date, rhr_conflicts = _normalize_dated_numeric_values(
        summary_data.get("heart_rate", []), "resting_hr"
    )
    resp_by_date, resp_conflicts = _normalize_dated_numeric_values(
        summary_data.get("sleep", []), "avg_respiration"
    )
    duplicate_conflicts = {
        name: dates
        for name, dates in (
            ("hrv", hrv_conflicts),
            ("resting_heart_rate", rhr_conflicts),
            ("sleep_respiration", resp_conflicts),
        )
        if dates
    }
    paired_dates = sorted(set(hrv_by_date) & set(rhr_by_date))
    current_date = paired_dates[-1] if paired_dates else None
    prior_dates = paired_dates[:-1]
    epoch_comparability = _epoch_comparability(summary_data, paired_dates)
    if duplicate_conflicts:
        return {
            "analysis_type": "personal_baseline_change_signal",
            "status": "duplicate_conflict",
            "date": current_date,
            "paired_observation_date": current_date,
            "classification": "not_classified",
            "medical_interpretation": False,
            "duplicate_conflicts": duplicate_conflicts,
            "epoch_comparability": epoch_comparability,
            "metrics": {
                "rhr_z_score": None,
                "hrv_z_score": None,
                "paired_baseline_days": len(prior_dates),
                "required_paired_baseline_days": MIN_PAIRED_BASELINE_DAYS,
            },
            "observations": [],
            "limitations": [
                "Conflicting values were recorded for the same date, so the signal is not classified.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }
    if len(prior_dates) < MIN_PAIRED_BASELINE_DAYS:
        return {
            "analysis_type": "personal_baseline_change_signal",
            "status": "insufficient_baseline",
            "date": current_date,
            "paired_observation_date": current_date,
            "classification": "not_classified",
            "medical_interpretation": False,
            "epoch_comparability": epoch_comparability,
            "metrics": {
                "paired_baseline_days": len(prior_dates),
                "required_paired_baseline_days": MIN_PAIRED_BASELINE_DAYS,
                "baseline_start_date": prior_dates[0] if prior_dates else None,
                "baseline_end_date": prior_dates[-1] if prior_dates else None,
            },
            "limitations": [
                f"At least {MIN_PAIRED_BASELINE_DAYS} prior same-date HRV and resting-heart-rate observations are required.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

    prev_hrv = [hrv_by_date[day] for day in prior_dates]
    prev_rhr = [rhr_by_date[day] for day in prior_dates]
    prev_resp = [resp_by_date[day] for day in prior_dates if day in resp_by_date]
    current_hrv = hrv_by_date[current_date]
    current_rhr = rhr_by_date[current_date]
    current_resp = resp_by_date.get(current_date)
    observed_hrv_mean = statistics.mean(prev_hrv)
    observed_rhr_mean = statistics.mean(prev_rhr)
    observed_resp_median = statistics.median(prev_resp) if prev_resp else None

    if epoch_comparability["comparable"] is False:
        return {
            "analysis_type": "personal_baseline_change_signal",
            "status": "not_comparable",
            "date": current_date,
            "paired_observation_date": current_date,
            "classification": "not_comparable_cross_epoch",
            "medical_interpretation": False,
            "epoch_comparability": epoch_comparability,
            "metrics": {
                "paired_baseline_days": len(prior_dates),
                "required_paired_baseline_days": MIN_PAIRED_BASELINE_DAYS,
                "baseline_start_date": prior_dates[0] if prior_dates else None,
                "baseline_end_date": prior_dates[-1] if prior_dates else None,
            },
            "observations": [],
            "limitations": [
                "The paired baseline crosses known device or firmware epochs and is not treated as comparable.",
                "Firmware is only a proxy because the manufacturer algorithm epoch is unavailable in the local schema.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

    if epoch_comparability["comparable"] is None:
        return {
            "analysis_type": "personal_baseline_change_signal",
            "status": "epoch_unknown",
            "date": current_date,
            "paired_observation_date": current_date,
            "classification": "epoch_unknown_unclassified",
            "medical_interpretation": False,
            "epoch_comparability": epoch_comparability,
            "configuration_status": "not_evaluated_epoch_unknown",
            "metrics": {
                "current_rhr": current_rhr,
                "baseline_rhr": None,
                "historical_observed_rhr_mean": round(observed_rhr_mean, 1),
                "rhr_absolute_change_from_historical_observed_mean": round(
                    current_rhr - observed_rhr_mean, 1
                ),
                "current_hrv": current_hrv,
                "baseline_hrv": None,
                "historical_observed_hrv_mean": round(observed_hrv_mean, 1),
                "hrv_absolute_change_from_historical_observed_mean": round(
                    current_hrv - observed_hrv_mean, 1
                ),
                "current_resp": current_resp,
                "baseline_resp": None,
                "historical_observed_resp_median": (
                    round(observed_resp_median, 1)
                    if observed_resp_median is not None
                    else None
                ),
                "resp_absolute_change_from_historical_observed_median": (
                    round(current_resp - observed_resp_median, 1)
                    if current_resp is not None and observed_resp_median is not None
                    else None
                ),
                "rhr_z_score": None,
                "hrv_z_score": None,
                "paired_baseline_days": len(prior_dates),
                "required_paired_baseline_days": MIN_PAIRED_BASELINE_DAYS,
                "baseline_start_date": None,
                "baseline_end_date": None,
                "historical_observation_start_date": prior_dates[0],
                "historical_observation_end_date": prior_dates[-1],
            },
            "observations": [
                "设备或固件测量时代不可确认；仅报告原始值与相对历史观测均值的绝对变化。"
            ],
            "limitations": [
                "Unknown measurement epochs prevent qualification of the historical observations as a comparable baseline.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

    baseline_hrv = observed_hrv_mean
    baseline_rhr = observed_rhr_mean
    baseline_resp = observed_resp_median
    std_hrv = statistics.stdev(prev_hrv)
    std_rhr = statistics.stdev(prev_rhr)
    z_hrv = (current_hrv - baseline_hrv) / std_hrv if std_hrv > 0 else None
    z_rhr = (current_rhr - baseline_rhr) / std_rhr if std_rhr > 0 else None
    resp_delta = (
        current_resp - baseline_resp
        if current_resp is not None and baseline_resp is not None
        else None
    )

    config = usable_method_config(
        "screening_signal",
        [
            "baseline_min_days",
            "thresholds.rhr_z_score_min",
            "thresholds.hrv_z_score_max",
            "thresholds.respiration_delta_min",
        ],
    )
    zero_variance = z_hrv is None or z_rhr is None
    classification = "unclassifiable_zero_variance" if zero_variance else "not_classified"
    if (
        config
        and not zero_variance
        and len(prior_dates) >= int(config["baseline_min_days"])
    ):
        thresholds = config["thresholds"]
        detected = (
            z_rhr >= float(thresholds["rhr_z_score_min"])
            and z_hrv <= float(thresholds["hrv_z_score_max"])
            and resp_delta is not None
            and resp_delta >= float(thresholds["respiration_delta_min"])
        )
        classification = (
            "change_signal_detected"
            if detected
            else "no_configured_change_signal"
        )

    observations = []
    if zero_variance:
        observations.extend(
            [
                "个人基线方差为零，无法计算可靠的静息心率或 HRV 标准分数。",
                f"静息心率相对基线绝对变化 {current_rhr - baseline_rhr:+.1f} 次/分钟；HRV 绝对变化 {current_hrv - baseline_hrv:+.1f} 毫秒。",
            ]
        )
    else:
        observations.extend(
            [
                f"静息心率相对可用个人基线为 {z_rhr:+.1f} 个标准差。",
                f"HRV 相对可用个人基线为 {z_hrv:+.1f} 个标准差。",
            ]
        )
    if resp_delta is not None:
        observations.append(
            f"睡眠呼吸率相对可用个人中位数变化 {resp_delta:+.1f} 次/分钟。"
        )
    return {
        "analysis_type": "personal_baseline_change_signal",
        "status": "unclassifiable" if zero_variance else "ok",
        "date": current_date,
        "paired_observation_date": current_date,
        "classification": classification,
        "medical_interpretation": False,
        "epoch_comparability": epoch_comparability,
        "configuration_status": (
            "enabled_and_traceable" if config else "not_enabled_or_incomplete"
        ),
        "metrics": {
            "current_rhr": current_rhr,
            "baseline_rhr": round(baseline_rhr, 1),
            "current_hrv": current_hrv,
            "baseline_hrv": round(baseline_hrv, 1),
            "current_resp": current_resp,
            "baseline_resp": (
                round(baseline_resp, 1) if baseline_resp is not None else None
            ),
            "rhr_z_score": round(z_rhr, 3) if z_rhr is not None else None,
            "hrv_z_score": round(z_hrv, 3) if z_hrv is not None else None,
            "paired_baseline_days": len(prior_dates),
            "required_paired_baseline_days": MIN_PAIRED_BASELINE_DAYS,
            "baseline_start_date": prior_dates[0] if prior_dates else None,
            "baseline_end_date": prior_dates[-1] if prior_dates else None,
        },
        "observations": observations,
        "limitations": [
            "这是非诊断性可穿戴设备变化筛查，不是流感、感染或其他疾病诊断。",
            "症状、设备变化、睡眠、训练、旅行、药物和饮酒等都可能造成混杂。",
        ],
    }


def calculate_sleep_consistency(
    sleep_data: list[dict[str, Any]],
) -> tuple[float | None, str]:
    durations = [
        float(item["sleep_time_seconds"]) / 3600
        for item in sleep_data
        if _is_observed(item.get("sleep_time_seconds"))
    ]
    if len(durations) < 2:
        return None, "数据不足"
    return round(statistics.stdev(durations), 2), "仅描述，不分级"


def synthesize_pmc(days: int = 90) -> dict[str, Any] | None:
    config = usable_method_config(
        "training_load_model",
        [
            "acute_span_days",
            "chronic_span_days",
            "daily_load_derivation.input_field",
            "daily_load_derivation.scale",
        ],
    )
    if not HAS_SQLITE or config is None:
        return None
    derivation = {
        **config["daily_load_derivation"],
        "provenance": config["provenance"],
    }
    frame = calc_pmc_metrics(
        get_daily_friction_matrix(days, derivation_config=derivation)
    )
    if frame.empty:
        return None
    latest = frame.iloc[-1]
    acute_span = int(config["acute_span_days"])
    ramp = frame["atl"] - frame["atl"].shift(acute_span)
    return {
        "CTL": round(float(latest["ctl"]), 1),
        "ATL": round(float(latest["atl"]), 1),
        "TSB": round(float(latest["tsb"]), 1),
        "TSB_Zone": "experimental_unclassified",
        "Ramp_Rate": (
            round(float(ramp.iloc[-1]), 1) if pd.notna(ramp.iloc[-1]) else None
        ),
        "Daily_Load": round(float(latest["daily_friction_load"]), 1),
        "method_provenance": config["provenance"],
    }


def analyze_executive_readiness(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Align source observations without combining shared upstream inputs."""
    def dated_records(records, key):
        return {
            str(item["date"]): item
            for item in records
            if item.get("date") and _is_observed(item.get(key))
        }

    sleep_by_date = dated_records(summary_data.get("sleep", []), "sleep_score")
    bb_by_date = dated_records(summary_data.get("body_battery", []), "highest")
    stress_by_date = dated_records(summary_data.get("stress", []), "avg_stress")
    hrv_by_date = dated_records(summary_data.get("hrv", []), "status")
    common_dates = sorted(set(sleep_by_date) & set(bb_by_date) & set(stress_by_date))
    observation_date = common_dates[-1] if common_dates else None
    latest_sleep = sleep_by_date.get(observation_date, {})
    latest_bb = bb_by_date.get(observation_date, {})
    latest_stress = stress_by_date.get(observation_date, {})
    latest_hrv = hrv_by_date.get(observation_date, {})
    inputs = {
        "sleep_score": latest_sleep.get("sleep_score"),
        "body_battery_peak": latest_bb.get("highest"),
        "garmin_stress": latest_stress.get("avg_stress"),
        "garmin_hrv_status": latest_hrv.get("status"),
    }
    return {
        "analysis_type": "executive_readiness",
        "status": "not_scored",
        "score": None,
        "date": observation_date,
        "alignment_status": "same_date" if observation_date else "not_aligned",
        "physical_score": None,
        "cognitive_score": None,
        "inputs": inputs,
        "configuration_status": "composite_disabled_shared_inputs",
        "metric_lineage": {
            "independent_inputs": False,
            "shared_upstream_inputs": ["sleep", "hrv", "stress", "activity"],
        },
        "recommendation": (
            "仅展示同日原始指标；睡眠评分、Body Battery 与压力共享上游信号，"
            "不生成准备度分数或行动等级。"
        ),
    }


def perform_bio_metric_audit(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Build a descriptive audit without clinical or behavioral directives."""
    rhr_by_date, _rhr_conflicts = _normalize_dated_numeric_values(
        summary_data.get("heart_rate", []), "resting_hr"
    )
    ordered_rhr_dates = sorted(rhr_by_date)
    latest_rhr = rhr_by_date[ordered_rhr_dates[-1]] if ordered_rhr_dates else None
    historical_rhrs = [rhr_by_date[day] for day in ordered_rhr_dates[:-1]]
    historical_observed_median = (
        statistics.median(historical_rhrs) if historical_rhrs else None
    )
    strict_baseline = analyze_baseline_change(summary_data)
    strict_metrics = strict_baseline.get("metrics", {})
    strict_epoch = strict_baseline.get("epoch_comparability", {}).get("comparable")
    baseline_rhr = (
        strict_metrics.get("baseline_rhr")
        if strict_epoch is True
        and strict_baseline.get("status") in {"ok", "unclassifiable"}
        else None
    )
    latest_hrv_record = next(
        (
            item
            for item in reversed(summary_data.get("hrv", []))
            if _is_observed(item.get("last_night_avg"))
        ),
        {},
    )
    latest_hrv = latest_hrv_record.get("last_night_avg")
    hrv_status = latest_hrv_record.get("status")
    latest_sleep = next(
        (
            item
            for item in reversed(summary_data.get("sleep", []))
            if _is_observed(item.get("sleep_time_seconds"))
        ),
        {},
    )
    total_sleep_raw = latest_sleep.get("sleep_time_seconds")
    total_sleep = float(total_sleep_raw) if _is_observed(total_sleep_raw) else None
    deep_sleep = latest_sleep.get("deep_sleep_seconds")
    rem_sleep = latest_sleep.get("rem_sleep_seconds")
    deep_pct = (
        float(deep_sleep) / total_sleep * 100
        if total_sleep is not None and total_sleep > 0 and _is_observed(deep_sleep)
        else None
    )
    rem_pct = (
        float(rem_sleep) / total_sleep * 100
        if total_sleep is not None and total_sleep > 0 and _is_observed(rem_sleep)
        else None
    )
    latest_bb = next(
        (
            item
            for item in reversed(summary_data.get("body_battery", []))
            if _is_observed(item.get("highest"))
        ),
        {},
    )
    latest_stress = next(
        (
            item
            for item in reversed(summary_data.get("stress", []))
            if _is_observed(item.get("avg_stress"))
        ),
        {},
    )
    component_coverage = summary_data.get("component_status") or (
        summary_data.get("coverage", {}).get("components", {})
    )
    return {
        "analysis_type": "bio_metric_audit",
        "component_coverage": {
            component: component_coverage.get(component, {"status": "unknown"})
            for component in LIVE_ANALYSIS_COMPONENTS["insight_cn"]
        },
        "system_status": {
            "rhr": {
                "current": latest_rhr,
                "observation_date": ordered_rhr_dates[-1] if ordered_rhr_dates else None,
                "baseline": (
                    round(baseline_rhr, 1) if baseline_rhr is not None else None
                ),
                "baseline_status": strict_baseline.get("status"),
                "historical_observed_median": (
                    round(historical_observed_median, 1)
                    if historical_observed_median is not None
                    else None
                ),
                "delta": (
                    round(latest_rhr - baseline_rhr, 1)
                    if latest_rhr is not None and baseline_rhr is not None
                    else None
                ),
                "status": "descriptive_only" if latest_rhr is not None else "no_data",
            },
            "hrv": {
                "value": latest_hrv,
                "status": hrv_status,
                "observation_date": latest_hrv_record.get("date"),
            },
            "vo2_max": summary_data.get("training_status", {}).get("vo2_max"),
            "fitness_age": summary_data.get("max_metrics", {}).get("fitness_age"),
            "bmi": summary_data.get("body_composition", {}).get("bmi"),
            "is_stale": summary_data.get("is_stale"),
        },
        "recovery_loop": {
            "sleep_architecture": {
                "observation_date": latest_sleep.get("date"),
                "duration_hours": _hours_or_none(total_sleep),
                "duration_status": (
                    "observed" if total_sleep is not None else "no_observation"
                ),
                "deep_pct": round(deep_pct, 1) if deep_pct is not None else None,
                "rem_pct": round(rem_pct, 1) if rem_pct is not None else None,
                "restlessness": latest_sleep.get("restless_periods"),
                "sleep_debt_h": None,
                "sleep_debt_status": "not_provided_by_source",
                "interpretation": "consumer_device_estimate",
            },
            "body_battery": {
                "observation_date": latest_bb.get("date"),
                "charged": latest_bb.get("charged"),
                "peak": latest_bb.get("highest"),
                "lowest": latest_bb.get("lowest"),
                "interpretation": "garmin_proprietary_metric",
            },
        },
        "load_friction": {
            "stress_score": latest_stress.get("avg_stress"),
            "stress_observation_date": latest_stress.get("date"),
            "stress_status": (
                "observed"
                if _is_observed(latest_stress.get("avg_stress"))
                else "no_observation"
            ),
            "dissipation": {
                "high_stress_hours": _hours_or_none(
                    latest_stress.get("high_stress_duration")
                ),
                "medium_stress_hours": _hours_or_none(
                    latest_stress.get("medium_stress_duration")
                ),
                "rest_hours": _hours_or_none(
                    latest_stress.get("rest_stress_duration")
                ),
                "interpretation": "garmin_proprietary_metric",
            },
            "training_load": {
                "ratio": summary_data.get("training_status", {}).get("load_ratio"),
                "status": summary_data.get("training_status", {}).get(
                    "load_status", "not_computed"
                ),
                "interpretation": "source_or_explicit_experimental_value",
            },
        },
        "action_protocol": {
            "move": "unclassified_observation",
            "description": (
                "设备数据只提供观测，不生成训练、补剂、日程、行为或决策命令。"
            ),
            "type": "UNCLASSIFIED",
        },
        "limitations": [
            "消费级可穿戴设备数据不是临床级证据。",
            "本脚本不生成诊断、药物、补剂、训练处方或日程命令。",
        ],
    }


def analyze_env_stress(summary_data: dict[str, Any]) -> dict[str, Any]:
    temperatures = [
        float(item["temperature"])
        for item in summary_data.get("activities", [])
        if _is_observed(item.get("temperature"))
    ]
    return {
        "analysis_type": "environmental_context",
        "status": "observed" if temperatures else "unsupported_by_current_source",
        "average_recorded_temperature_c": (
            round(statistics.mean(temperatures), 1) if temperatures else None
        ),
        "interpretation": (
            "Temperature is recorded as a possible confounder; no physiological effect is inferred."
        ),
    }


def analyze_device_health(summary_data: dict[str, Any]) -> dict[str, Any]:
    devices = summary_data.get("device_info", [])
    records = devices.to_dict("records") if hasattr(devices, "to_dict") else devices
    versions = sorted(
        {
            str(item.get("software_version"))
            for item in records or []
            if _is_observed(item.get("software_version"))
        }
    )
    return {
        "analysis_type": "device_audit",
        "devices": records or [],
        "measurement_epoch_evidence": summary_data.get(
            "measurement_epoch_evidence",
            {
                "analysis_algorithm_epoch": BASELINE_ALGORITHM_EPOCH,
                "manufacturer_algorithm_epoch": "not_available_in_local_schema",
                "firmware_history": [],
            },
        ),
        "observations": (
            [f"Multiple recorded firmware versions: {', '.join(versions)}"]
            if len(versions) > 1
            else []
        ),
    }


def generate_sparkline(data_series: list[Any]) -> str:
    values = [float(value) for value in data_series if _is_observed(value)]
    if not values:
        return "无数据"
    ticks = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    low, high = min(values), max(values)
    if low == high:
        return ticks[3] * len(values)
    return "".join(
        ticks[int((value - low) / (high - low) * (len(ticks) - 1))]
        for value in values
    )


def sleep_midpoint_variability_hours(
    sleep_data: list[dict[str, Any]],
) -> float | None:
    """Return the sample standard deviation of observed sleep midpoints in hours."""
    midpoint_hours = []
    for item in sleep_data[-7:]:
        start_raw = item.get("sleep_start") or item.get("sleep_start_time")
        end_raw = item.get("sleep_end") or item.get("sleep_end_time")
        if not start_raw or not end_raw:
            continue
        try:
            start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if end <= start:
            continue
        midpoint = start + (end - start) / 2
        midpoint_hours.append(
            midpoint.hour
            + midpoint.minute / 60
            + midpoint.second / 3600
            + midpoint.microsecond / 3_600_000_000
        )
    if len(midpoint_hours) < 3:
        return None
    angles = [hour / 24 * 2 * math.pi for hour in midpoint_hours]
    center_angle = math.atan2(
        statistics.mean(math.sin(angle) for angle in angles),
        statistics.mean(math.cos(angle) for angle in angles),
    )
    center_hour = (center_angle % (2 * math.pi)) / (2 * math.pi) * 24
    signed_offsets = [
        (hour - center_hour + 12) % 24 - 12 for hour in midpoint_hours
    ]
    return round(statistics.stdev(signed_offsets), 2)


def calculate_social_jetlag(
    sleep_data: list[dict[str, Any]],
) -> float | None:
    """Deprecated alias; this calculates sleep-midpoint variability, not social jetlag."""
    warnings.warn(
        "calculate_social_jetlag is deprecated; use "
        "sleep_midpoint_variability_hours. The value is sleep-midpoint "
        "variability and is not a medical social-jetlag measure.",
        DeprecationWarning,
        stacklevel=2,
    )
    return sleep_midpoint_variability_hours(sleep_data)


def query_vector_lake(*_args, **_kwargs) -> None:
    """Compatibility hook: health analysis never queries memory automatically."""
    return None


def generate_chinese_insight(summary_data: dict[str, Any]) -> dict[str, Any]:
    audit = perform_bio_metric_audit(summary_data)
    readiness = analyze_executive_readiness(summary_data)
    variability, variability_status = calculate_sleep_consistency(
        summary_data.get("sleep", [])
    )
    period = summary_data.get("summary", {}).get("period", "指定时间段")
    stale_note = "数据可能陈旧。" if audit["system_status"]["is_stale"] else "未标记为陈旧。"
    sleep = audit["recovery_loop"]["sleep_architecture"]

    def display(value: Any, unit: str = "") -> str:
        return f"{value}{unit}" if _is_observed(value) else "无有效观测"

    lines = [
        f"【数据范围】{period}；{stale_note}",
        "【可观察指标】"
        f"静息心率 {display(audit['system_status']['rhr']['current'])}；"
        f"HRV {display(audit['system_status']['hrv']['value'])}；"
        "Body Battery 峰值 "
        f"{display(audit['recovery_loop']['body_battery']['peak'])}；"
        f"Garmin 压力 {display(audit['load_friction']['stress_score'])}。",
        "【睡眠描述】"
        f"最近睡眠时长 {display(sleep['duration_hours'], ' 小时')}"
        f"（观测日期 {sleep['observation_date'] or '未提供'}）；"
        f"深睡占比 {display(sleep['deep_pct'], '%')}；"
        f"REM 占比 {display(sleep['rem_pct'], '%')}；"
        f"睡眠时长标准差 {variability if variability is not None else '数据不足'} 小时"
        f"（{variability_status}）。睡眠阶段为消费级设备估计，不作诊断。",
        "【方法边界】"
        + readiness["recommendation"]
        + " 不从这些指标推断感染、炎症、免疫状态、认知能力或职业表现。",
        "【说明】这些观测不生成训练、休息或日程建议；若变化持续、伴随明显症状或"
        "影响生活，建议携带原始数据咨询合格医疗人员。",
    ]
    chart_insights = {
        "sleep": "展示时长与设备评分，不使用统一深睡阈值。",
        "hrv": "展示个人趋势与 Garmin 原始状态，不诊断疾病。",
        "activities": "展示活动量，不自动生成训练处方。",
        "body_battery": "Garmin 厂商派生指标，仅作描述。",
        "stress": "Garmin 厂商派生指标，仅作描述。",
    }
    return {
        "period": period,
        "chart_insights": chart_insights,
        "overall_insight": "\n\n".join(lines),
        "audit_data": audit,
        "quant_scores": {
            "input": None,
            "loss": None,
            "output": readiness.get("score"),
            "cognitive": None,
            "physical": None,
        },
        "top_insights": [
            {"title": "分析边界", "content": audit["action_protocol"]["description"]},
            {
                "title": "准备度",
                "content": readiness["recommendation"],
            },
        ],
    }


def stitch_v3_metrics(summary_data: dict[str, Any], _days: int) -> dict[str, Any]:
    """Compatibility hook; local extraction already includes available fields."""
    return summary_data


def _load_summary(
    days: int,
    source: str = "local",
    allow_network: bool = False,
    allow_health_data: bool = False,
    analysis: str = "unspecified",
) -> dict[str, Any]:
    if source == "local":
        if not allow_health_data:
            raise PermissionError("HEALTH_DATA_ACCESS_NOT_AUTHORIZED")
        if not HAS_SQLITE:
            raise RuntimeError("Local Garmin database is unavailable.")
        components = LOCAL_ANALYSIS_COMPONENTS.get(analysis)
        if components is None:
            raise RuntimeError("LOCAL_ANALYSIS_SCOPE_INVALID")
        return fetch_local_summary(
            days,
            components=components,
            metadata_components=LOCAL_ANALYSIS_METADATA.get(analysis, ()),
        )
    if source != "live":
        raise ValueError("source must be 'local' or 'live'")
    if not allow_network:
        raise PermissionError("NETWORK_ACCESS_NOT_AUTHORIZED")
    if not allow_health_data:
        raise PermissionError("HEALTH_DATA_ACCESS_NOT_AUTHORIZED")
    if analysis in LIVE_UNSUPPORTED_ANALYSES:
        raise RuntimeError("LIVE_ANALYSIS_NOT_SUPPORTED")
    components = LIVE_ANALYSIS_COMPONENTS.get(analysis)
    if components is None:
        raise RuntimeError("LIVE_ANALYSIS_SCOPE_INVALID")
    start_date, end_date = get_date_range(days)
    request = {
        "analysis": analysis,
        "source": "live",
        "start": start_date,
        "end": end_date,
        "components": list(components),
    }
    network_capability = issue_capability(
        scope="network",
        operation=LIVE_SUMMARY_OPERATION,
        request=request,
    )
    health_data_capability = issue_capability(
        scope="health_data",
        operation=LIVE_SUMMARY_OPERATION,
        request=request,
    )
    client = get_client(
        network_capability=network_capability,
        operation=LIVE_SUMMARY_OPERATION,
        request=request,
    )
    if not client:
        raise RuntimeError("LIVE_AUTH_UNAVAILABLE")
    consume_capability(
        health_data_capability,
        scope="health_data",
        operation=LIVE_SUMMARY_OPERATION,
        request=request,
    )
    result = fetch_summary(
        client,
        start=start_date,
        end=end_date,
        components=components,
    )
    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError("HEALTH_DATA_LOAD_FAILED")
    return result


def _write_state_output(
    result: dict[str, Any],
    output_path: str | Path,
    overwrite: bool = False,
    *,
    allow_state_write: bool = False,
) -> Path:
    """Persist a minimal state record only to an explicitly authorized file."""
    if allow_state_write is not True:
        raise PermissionError("State persistence requires explicit allow_state_write=True")
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "analysis_type": result.get("analysis_type"),
        "status": result.get("status"),
        "medical_interpretation": False,
    }
    with output.open("w" if overwrite else "x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Non-diagnostic Garmin wearable-data analysis."
    )
    parser.add_argument(
        "analysis",
        choices=[
            "baseline_change",
            "readiness",
            "insight_cn",
            "audit",
            "long_term_load",
            "env_stress",
            "device_audit",
            "patterns",
        ],
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--period")
    parser.add_argument("--source", choices=["local", "live"], default="local")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-health-data", action="store_true")
    parser.add_argument(
        "--state-output",
        help="Explicit file path for persisting the minimal analysis state",
    )
    parser.add_argument(
        "--overwrite-state",
        action="store_true",
        help="Allow replacement of an existing --state-output file",
    )
    args = parser.parse_args()
    if args.days is not None and args.period:
        print(json.dumps({"status": "INVALID_PERIOD_SCOPE"}), file=sys.stderr)
        return 2
    if args.source == "live" and args.days is None and not args.period:
        print(json.dumps({"status": "EXPLICIT_LIVE_PERIOD_REQUIRED"}), file=sys.stderr)
        return 2
    try:
        days = parse_period(args.period, 7 if args.days is None else args.days)
    except (TypeError, ValueError):
        print(json.dumps({"status": "INVALID_PERIOD_SCOPE"}), file=sys.stderr)
        return 2
    if args.source == "local" and not args.allow_health_data:
        print(json.dumps({"error_code": "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"}), file=sys.stderr)
        return 2
    try:
        summary_data = _load_summary(
            days,
            args.source,
            args.allow_network,
            args.allow_health_data,
            args.analysis,
        )
    except Exception as exc:
        known_codes = {
            "NETWORK_ACCESS_NOT_AUTHORIZED",
            "HEALTH_DATA_ACCESS_NOT_AUTHORIZED",
            "LIVE_AUTH_UNAVAILABLE",
            "HEALTH_DATA_LOAD_FAILED",
            "LIVE_ANALYSIS_NOT_SUPPORTED",
            "LIVE_ANALYSIS_SCOPE_INVALID",
        }
        print(
            json.dumps(
                {
                    "error_code": str(exc) if str(exc) in known_codes else "DATA_SOURCE_FAILURE",
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    if args.analysis == "baseline_change":
        result = analyze_baseline_change(summary_data)
    elif args.analysis == "readiness":
        result = analyze_executive_readiness(summary_data)
    elif args.analysis == "insight_cn":
        result = generate_chinese_insight(summary_data)
    elif args.analysis == "audit":
        result = perform_bio_metric_audit(summary_data)
    elif args.analysis == "long_term_load":
        result = {
            "analysis_type": "experimental_load_index",
            "data": summary_data.get("pmc", []),
            "status": (
                "computed_from_enabled_traceable_config"
                if summary_data.get("pmc")
                else "not_computed"
            ),
        }
    elif args.analysis == "env_stress":
        result = analyze_env_stress(summary_data)
    elif args.analysis == "patterns":
        pattern_start, pattern_end = get_date_range(days)
        result = analyze_health_patterns(
            summary_data,
            requested_start=pattern_start,
            requested_end=pattern_end,
        )
    else:
        result = analyze_device_health(summary_data)

    if args.overwrite_state and not args.state_output:
        print(
            json.dumps(
                {"status": "INVALID_ARGUMENT", "error": "--overwrite-state requires --state-output"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    if args.state_output:
        try:
            _write_state_output(
                result,
                args.state_output,
                args.overwrite_state,
                allow_state_write=True,
            )
        except FileExistsError:
            print(
                json.dumps(
                    {"status": "STATE_OUTPUT_EXISTS", "overwrite_attempted": False},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 3
        except OSError as exc:
            print(
                json.dumps(
                    {"status": "STATE_WRITE_FAILED", "error_type": type(exc).__name__},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
