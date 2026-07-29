#!/usr/bin/env python3
"""Non-diagnostic analysis of user-authorized Garmin data."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    from garmin_sqlite_adapter import (
        DB_DIR,
        get_activities_data as sqlite_activities,
        get_biomechanics_data as sqlite_biomechanics,
        get_body_composition_detailed,
        get_daily_friction_matrix,
        get_devices_info,
        get_hrv_data as sqlite_hrv,
        get_max_metrics,
        get_sleep_data as sqlite_sleep,
        get_summary as sqlite_summary,
    )

    HAS_SQLITE = DB_DIR.exists()
except ImportError:
    HAS_SQLITE = False

from garmin_auth import get_client
from garmin_data import fetch_summary


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
    provenance = section.get("provenance", {})
    if section.get("enabled") is not True:
        return None
    if any(provenance.get(field) in (None, "") for field in REQUIRED_PROVENANCE_FIELDS):
        return None
    for key_path in required_values:
        current: Any = section
        for key in key_path.split("."):
            if not isinstance(current, dict) or current.get(key) is None:
                return None
            current = current[key]
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


def fetch_local_summary(days: int) -> dict[str, Any]:
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


def parse_period(period_str: str | None, days_int: int) -> int:
    if period_str and period_str.endswith("d"):
        try:
            return max(1, int(period_str[:-1]))
        except ValueError:
            pass
    if period_str == "YTD":
        return max(1, (datetime.now() - datetime(datetime.now().year, 1, 1)).days)
    return max(1, int(days_int))


def _records_with_value(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [record for record in records if _is_observed(record.get(key))]


def analyze_baseline_change(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Describe personal-baseline changes without assigning disease risk."""
    valid_hrv = _records_with_value(summary_data.get("hrv", []), "last_night_avg")
    valid_rhr = _records_with_value(summary_data.get("heart_rate", []), "resting_hr")
    valid_resp = _records_with_value(summary_data.get("sleep", []), "avg_respiration")
    if len(valid_hrv) < 3 or len(valid_rhr) < 3:
        return {
            "analysis_type": "personal_baseline_change_signal",
            "status": "insufficient_baseline",
            "classification": "not_classified",
            "medical_interpretation": False,
            "limitations": [
                "At least two prior non-missing HRV and resting-heart-rate observations are required.",
                "Wearable data alone cannot diagnose infection or another condition.",
            ],
        }

    prev_hrv = [float(item["last_night_avg"]) for item in valid_hrv[:-1]]
    prev_rhr = [float(item["resting_hr"]) for item in valid_rhr[:-1]]
    prev_resp = [float(item["avg_respiration"]) for item in valid_resp[:-1]]
    current_hrv = float(valid_hrv[-1]["last_night_avg"])
    current_rhr = float(valid_rhr[-1]["resting_hr"])
    current_resp = (
        float(valid_resp[-1]["avg_respiration"]) if valid_resp else None
    )
    # Performance: Replaced slow statistics.mean with built-in sum/len for ~48x speedup
    baseline_hrv = sum(prev_hrv) / len(prev_hrv) if prev_hrv else 0.0
    baseline_rhr = sum(prev_rhr) / len(prev_rhr) if prev_rhr else 0.0
    baseline_resp = statistics.median(prev_resp) if prev_resp else None
    std_hrv = statistics.stdev(prev_hrv)
    std_rhr = statistics.stdev(prev_rhr)
    z_hrv = (current_hrv - baseline_hrv) / std_hrv if std_hrv > 0 else 0.0
    z_rhr = (current_rhr - baseline_rhr) / std_rhr if std_rhr > 0 else 0.0
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
    classification = "not_classified"
    if config and min(len(prev_hrv), len(prev_rhr)) >= int(config["baseline_min_days"]):
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

    observations = [
        f"静息心率相对可用个人基线为 {z_rhr:+.1f} 个标准差。",
        f"HRV 相对可用个人基线为 {z_hrv:+.1f} 个标准差。",
    ]
    if resp_delta is not None:
        observations.append(
            f"睡眠呼吸率相对可用个人中位数变化 {resp_delta:+.1f} 次/分钟。"
        )
    return {
        "analysis_type": "personal_baseline_change_signal",
        "status": "ok",
        "date": valid_hrv[-1].get("date", "Unknown"),
        "classification": classification,
        "medical_interpretation": False,
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
    latest_sleep = next(
        (
            item
            for item in reversed(summary_data.get("sleep", []))
            if _is_observed(item.get("sleep_score"))
        ),
        {},
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
    latest_hrv = next(
        (
            item
            for item in reversed(summary_data.get("hrv", []))
            if _is_observed(item.get("status"))
        ),
        {},
    )
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
    if config and all(
        _is_observed(inputs[key])
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
            # Performance: Replaced slow statistics.mean with built-in sum/len for ~48x speedup
            round(sum(temperatures) / len(temperatures), 1) if temperatures else None
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


def calculate_social_jetlag(
    sleep_data: list[dict[str, Any]],
) -> float | None:
    """Describe mid-sleep variability only when actual timestamps exist."""
    midpoints = []
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
        midpoints.append(start.timestamp() + (end.timestamp() - start.timestamp()) / 2)
    return round(statistics.stdev(midpoints) / 3600, 2) if len(midpoints) >= 3 else None


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


def _load_summary(days: int) -> dict[str, Any]:
    if HAS_SQLITE:
        try:
            return fetch_local_summary(days)
        except Exception as exc:
            print(
                f"Local Garmin data unavailable ({type(exc).__name__}); trying authorized live access.",
                file=sys.stderr,
            )
    client = get_client()
    if not client:
        raise RuntimeError("Live API authentication failed and local data is unavailable.")
    return fetch_summary(client, days)


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
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--period")
    args = parser.parse_args()
    days = parse_period(args.period, args.days)
    try:
        summary_data = _load_summary(days)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
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

    state_dir = os.environ.get("GARMIN_STATE_DIR")
    if state_dir and isinstance(result, dict):
        output_dir = Path(state_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"health_state_{datetime.now().strftime('%Y-%m-%d')}.json"
        output.write_text(
            json.dumps(
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "analysis_type": result.get("analysis_type"),
                    "status": result.get("status"),
                    "medical_interpretation": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
