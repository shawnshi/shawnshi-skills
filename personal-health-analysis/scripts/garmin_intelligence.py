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
from datetime import date, datetime
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

LocalDataChangedError = LocalDatabaseChangedError

LIVE_ANALYSIS_COMPONENTS = {
    "baseline_change": ("sleep", "hrv", "heart_rate"),
    "readiness": ("sleep", "hrv", "body_battery", "stress"),
    "insight_cn": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "audit": ("sleep", "hrv", "body_battery", "heart_rate", "stress"),
    "env_stress": ("activities",),
}
LIVE_UNSUPPORTED_ANALYSES = frozenset({"long_term_load", "device_audit"})


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
    "readiness_index": "descriptive_experimental_index",
    "training_load_model": "descriptive_experimental_index",
}


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
    if section_name == "readiness_index":
        weights = section.get("weights", {})
        names = ("sleep_score", "body_battery_peak", "stress_recovery")
        return (
            all(_finite_number(weights.get(name)) for name in names)
            and all(0 <= float(weights[name]) <= 1 for name in names)
            and math.isclose(sum(float(weights[name]) for name in names), 1.0, abs_tol=1e-9)
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


def _fetch_local_summary_unverified(days: int) -> dict[str, Any]:
    if not HAS_SQLITE:
        raise DataStaleError("Local Garmin database is unavailable.")
    fetch_days = max(int(days), 1)
    summary_df = sqlite_summary(fetch_days)
    if summary_df.empty:
        raise DataStaleError("Local Garmin database has no data in the requested range.")

    summary_observation_columns = [
        column
        for column in (
            "resting_heart_rate",
            "max_hr",
            "stress_avg",
            "body_battery_highest",
            "body_battery_lowest",
            "body_battery_charged",
            "sweat_loss",
            "rr_waking_avg",
            "steps",
        )
        if column in summary_df.columns
    ]
    if summary_observation_columns:
        observed_summary_rows = summary_df[summary_observation_columns].notna().any(axis=1)
    else:
        observed_summary_rows = pd.Series(False, index=summary_df.index)

    is_stale = True
    if "date" in summary_df.columns and observed_summary_rows.any():
        valid_dates = summary_df.loc[observed_summary_rows, "date"].dropna()
        if not valid_dates.empty:
            try:
                latest = datetime.strptime(str(valid_dates.max())[:10], "%Y-%m-%d")
                is_stale = (datetime.now() - latest).days >= 1
            except ValueError:
                is_stale = True

    sleep_df = sqlite_sleep(fetch_days)
    hrv_df = sqlite_hrv(fetch_days)
    activities_df = sqlite_activities(fetch_days)
    biomechanics_df = sqlite_biomechanics(fetch_days)
    activities = _records_without_missing(activities_df)
    for activity in activities:
        activity["duration"] = parse_time_to_seconds(activity.get("duration"))

    daily_loads: dict[str, float] = {}
    for activity in activities:
        day = activity.get("date")
        load = activity.get("training_load")
        if day and _is_observed(load):
            daily_loads[day] = daily_loads.get(day, 0.0) + float(load)

    load_config = usable_method_config(
        "training_load_model",
        [
            "acute_span_days",
            "chronic_span_days",
            "daily_load_derivation.input_field",
            "daily_load_derivation.scale",
        ],
    )
    pmc = pd.DataFrame()
    if load_config:
        load_window = int(load_config["chronic_span_days"])
        derivation = {
            **load_config["daily_load_derivation"],
            "provenance": load_config["provenance"],
        }
        pmc = calc_pmc_metrics(
            get_daily_friction_matrix(
                max(fetch_days, load_window), derivation_config=derivation
            )
        )
    max_metrics = get_max_metrics()

    hrv_records = _records_without_missing(
        hrv_df.rename(columns={"hrv_avg": "last_night_avg"})
    )
    for entry in hrv_records:
        entry.setdefault("status", None)

    sleep_records = _records_without_missing(sleep_df)
    summary_records = _records_without_missing(summary_df)
    data_gaps = []
    if not observed_summary_rows.any():
        data_gaps.append("No observed daily-summary metrics in the requested range.")
    if not any(
        _is_observed(item.get("sleep_time_seconds")) for item in sleep_records
    ):
        data_gaps.append("No observed sleep duration in the requested range.")
    if not any(_is_observed(item.get("last_night_avg")) for item in hrv_records):
        data_gaps.append("No observed HRV in the requested range.")

    firmware_history = _records_without_missing(get_device_firmware_history())
    return {
        "heart_rate": _records_without_missing(summary_df.rename(
            columns={"resting_heart_rate": "resting_hr"}
        )),
        "stress": _records_without_missing(
            summary_df.rename(columns={"stress_avg": "avg_stress"})
        ),
        "body_battery": _records_without_missing(summary_df.rename(
            columns={
                "body_battery_highest": "highest",
                "body_battery_lowest": "lowest",
                "body_battery_charged": "charged",
            }
        )),
        "sleep": sleep_records,
        "hrv": hrv_records,
        "activities": activities,
        "biomechanics": (
            _records_without_missing(biomechanics_df)
        ),
        "daily_summary": summary_records,
        "training_load_series": [
            {"date": day, "acute_load": value}
            for day, value in sorted(daily_loads.items())
        ],
        "pmc": _records_without_missing(pmc),
        "device_info": _records_without_missing(get_devices_info()),
        "measurement_epoch_evidence": {
            "analysis_algorithm_epoch": BASELINE_ALGORITHM_EPOCH,
            "manufacturer_algorithm_epoch": "not_available_in_local_schema",
            "firmware_epoch_proxy": "serial_number_and_software_version",
            "firmware_history": firmware_history,
        },
        "body_composition_detailed": _records_without_missing(
            get_body_composition_detailed(fetch_days)
        ),
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
    }


def _verified_local_read_window(database_paths=None):
    paths = (
        list(database_paths)
        if database_paths is not None
        else [GARMIN_DB, ACTIVITIES_DB]
    )
    return verified_database_read_window(paths)


def fetch_local_summary(
    days: int, database_paths: list[str | Path] | None = None
) -> dict[str, Any]:
    """Read local data only if all used databases remain byte-for-byte stable."""
    if not HAS_SQLITE:
        raise DataStaleError("Local Garmin database is unavailable.")
    window = _verified_local_read_window(database_paths)
    with window:
        summary = _fetch_local_summary_unverified(days)
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


def _epoch_comparability(
    summary_data: dict[str, Any], observation_dates: list[str]
) -> dict[str, Any]:
    """Conservatively test whether one baseline crosses known firmware epochs."""
    evidence = summary_data.get("measurement_epoch_evidence") or {}
    algorithm_epoch = evidence.get("analysis_algorithm_epoch")
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
    comparable = (
        False
        if cross_epoch
        else True
        if len(observed_epochs) == 1 and not unknown_dates
        else None
    )
    return {
        "comparable": comparable,
        "status": (
            "cross_epoch"
            if cross_epoch
            else "single_known_epoch"
            if comparable is True
            else "epoch_unknown"
        ),
        "observed_epochs": sorted(observed_epochs),
        "analysis_algorithm_epoch": algorithm_epoch,
        "manufacturer_algorithm_epoch": evidence.get(
            "manufacturer_algorithm_epoch", "not_available"
        ),
        "unknown_observation_dates": unknown_dates,
    }


def analyze_baseline_change(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Describe personal-baseline changes without assigning disease risk."""
    def dated_values(records, key):
        values = {}
        for record in records:
            day = record.get("date")
            value = record.get(key)
            if not day or not _is_observed(value):
                continue
            try:
                datetime.strptime(str(day), "%Y-%m-%d")
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                values[str(day)] = numeric
        return values

    hrv_by_date = dated_values(summary_data.get("hrv", []), "last_night_avg")
    rhr_by_date = dated_values(summary_data.get("heart_rate", []), "resting_hr")
    resp_by_date = dated_values(summary_data.get("sleep", []), "avg_respiration")
    paired_dates = sorted(set(hrv_by_date) & set(rhr_by_date))
    current_date = paired_dates[-1] if paired_dates else None
    prior_dates = paired_dates[:-1]
    epoch_comparability = _epoch_comparability(summary_data, paired_dates)
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
            },
            "limitations": [
                f"At least {MIN_PAIRED_BASELINE_DAYS} prior same-date HRV and resting-heart-rate observations are required.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

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
            },
            "observations": [],
            "limitations": [
                "The paired baseline crosses known device or firmware epochs and is not treated as comparable.",
                "Firmware is only a proxy because the manufacturer algorithm epoch is unavailable in the local schema.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

    prev_hrv = [hrv_by_date[day] for day in prior_dates]
    prev_rhr = [rhr_by_date[day] for day in prior_dates]
    prev_resp = [resp_by_date[day] for day in prior_dates if day in resp_by_date]
    current_hrv = hrv_by_date[current_date]
    current_rhr = rhr_by_date[current_date]
    current_resp = resp_by_date.get(current_date)
    baseline_hrv = statistics.mean(prev_hrv)
    baseline_rhr = statistics.mean(prev_rhr)
    baseline_resp = statistics.median(prev_resp) if prev_resp else None
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
    """Score only when explicit, traceable experimental weights are enabled."""
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
    config = usable_method_config(
        "readiness_index",
        [
            "weights.sleep_score",
            "weights.body_battery_peak",
            "weights.stress_recovery",
        ],
    )
    score = None
    if config and observation_date and all(
        _is_observed(inputs[key])
        for key in ("sleep_score", "body_battery_peak", "garmin_stress")
    ) and all(
        0 <= float(inputs[key]) <= 100
        for key in ("sleep_score", "body_battery_peak", "garmin_stress")
    ):
        weights = {key: float(value) for key, value in config["weights"].items()}
        total_weight = sum(weights.values())
        if total_weight > 0:
            stress_recovery = max(0.0, 100.0 - float(inputs["garmin_stress"]))
            score = round(
                (
                    float(inputs["sleep_score"]) * weights["sleep_score"]
                    + float(inputs["body_battery_peak"]) * weights["body_battery_peak"]
                    + stress_recovery * weights["stress_recovery"]
                )
                / total_weight,
                1,
            )
    return {
        "analysis_type": "executive_readiness",
        "status": "experimental_score" if score is not None else "not_scored",
        "score": score,
        "date": observation_date,
        "alignment_status": "same_date" if observation_date else "not_aligned",
        "physical_score": None,
        "cognitive_score": None,
        "inputs": inputs,
        "configuration_status": (
            "enabled_and_traceable" if config else "not_enabled_or_incomplete"
        ),
        "recommendation": (
            "该指数只作描述，不能用于判断认知能力、职业表现、训练资格或医疗状态。"
            if score is not None
            else "配置未启用或不可追踪；仅展示原始指标，不生成准备度分数。"
        ),
    }


def perform_bio_metric_audit(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Build a descriptive audit without clinical or behavioral directives."""
    valid_rhrs = [
        float(item["resting_hr"])
        for item in summary_data.get("heart_rate", [])
        if _is_observed(item.get("resting_hr"))
    ]
    latest_rhr = valid_rhrs[-1] if valid_rhrs else None
    baseline_rhr = statistics.median(valid_rhrs[:-1]) if len(valid_rhrs) > 1 else None
    latest_hrv = next(
        (
            item.get("last_night_avg")
            for item in reversed(summary_data.get("hrv", []))
            if _is_observed(item.get("last_night_avg"))
        ),
        None,
    )
    hrv_status = next(
        (
            item.get("status")
            for item in reversed(summary_data.get("hrv", []))
            if _is_observed(item.get("status"))
        ),
        None,
    )
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
    return {
        "analysis_type": "bio_metric_audit",
        "system_status": {
            "rhr": {
                "current": latest_rhr,
                "baseline": (
                    round(baseline_rhr, 1) if baseline_rhr is not None else None
                ),
                "delta": (
                    round(latest_rhr - baseline_rhr, 1)
                    if latest_rhr is not None and baseline_rhr is not None
                    else None
                ),
                "status": "descriptive_only" if latest_rhr is not None else "no_data",
            },
            "hrv": {"value": latest_hrv, "status": hrv_status},
            "vo2_max": summary_data.get("training_status", {}).get("vo2_max"),
            "fitness_age": summary_data.get("max_metrics", {}).get("fitness_age"),
            "bmi": summary_data.get("body_composition", {}).get("bmi"),
            "is_stale": summary_data.get("is_stale"),
        },
        "recovery_loop": {
            "sleep_architecture": {
                "deep_pct": round(deep_pct, 1) if deep_pct is not None else None,
                "rem_pct": round(rem_pct, 1) if rem_pct is not None else None,
                "restlessness": latest_sleep.get("restless_periods"),
                "sleep_debt_h": None,
                "interpretation": "consumer_device_estimate",
            },
            "body_battery": {
                "charged": latest_bb.get("charged"),
                "peak": latest_bb.get("highest"),
                "lowest": latest_bb.get("lowest"),
                "interpretation": "garmin_proprietary_metric",
            },
        },
        "load_friction": {
            "stress_score": latest_stress.get("avg_stress"),
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
                "设备数据不生成训练、补剂、日程或决策命令。可结合主观感受、症状、"
                "个人计划和专业意见决定是否调整活动。"
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
    lines = [
        f"【数据范围】{period}；{stale_note}",
        "【可观察指标】"
        f"静息心率 {audit['system_status']['rhr']['current']}；"
        f"HRV {audit['system_status']['hrv']['value']}；"
        f"Body Battery 峰值 {audit['recovery_loop']['body_battery']['peak']}；"
        f"Garmin 压力 {audit['load_friction']['stress_score']}。",
        "【睡眠描述】"
        f"睡眠时长标准差 {variability if variability is not None else '数据不足'} 小时"
        f"（{variability_status}）。睡眠阶段为消费级设备估计，不作诊断。",
        "【方法边界】"
        + readiness["recommendation"]
        + " 不从这些指标推断感染、炎症、免疫状态、认知能力或职业表现。",
        "【可选考虑】若主观感觉恢复不足，可自行考虑降低活动强度或安排休息；"
        "若变化持续、伴随明显症状或影响生活，建议携带原始数据咨询合格医疗人员。",
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
        return fetch_local_summary(days)
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
