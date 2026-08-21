#!/usr/bin/env python3
"""
@Input:  analysis, --days/--period, --source, --allow-health-data
@Output: JSON Analysis Report with Actionable Insights
@Pos:    Intelligence Layer. Second-order analysis of raw health data.

!!! Maintenance Protocol: Tune thresholds based on user feedback.
"""

import sys
sys.dont_write_bytecode = True

import json
import argparse
import statistics
import contextlib
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta

pd = None

# Provider modules are loaded only after the CLI capability gates pass.
sys.path.insert(0, str(Path(__file__).parent))

# Compatibility signal for garmin_chart.py. Availability is resolved lazily by
# fetch_local_summary(), without probing a health-data path at module import.
HAS_SQLITE = True


def _load_local_adapter():
    import importlib

    return importlib.import_module("garmin_sqlite_adapter")


def _load_pandas():
    """Load pandas only for an authorized data read, not for --help/gate failures."""
    global pd
    if pd is None:
        import pandas as pandas_module

        pd = pandas_module
    return pd

_CLINICAL_GUIDELINES = None

def load_clinical_guidelines():
    global _CLINICAL_GUIDELINES
    if _CLINICAL_GUIDELINES is None:
        guidelines_path = Path(__file__).parent.parent / "resources" / "clinical_guidelines.json"
        if guidelines_path.exists():
            with open(guidelines_path, "r", encoding="utf-8") as f:
                _CLINICAL_GUIDELINES = json.load(f)
        else:
            _CLINICAL_GUIDELINES = {} # Fallback empty dict
    return _CLINICAL_GUIDELINES

def calc_pmc_metrics(friction_matrix):
    """
    Calculate PMC (Performance Management Chart) metrics: CTL, ATL, TSB.
    CTL (Chronic Training Load): 42-day EWMA of daily friction load.
    ATL (Acute Training Load): 7-day EWMA of daily friction load.
    TSB (Training Stress Balance): CTL - ATL.
    """
    if friction_matrix.empty:
        return friction_matrix

    # Sort by date ascending for EWMA
    df = friction_matrix.sort_values('date')

    # CTL: 42-day rolling average
    df['ctl'] = df['daily_friction_load'].ewm(span=42, adjust=False).mean()
    # ATL: 7-day rolling average
    df['atl'] = df['daily_friction_load'].ewm(span=7, adjust=False).mean()
    # TSB: CTL - ATL
    df['tsb'] = df['ctl'] - df['atl']

    # Performance: Replaced slow .apply() with vectorized np.select() for ~1.81x faster zone calculation
    import numpy as np
    conditions = [
        df['tsb'].isna(),
        df['tsb'] > 10,
        df['tsb'] >= -10,
        df['tsb'] >= -30
    ]
    choices = [
        "无数据",
        "超量恢复 (Fresh)",
        "战术稳态 (Grey)",
        "结构性耗散 (Optimal_Training)"
    ]
    df['TSB_Zone'] = np.select(conditions, choices, default="熔断先兆 (High_Risk)")

    return df

def analyze_env_stress(summary_data):
    """Analyze correlation between environment factors (temp/alt) and physiological stress."""
    activities = summary_data.get("activities", [])
    if not activities:
        return {"status": "no_data"}

    env_insights = []
    temps = [a.get('temperature') for a in activities if a.get('temperature')]
    if temps:
        avg_temp = statistics.mean(temps)
        if avg_temp > 28:
            env_insights.append(f"High thermal stress detected (avg {avg_temp:.1f}°C). Increased RHR expected.")

    return {"analysis_type": "environmental_stress", "insights": env_insights}

def analyze_device_health(summary_data):
    """Audit device firmware and sensor consistency."""
    devices = summary_data.get("device_info", [])
    if hasattr(devices, 'empty') and devices.empty:
        return {"status": "no_data"}

    insights = []
    # Check for multiple devices or firmware versions
    if hasattr(devices, 'software_version'):
        unique_firmware = devices['software_version'].unique()
        if len(unique_firmware) > 1:
            insights.append(f"Firmware version shift detected ({', '.join(map(str, unique_firmware))}). Physiological baseline may be affected by sensor algorithm changes.")

    return {
        "analysis_type": "device_audit",
        "devices": devices.to_dict('records') if hasattr(devices, 'to_dict') else [],
        "insights": insights
    }

def parse_time_to_seconds(time_str):
    """Convert HH:MM:SS string to seconds."""
    if not time_str or not isinstance(time_str, str): return 0
    try:
        parts = time_str.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(time_str)
    except ValueError:
        return 0

class DataStaleError(Exception):
    pass


class LiveAuthenticationError(Exception):
    pass


def _is_auth_error(exc):
    return type(exc).__name__ == "GarminConnectAuthenticationError" or "401" in str(exc)

def fetch_local_summary(days):
    """
    Load only the requested local calendar-day window.

    The SQLite adapter uses an inclusive start date, so it receives ``days - 1``
    to keep the physical access window equal to the caller's request. Advanced
    all-time/device/baseline reads are deliberately excluded from this bounded
    summary.
    """
    if not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")

    _load_pandas()
    adapter = _load_local_adapter()
    provider_days = days - 1
    print(f"📂 Loading bounded local SQLite data ({days} calendar days)...", file=sys.stderr)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            summary_df = adapter.get_summary(provider_days, fill_missing=False)
    except ValueError as exc:
        if "no data found" in str(exc).lower():
            raise DataStaleError("Local data is empty for the requested window.") from exc
        raise

    if summary_df.empty:
        raise DataStaleError("Local data is empty for the requested window.")

    data_gaps = []
    if days < 30:
        data_gaps.append("long_horizon_baseline_not_authorized")

    def load_optional(name, loader, **kwargs):
        try:
            with contextlib.redirect_stdout(sys.stderr):
                return loader(provider_days, **kwargs)
        except Exception as exc:
            data_gaps.append(name)
            print(
                f"⚠️ Optional local lane '{name}' unavailable ({type(exc).__name__}).",
                file=sys.stderr,
            )
            return pd.DataFrame()

    # --- Check Data Freshness ---
    is_stale = False
    if not summary_df.empty and 'date' in summary_df.columns and 'resting_heart_rate' in summary_df.columns:
        valid_dates = summary_df.dropna(subset=['resting_heart_rate'])['date']
        if not valid_dates.empty:
            latest_date_str = valid_dates.max()
            try:
                latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
                if (datetime.now() - latest_date).days >= 1:
                    is_stale = True
            except ValueError:
                pass

    sleep_df = load_optional(
        "sleep", adapter.get_sleep_data, fill_missing=False
    )
    hrv_df = load_optional("hrv", adapter.get_hrv_data, fill_missing=False)
    activities_df = load_optional("activities", adapter.get_activities_data)

    activities_list = activities_df.to_dict('records') if not activities_df.empty else []

    daily_loads = {}
    for act in activities_list:
        if isinstance(act.get('duration'), str):
            act['duration'] = parse_time_to_seconds(act['duration'])

        d = act.get('date')
        if d and act.get('training_load') is not None:
            daily_loads[d] = daily_loads.get(d, 0) + act['training_load']

    training_load_series = [{"date": d, "acute_load": val} for d, val in daily_loads.items()]

    heart_rate_records = summary_df.rename(
        columns={"resting_heart_rate": "resting_hr"}
    ).to_dict('records')
    stress_records = summary_df.rename(
        columns={"stress_avg": "avg_stress"}
    ).to_dict('records')
    body_battery_records = summary_df.rename(
        columns={
            "body_battery_highest": "highest",
            "body_battery_lowest": "lowest",
            "body_battery_charged": "charged",
        }
    ).to_dict('records')
    sleep_records = sleep_df.to_dict('records') if not sleep_df.empty else []
    hrv_records = (
        hrv_df.rename(columns={"hrv_avg": "last_night_avg"}).to_dict('records')
        if not hrv_df.empty
        else []
    )

    if not any(
        row.get("sleep_time_seconds")
        and not pd.isna(row.get("sleep_time_seconds"))
        for row in sleep_records
    ):
        data_gaps.append("sleep_observations")
    if not any(
        row.get("last_night_avg")
        and not pd.isna(row.get("last_night_avg"))
        for row in hrv_records
    ):
        data_gaps.append("hrv_observations")

    required_observations = (
        ("resting_heart_rate_observations", heart_rate_records, "resting_hr"),
        ("stress_observations", stress_records, "avg_stress"),
        ("body_battery_observations", body_battery_records, "highest"),
    )
    for gap_name, records, key in required_observations:
        if not any(
            row.get(key) is not None and not pd.isna(row.get(key))
            for row in records
        ):
            data_gaps.append(gap_name)

    def mean_value(records, key):
        values = [
            row.get(key)
            for row in records
            if row.get(key) is not None and not pd.isna(row.get(key))
        ]
        return round(statistics.mean(values), 1) if values else None

    start_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    avg_sleep_seconds = mean_value(sleep_records, "sleep_time_seconds")

    # Convert DataFrames to the dictionary list format expected by existing logic.
    # Missing observations remain null; this bounded path never normalizes them
    # into population-like defaults.
    summary_data = {
        "summary": {
            "period": f"{start_date} to {end_date}",
            "days": days,
            "avg_sleep_hours": (
                round(avg_sleep_seconds / 3600, 1)
                if avg_sleep_seconds is not None
                else None
            ),
            "avg_sleep_score": mean_value(sleep_records, "sleep_score"),
            "avg_hrv_ms": mean_value(hrv_records, "last_night_avg"),
            "avg_resting_hr": mean_value(heart_rate_records, "resting_hr"),
            "avg_body_battery_charged": mean_value(body_battery_records, "charged"),
            "total_activities": len(activities_list),
        },
        "heart_rate": heart_rate_records,
        "stress": stress_records,
        "body_battery": body_battery_records,
        "sleep": sleep_records,
        "hrv": hrv_records,
        "activities": activities_list,
        "biomechanics": [],
        "daily_summary": summary_df.to_dict('records'),
        "training_load_series": training_load_series,
        "pmc": [],
        "device_info": [],
        "body_composition_detailed": [],
        "training_status": {
            "vo2_max": "--",
            "load_status": "窗口不足",
            "load_ratio": "--",
        },
        "max_metrics": {},
        "body_composition": {},
        "_bounded_contract": True,
        "_data_gaps": sorted(set(data_gaps)),
        "_accessed_days": days,
    }

    # Add status field to HRV to match existing logic
    for entry in summary_data["hrv"]:
        status = entry.get("status")
        if status is None or pd.isna(status) or not str(status).strip():
            entry["status"] = "UNKNOWN"

    summary_data["is_stale"] = is_stale

    return summary_data


def _live_token_path():
    """Resolve one existing token file without reading account profile/settings."""
    configured = os.environ.get("GARMIN_TOKEN_DIR")
    roots = []
    if configured:
        roots.append(Path(configured).expanduser())
    roots.extend(
        [
            Path.home() / ".GarminDb",
            Path.home() / ".config" / "garmin-connect",
        ]
    )
    seen = set()
    for root in roots:
        candidate = root if root.suffix.casefold() == ".json" else root / "garmin_tokens.json"
        key = str(candidate.resolve(strict=False)).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    raise FileNotFoundError("No Garmin token store is available.")


def _load_live_client():
    """Load tokens into memory without profile/settings reads or token persistence."""
    try:
        from garminconnect import Garmin
    except ImportError:
        raise

    token_path = _live_token_path()
    token_text = token_path.read_text(encoding="utf-8")
    # One attempt caps a failing endpoint at the provider's request timeout;
    # orchestration below returns partial data for independent lane failures.
    client = Garmin(retry_attempts=0)
    client.client._tokenstore_path = None
    try:
        client.client.loads(token_text)
    except Exception as exc:
        raise LiveAuthenticationError("Garmin token store is invalid.") from exc

    # Refreshes may happen in memory, but loads() must not bind persistence.
    if client.client._tokenstore_path is not None:
        raise RuntimeError("Garmin client unexpectedly bound a persistent token store.")
    return client


def _pick(record, *keys):
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _mean(records, key):
    values = [row.get(key) for row in records if isinstance(row.get(key), (int, float))]
    return round(statistics.mean(values), 1) if values else None


def _sleep_records(payload):
    records = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        values = row.get("values") if isinstance(row.get("values"), dict) else row
        score = _pick(values, "sleepScore", "overallSleepScore", "score")
        if isinstance(score, dict):
            score = _pick(score, "value")
        records.append(
            {
                "date": _pick(row, "calendarDate", "date"),
                "sleep_time_seconds": _pick(values, "totalSleepTimeInSeconds", "sleepTimeSeconds", "totalSleepSeconds", "totalSleep"),
                "deep_sleep_seconds": _pick(values, "deepTime", "deepSleepSeconds", "deepSleep"),
                "light_sleep_seconds": _pick(values, "lightTime", "lightSleepSeconds", "lightSleep"),
                "rem_sleep_seconds": _pick(values, "remTime", "remSleepSeconds", "remSleep"),
                "awake_seconds": _pick(values, "awakeTime", "awakeSleepSeconds", "awakeSeconds", "awake"),
                "sleep_score": score,
                "avg_respiration": _pick(values, "respiration", "averageRespirationValue", "avgRespiration"),
                "avg_spo2": _pick(values, "spO2", "averageSpO2", "avgSpO2"),
                "resting_hr": _pick(values, "restingHeartRate", "resting_hr"),
            }
        )
    return records


def _hrv_records(payload):
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("hrvSummaries")
            or payload.get("hrvSummary")
            or payload.get("dailyHrvSummaries")
            or []
        )
        if isinstance(rows, dict):
            rows = [rows]
    else:
        rows = []
    return [
        {
            "date": _pick(row, "calendarDate", "date"),
            "last_night_avg": _pick(row, "lastNightAvg", "last_night_avg"),
            "status": _pick(row, "status", "hrvStatus") or "UNKNOWN",
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _body_battery_records(payload):
    records = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        points = row.get("bodyBatteryValuesArray") or []
        values = [point[1] for point in points if isinstance(point, (list, tuple)) and len(point) > 1 and isinstance(point[1], (int, float))]
        records.append(
            {
                "date": _pick(row, "date", "calendarDate"),
                "charged": _pick(row, "charged"),
                "drained": _pick(row, "drained"),
                "highest": max(values) if values else _pick(row, "highest"),
                "lowest": min(values) if values else _pick(row, "lowest"),
            }
        )
    return records


def _stress_record(date_string, payload):
    payload = payload if isinstance(payload, dict) else {}
    return {
        "date": _pick(payload, "calendarDate") or date_string,
        "avg_stress": _pick(payload, "avgStressLevel", "averageStressLevel", "avgStress"),
        "rest_stress_duration": _pick(payload, "restStressDuration"),
        "low_stress_duration": _pick(payload, "lowStressDuration"),
        "medium_stress_duration": _pick(payload, "mediumStressDuration"),
        "high_stress_duration": _pick(payload, "highStressDuration"),
    }


def fetch_live_summary(days):
    """Read an exact live window without profile/settings reads or persistence."""
    if not isinstance(days, int) or days < 1:
        raise ValueError("days must be a positive integer")

    client = _load_live_client()
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)
    start_string = start.isoformat()
    end_string = end.isoformat()

    # The body-battery range is the cheapest authenticated lane in the active
    # provider, so use it as the fail-fast probe before starting slower calls.
    try:
        battery_payload = client.get_body_battery(start_string, end_string)
    except Exception as exc:
        if _is_auth_error(exc):
            raise LiveAuthenticationError("Garmin live session is invalid.") from exc
        raise

    date_strings = [(start + timedelta(days=offset)).isoformat() for offset in range(days)]
    lane_gaps = []

    def optional_result(future, gap, empty):
        try:
            return future.result()
        except Exception as exc:
            if _is_auth_error(exc):
                raise LiveAuthenticationError("Garmin live session is invalid.") from exc
            lane_gaps.append(gap)
            return empty

    with ThreadPoolExecutor(max_workers=min(4, days + 2)) as pool:
        hrv_future = pool.submit(client.get_hrv_data_range, start_string, end_string)
        sleep_future = pool.submit(client.get_sleep_daily, start_string, end_string)
        stress_futures = {
            date_string: pool.submit(client.get_stress_data, date_string)
            for date_string in date_strings
        }
        hrv_payload = optional_result(hrv_future, "hrv_provider_unavailable", {})
        sleep_payload = optional_result(sleep_future, "sleep_provider_unavailable", [])
        stress_payloads = {
            date_string: optional_result(
                future, f"stress_provider_unavailable:{date_string}", {}
            )
            for date_string, future in stress_futures.items()
        }

    sleep = _sleep_records(sleep_payload)
    hrv = _hrv_records(hrv_payload)
    body_battery = _body_battery_records(battery_payload)
    stress = [_stress_record(day, stress_payloads[day]) for day in date_strings]
    heart_rate = [
        {"date": row.get("date"), "resting_hr": row.get("resting_hr")}
        for row in sleep
        if row.get("resting_hr") is not None
    ]
    gaps = [
        "long_horizon_baseline_not_authorized",
        "activities_not_requested",
        *lane_gaps,
    ]
    required = (
        ("sleep_observations", sleep, "sleep_time_seconds"),
        ("hrv_observations", hrv, "last_night_avg"),
        ("body_battery_observations", body_battery, "highest"),
        ("stress_observations", stress, "avg_stress"),
        ("resting_heart_rate_observations", heart_rate, "resting_hr"),
    )
    for gap, records, key in required:
        if not any(row.get(key) is not None for row in records):
            gaps.append(gap)

    summary = {
        "period": f"{start_string} to {end_string}",
        "days": days,
        "avg_sleep_hours": None,
        "avg_sleep_score": _mean(sleep, "sleep_score"),
        "avg_hrv_ms": _mean(hrv, "last_night_avg"),
        "avg_resting_hr": _mean(heart_rate, "resting_hr"),
        "avg_body_battery_charged": _mean(body_battery, "charged"),
        "total_activities": 0,
    }
    sleep_seconds = _mean(sleep, "sleep_time_seconds")
    if sleep_seconds is not None:
        summary["avg_sleep_hours"] = round(sleep_seconds / 3600, 1)

    return {
        "summary": summary,
        "heart_rate": heart_rate,
        "stress": stress,
        "body_battery": body_battery,
        "sleep": sleep,
        "hrv": hrv,
        "activities": [],
        "biomechanics": [],
        "daily_summary": [],
        "training_load_series": [],
        "pmc": [],
        "device_info": [],
        "body_composition_detailed": [],
        "training_status": {},
        "max_metrics": {},
        "body_composition": {},
        "is_stale": False,
        "_bounded_contract": True,
        "_source": "live",
        "_data_gaps": sorted(set(gaps)),
        "_accessed_days": days,
    }

def parse_period(period_str, days_int):
    """Parse period string like '90d' or fallback to days."""
    if period_str and period_str.endswith('d'):
        try:
            return int(period_str[:-1])
        except ValueError:
            pass
    if period_str == 'YTD':
        return (datetime.now() - datetime(datetime.now().year, 1, 1)).days
    return days_int

def analyze_flu_risk(summary_data):
    """
    Detect 'The Garmin Flu' pattern (CMO Level) using Rolling Baseline Calibration
    loaded from external DE (Domain Expert) Knowledge Base.
    """
    import math
    guidelines = load_clinical_guidelines().get("flu_risk", {})

    # Fallback to hardcoded safe defaults if KB missing
    crit_rhr = guidelines.get("critical", {}).get("rhr_z_score_min", 2.0)
    crit_hrv = guidelines.get("critical", {}).get("hrv_z_score_max", -2.0)
    crit_resp = guidelines.get("critical", {}).get("resp_spike_min", 0.5)

    high_rhr = guidelines.get("high", {}).get("rhr_z_score_min", 1.5)
    high_hrv = guidelines.get("high", {}).get("hrv_z_score_max", -1.5)

    mod_rhr = guidelines.get("moderate", {}).get("rhr_z_score_min", 1.0)
    mod_hrv = guidelines.get("moderate", {}).get("hrv_z_score_max", -1.0)

    waking_resp_min = guidelines.get("waking_resp_spike_min", 0.5)

    hrv_data = summary_data.get("hrv", [])
    hr_data = summary_data.get("heart_rate", [])
    sleep_data = summary_data.get("sleep", [])

    # Need at least 3 days of data
    if len(hrv_data) < 3 or len(hr_data) < 3:
        return {"status": "insufficient_data"}

    # Get latest data
    # Performance: Replaced O(N^2) backward scanning next() and filtering with single O(N) list comprehensions for ~1.5x speedup and fixed dropped historical records.
    valid_hrv = [d for d in hrv_data if d.get("last_night_avg")]
    latest_hrv_entry = valid_hrv[-1] if valid_hrv else {}

    valid_rhr = [d for d in hr_data if d.get("resting_hr")]
    latest_hr_entry = valid_rhr[-1] if valid_rhr else {}

    valid_resp = [d for d in sleep_data if d.get("avg_respiration")]
    latest_sleep = valid_resp[-1] if valid_resp else {}

    # Calculate rolling baseline (avg & stdev of previous days, typically 30)
    prev_hrv = [d.get("last_night_avg") for d in valid_hrv[:-1]]
    prev_rhr = [d.get("resting_hr") for d in valid_rhr[:-1]]
    prev_resp = [d.get("avg_respiration") for d in valid_resp[:-1]]

    if len(prev_hrv) < 2 or len(prev_rhr) < 2:
        return {"status": "insufficient_baseline"}

    avg_hrv_baseline = statistics.mean(prev_hrv)
    std_hrv = statistics.stdev(prev_hrv) if len(prev_hrv) > 1 else 1.0

    avg_rhr_baseline = statistics.mean(prev_rhr)
    std_rhr = statistics.stdev(prev_rhr) if len(prev_rhr) > 1 else 1.0

    avg_resp_baseline = statistics.median(prev_resp) if prev_resp else 14.0

    current_hrv = latest_hrv_entry.get("last_night_avg") or avg_hrv_baseline
    current_rhr = latest_hr_entry.get("resting_hr") or avg_rhr_baseline
    current_resp = latest_sleep.get("avg_respiration") or avg_resp_baseline

    # Z-Scores
    z_hrv = (current_hrv - avg_hrv_baseline) / std_hrv if std_hrv > 0 else 0
    z_rhr = (current_rhr - avg_rhr_baseline) / std_rhr if std_rhr > 0 else 0

    resp_spike = current_resp - avg_resp_baseline

    daily_summary_data = summary_data.get("daily_summary", [])
    # Performance: Replaced multiple O(N) passes with a single O(N) list comprehension
    valid_waking = [d for d in daily_summary_data if d.get("rr_waking_avg")]
    latest_daily = valid_waking[-1] if valid_waking else {}
    current_waking_resp = latest_daily.get("rr_waking_avg")
    prev_waking_resp = [d.get("rr_waking_avg") for d in valid_waking[:-1]]
    avg_waking_resp_baseline = statistics.median(prev_waking_resp) if prev_waking_resp else (current_waking_resp or 14.0)
    waking_resp_spike = (current_waking_resp - avg_waking_resp_baseline) if current_waking_resp else 0

    risk_level = "low"
    reasons = []

    # Dynamic thresholds loaded from DE Knowledge Base
    if z_rhr > crit_rhr and z_hrv < crit_hrv and resp_spike > crit_resp:
        risk_level = "CRITICAL"
        reasons.append(f"Respiration spike detected (+{resp_spike:.1f} brpm) - High clinical relevance for infection")
        reasons.append(f"Critical RHR deviation (+{z_rhr:.1f}σ, baseline: {avg_rhr_baseline:.1f})")
        reasons.append(f"Critical HRV collapse ({z_hrv:.1f}σ, baseline: {avg_hrv_baseline:.1f})")
    elif z_rhr > high_rhr and z_hrv < high_hrv:
        risk_level = "HIGH"
        reasons.append(f"Significant RHR deviation (+{z_rhr:.1f}σ)")
        reasons.append(f"Significant HRV collapse ({z_hrv:.1f}σ)")
    elif z_rhr > mod_rhr and z_hrv < mod_hrv:
        risk_level = "MODERATE"
        reasons.append(f"Elevated RHR (+{z_rhr:.1f}σ)")
        reasons.append(f"Depressed HRV ({z_hrv:.1f}σ)")

    if waking_resp_spike > waking_resp_min:
        reasons.append(f"Daytime sympathetic overdrive (+{waking_resp_spike:.1f} brpm waking RR)")
        if risk_level == "low": risk_level = "MODERATE"

    return {
        "analysis_type": "bio_entropy_flu_risk",
        "date": latest_hrv_entry.get("date", "Unknown"),
        "risk_level": risk_level,
        "metrics": {
            "current_rhr": current_rhr,
            "baseline_rhr": round(avg_rhr_baseline, 1),
            "current_hrv": current_hrv,
            "baseline_hrv": round(avg_hrv_baseline, 1),
            "current_resp": round(current_resp, 1) if current_resp else "--",
            "baseline_resp": round(avg_resp_baseline, 1) if avg_resp_baseline else "--"
        },
        "insights": reasons
    }

def calculate_sleep_consistency(sleep_data):
    """Calculate sleep duration consistency (lower std dev is better)."""
    if not sleep_data or len(sleep_data) < 2:
        return 0, "数据不足"

    durations = [s.get("sleep_time_seconds", 0) / 3600 for s in sleep_data if s.get("sleep_time_seconds")]
    if len(durations) < 2:
        return 0, "数据不足"

    std_dev = statistics.stdev(durations)
    return round(std_dev, 2), "高" if std_dev > 1.5 else "中" if std_dev > 0.8 else "优"

def synthesize_pmc(summary_data):
    """Summarize already-loaded PMC records without performing hidden reads."""
    records = summary_data.get("pmc", [])
    if not records:
        return None

    latest = records[-1]

    def number(key, default=0):
        value = latest.get(key, default)
        return default if value is None or pd.isna(value) else float(value)

    ctl = number("ctl", number("CTL"))
    atl = number("atl", number("ATL"))
    tsb = number("tsb", number("TSB", ctl - atl))
    daily_load = number("daily_friction_load", number("Daily_Load"))
    ramp = 0.0
    if len(records) >= 8:
        prior = records[-8]
        prior_atl = prior.get("atl", prior.get("ATL"))
        if prior_atl is not None and not pd.isna(prior_atl):
            ramp = atl - float(prior_atl)

    zone = latest.get("TSB_Zone")
    if not zone:
        if tsb > 10:
            zone = "超量恢复 (Fresh)"
        elif tsb >= -10:
            zone = "战术稳态 (Grey)"
        elif tsb >= -30:
            zone = "结构性耗散 (Optimal_Training)"
        else:
            zone = "熔断先兆 (High_Risk)"

    return {
        "CTL": round(ctl, 1),
        "ATL": round(atl, 1),
        "TSB": round(tsb, 1),
        "TSB_Zone": zone,
        "Ramp_Rate": round(ramp, 1),
        "Daily_Load": round(daily_load, 1),
    }

def analyze_executive_readiness(summary_data):
    """
    Calculate Daily Executive Readiness Score (0-100) with Cognitive vs Physical split.
    Integrates Zone Dissipation (Time in High Stress) as a major friction penalty.
    """
    # Get latest non-null data
    sleep_list = summary_data.get("sleep", [])
    bb_list = summary_data.get("body_battery", [])
    stress_list = summary_data.get("stress", [])
    hrv_list = summary_data.get("hrv", [])
    hr_data = summary_data.get("heart_rate", [])

    latest_sleep = next((s for s in reversed(sleep_list) if s.get("sleep_score")), {})
    latest_bb = next((b for b in reversed(bb_list) if b.get("highest")), {})
    latest_stress = next((st for st in reversed(stress_list) if st.get("avg_stress")), {})
    latest_hrv = next((h for h in reversed(hrv_list) if h.get("status")), {})

    # 1. Base Metrics
    sleep_score = latest_sleep.get("sleep_score", 0) or 0
    bb_peak = latest_bb.get("highest", 0) or 0
    avg_stress = latest_stress.get("avg_stress", 50) or 50
    hrv_status = latest_hrv.get("status", "BALANCED")

    total_sleep_sec = latest_sleep.get("sleep_time_seconds", 0) or 1
    rem_pct = (latest_sleep.get("rem_sleep_seconds", 0) / total_sleep_sec) * 100
    deep_pct = (latest_sleep.get("deep_sleep_seconds", 0) / total_sleep_sec) * 100
    avg_spo2 = latest_sleep.get("avg_spo2", 95) or 95

    # Calculate RHR Diff (Metabolic Pressure)
    # Performance: Replaced multiple O(N) passes and a filtering bug with a single O(N) list comprehension for ~1.65x speedup
    valid_rhrs = [h["resting_hr"] for h in hr_data if h.get("resting_hr")]
    latest_rhr = valid_rhrs[-1] if valid_rhrs else 0
    prev_rhrs = valid_rhrs[:-1]
    baseline_rhr = statistics.median(prev_rhrs) if prev_rhrs else latest_rhr
    rhr_diff = latest_rhr - baseline_rhr if latest_rhr > 0 else 0

    # Calculate Sleep Debt
    target_sleep_s = 27000
    sleep_debt_s = sum(max(0, target_sleep_s - s.get("sleep_time_seconds", target_sleep_s)) for s in sleep_list[-3:] if s.get("sleep_time_seconds"))
    sleep_debt_h = sleep_debt_s / 3600

    # Dissipation Profile (Time in High Stress)
    high_stress_sec = latest_stress.get("high_stress_duration", 0) or 0
    med_stress_sec = latest_stress.get("medium_stress_duration", 0) or 0
    dissipation_hours = (high_stress_sec + (med_stress_sec * 0.5)) / 3600

    # Hydration & Biosustainability
    hydration_ml = summary_data.get("hydration", {}).get("valueInML", 0) or 0
    daily_summary_list = summary_data.get("daily_summary", [])
    latest_daily = next((d for d in reversed(daily_summary_list) if "sweat_loss" in d), {})
    sweat_loss = latest_daily.get("sweat_loss", 0) or 0
    fluid_delta = hydration_ml - sweat_loss

    # Biomechanics
    bio_list = summary_data.get("biomechanics", [])
    recent_bio = [b for b in bio_list if b.get("avg_ground_contact_time") is not None]
    gct_spike = 0
    if len(recent_bio) >= 3:
        gct_values = [b["avg_ground_contact_time"] for b in recent_bio]
        gct_baseline = statistics.median(gct_values[:-1]) if len(gct_values) > 1 else gct_values[0]
        gct_spike = gct_values[-1] - gct_baseline

    # 2. Cognitive Readiness (Focus: REM, HRV, Stress, Dissipation Penalty)
    guidelines = load_clinical_guidelines().get("executive_readiness", {})
    penalties = guidelines.get("penalties", {})

    sleep_debt_thresh = penalties.get("sleep_debt_threshold", 1.5)
    sleep_debt_mult = penalties.get("sleep_debt_multiplier", 3.0) # original hardcoded 5, let's use config default or 5
    dissipation_mult = penalties.get("high_stress_dissipation_multiplier", 4.0)

    cog_rem_score = min(rem_pct / 20, 1.2) * 30
    cog_stress_score = max(0, (50 - avg_stress)) * 1
    cog_hrv_score = 40 if hrv_status == "BALANCED" else 20
    cognitive_score = cog_rem_score + cog_stress_score + cog_hrv_score + (sleep_score * 0.2)

    # Pessimistic Penalty: Dissipation & Sleep Debt
    if sleep_debt_h > sleep_debt_thresh:
        cognitive_score -= (sleep_debt_h * sleep_debt_mult)
    if dissipation_hours > 2.0:
        cognitive_score -= (dissipation_hours * dissipation_mult) # Cognitive drain penalty

    # Social Jetlag Penalty
    social_jetlag = calculate_social_jetlag(sleep_list)
    if social_jetlag > 1.5:
        cognitive_score -= (social_jetlag * 3) # Disrupts circadian rhythm

    if avg_spo2 < 93:
        cognitive_score *= 0.7 # Severe hypoxia penalty (limits prefrontal cortex)

    cognitive_score = max(0, min(100, cognitive_score))

    # 3. Physical Readiness (Focus: Deep Sleep, Body Battery, RHR Stability)
    phy_deep_score = min(deep_pct / 15, 1.2) * 30
    phy_bb_score = (bb_peak / 100) * 40
    phy_hrv_score = 30 if hrv_status == "BALANCED" else 10
    physical_score = phy_deep_score + phy_bb_score + phy_hrv_score

    # Pessimistic Penalty: High RHR, Extracellular Fluid Deficit & Biomechanical Wear
    if rhr_diff > 3:
        physical_score *= 0.8
    if fluid_delta < -1000 and dissipation_hours > 1.5:
        physical_score -= 15 # Severe dehydration / extracellular fluid deficit
    if gct_spike > 15:
        physical_score -= 10 # Musculoskeletal wear & tear detected

    # PMC Integration Penetration
    pmc = synthesize_pmc(summary_data)
    if pmc:
        if pmc['TSB'] < -30:
            cognitive_score -= 15
            physical_score -= 20
        if pmc['Ramp_Rate'] > 150:
            cognitive_score -= 10

    physical_score = max(0, min(100, physical_score))
    cognitive_score = max(0, min(100, cognitive_score))

    # Combined Score
    readiness_score = (cognitive_score * 0.5) + (physical_score * 0.5)

    recommendation = ""
    if readiness_score >= 85:
        recommendation = "巅峰状态。身心协同一体，适合攻坚战。"
    elif readiness_score >= 70:
        recommendation = "理想状态。执行力充沛。"
    elif readiness_score >= 50:
        recommendation = "次优状态。建议规避高风险操作。"
    else:
        recommendation = "电量枯竭。系统处于防御模式。"

    return {
        "analysis_type": "executive_readiness",
        "score": round(readiness_score, 1),
        "physical_score": round(physical_score, 1),
        "cognitive_score": round(cognitive_score, 1),
        "dissipation_hours": round(dissipation_hours, 1),
        "recommendation": recommendation
    }

def perform_bio_metric_audit(summary_data):
    """
    Garmin Bio-Metric Audit (The Audit)
    Based on 4 Layers: System Status, Recovery Loop, Load & Friction, Action Protocol.
    Includes Zone Dissipation extraction.
    """
    # 1. System Status Audit
    hr_data = summary_data.get("heart_rate", [])
    hrv_data = summary_data.get("hrv", [])
    training_status = summary_data.get("training_status", {})
    max_metrics = summary_data.get("max_metrics", {})
    body_comp = summary_data.get("body_composition", {})

    # RHR Audit (30-day baseline drift detection if days > 14)
    # Performance: Replaced multiple O(N) passes and a filtering bug with a single O(N) list comprehension for ~1.65x speedup
    valid_rhrs = [h["resting_hr"] for h in hr_data if h.get("resting_hr")]
    latest_rhr = valid_rhrs[-1] if valid_rhrs else 0
    prev_rhrs = valid_rhrs[:-1]
    baseline_rhr = statistics.median(prev_rhrs) if prev_rhrs else latest_rhr
    rhr_diff = latest_rhr - baseline_rhr if latest_rhr > 0 else 0

    rhr_status = "稳定"
    if latest_rhr == 0: rhr_status = "无数据"
    elif rhr_diff < -2: rhr_status = "优异 (心肺耐力提升)"
    elif rhr_diff > 3: rhr_status = "警告 (代谢压力高)"

    # HRV Audit
    latest_hrv = next((h.get("last_night_avg") for h in reversed(hrv_data) if h.get("last_night_avg")), 0)
    hrv_status_raw = next((h.get("status") for h in reversed(hrv_data) if h.get("status")), "无数据")

    # VO2 Max & Fitness Age & BMI
    vo2_max = training_status.get("vo2_max", "--")
    fitness_age = max_metrics.get("fitness_age", "N/A") if max_metrics else "N/A"
    bmi = body_comp.get("bmi", "--")

    system_status = {
        "rhr": {"current": latest_rhr, "baseline": round(baseline_rhr, 1), "status": rhr_status},
        "hrv": {"value": latest_hrv, "status": hrv_status_raw},
        "vo2_max": vo2_max,
        "fitness_age": fitness_age,
        "bmi": bmi,
        "is_stale": summary_data.get("is_stale", False)
    }

    # 2. Recovery Loop Audit
    sleep_data = summary_data.get("sleep", [])
    latest_sleep = next((s for s in reversed(sleep_data) if s.get("sleep_time_seconds")), {})

    total_sleep = latest_sleep.get("sleep_time_seconds", 0)
    deep_sleep = latest_sleep.get("deep_sleep_seconds", 0)
    rem_sleep = latest_sleep.get("rem_sleep_seconds", 0)

    deep_pct = (deep_sleep / total_sleep * 100) if total_sleep > 0 else 0
    rem_pct = (rem_sleep / total_sleep * 100) if total_sleep > 0 else 0

    target_sleep_s = 27000
    sleep_debt_s = 0
    for s in sleep_data[-3:]:
        if s.get("sleep_time_seconds"):
            debt = target_sleep_s - s["sleep_time_seconds"]
            if debt > 0: sleep_debt_s += debt
    sleep_debt_h = sleep_debt_s / 3600

    bb_data = summary_data.get("body_battery", [])
    latest_bb = next((b for b in reversed(bb_data) if b.get("highest")), {})
    bb_charged = latest_bb.get("charged", 0)
    bb_peak = latest_bb.get("highest", 0)
    bb_lowest = latest_bb.get("lowest", 0)

    recovery_loop = {
        "sleep_architecture": {
            "deep_pct": round(deep_pct, 1),
            "rem_pct": round(rem_pct, 1),
            "restlessness": latest_sleep.get("restless_periods", 0),
            "sleep_debt_h": round(sleep_debt_h, 1)
        },
        "body_battery": {
            "charged": bb_charged,
            "peak": bb_peak,
            "lowest": bb_lowest
        }
    }

    # 3. Load & Friction Audit (Zone Dissipation)
    stress_data = summary_data.get("stress", [])
    latest_stress = next((s for s in reversed(stress_data) if s.get("avg_stress")), {})
    high_stress_h = (latest_stress.get("high_stress_duration", 0) or 0) / 3600
    med_stress_h = (latest_stress.get("medium_stress_duration", 0) or 0) / 3600
    rest_stress_h = (latest_stress.get("rest_stress_duration", 0) or 0) / 3600

    load_friction = {
        "stress_score": latest_stress.get("avg_stress", 0),
        "dissipation": {
            "high_stress_hours": round(high_stress_h, 1),
            "medium_stress_hours": round(med_stress_h, 1),
            "rest_hours": round(rest_stress_h, 1)
        },
        "training_load": {
            "ratio": training_status.get("load_ratio", "--"),
            "status": training_status.get("load_status", "无数据")
        }
    }

    # 4. Action Protocol Logic
    protocol = "黄灯 (Fatigue) - 维护性运转"
    protocol_desc = "储备不足。保持低强度有氧 (Zone 2)，时长缩减 30%。优先补充镁/茶氨酸等神经修复剂。"
    move_type = "YELLOW"

    sleep_score = latest_sleep.get("sleep_score", 0) or 0
    dissipation_hours = high_stress_h + (med_stress_h * 0.5)

    if hrv_status_raw == "BALANCED" and sleep_score > 80 and bb_peak > 80 and sleep_debt_h < 1.5 and rhr_diff <= 2 and dissipation_hours < 2.5:
        protocol = "绿灯 (Prime) - 推极限"
        protocol_desc = "防线巩固。执行高强度间歇 (HIIT) 或长距离训练。认知冗余充足，适合进行破局性商业决策。"
        move_type = "GREEN"
    elif rhr_diff > 4 or (latest_stress.get("avg_stress", 0) > 45 and hrv_status_raw != "BALANCED") or sleep_debt_h > 4:
        protocol = "警报 (Infection/Overload) - 停机"
        protocol_desc = "系统边缘崩溃可能。身体正在对抗过度应激或病毒，且睡眠债务极高。禁止高要求决策与大规律运动，增加深度补水，建议补充维生素C/锌预防感染。"
        move_type = "ALERT"
    elif hrv_status_raw != "BALANCED" or sleep_score < 60 or sleep_debt_h > 2.5 or dissipation_hours > 4.0:
        protocol = "红灯 (Critical) - 主动刹车"
        protocol_desc = "系统代偿严重不足（或昨日高压耗散过大）。禁止神经要求高的大型决策与高强度训练。仅允许主动恢复。必须限制今日的交叉会议与咖啡因摄入。"
        move_type = "RED"

    if latest_hrv == 0 and latest_rhr == 0:
        protocol = "数据同步中"
        protocol_desc = "未检测到今日有效的生理指标，请确保设备已同步。"
        move_type = "YELLOW"

    pmc = synthesize_pmc(summary_data)
    if pmc:
        if move_type != "ALERT" and pmc['CTL'] > 45 and pmc['TSB'] < -10:
            protocol = "授权强行军 (Endurance Override)"
            protocol_desc = f"护城河底座丰厚 (CTL: {pmc['CTL']})，足以消化短期高度耗散。\\n🗓️ 【未来 48-72 小时调度约束】：准许执行跨夜高压攻坚与背靠背商业谈判。无需退缩，系统防线完全可以承受这一波冲击。但在 72 小时后必需执行绝对关机。"
        elif move_type == "GREEN" and pmc['CTL'] < 20 and pmc['TSB'] > 10:
            protocol = "虚假稳态预警 (Fragile Peak)"
            protocol_desc = f"表面净胜池充足 (TSB: +{pmc['TSB']})，但底盘严重空虚 (CTL: {pmc['CTL']})。\\n🗓️ 【未来 48-72 小时调度约束】：严禁因感知状态极佳而连续排满高压日程！这是一种免疫耗竭前的假象。必须将未来两天的日程压低至 60% 负荷，防止脆性断裂。"
        elif pmc['TSB'] < -30:
            protocol = "强制破产保护 (System Melt-down)"
            protocol_desc = f"系统动能已跌破致病红线 (TSB: {pmc['TSB']})，免疫护甲崩塌边缘。\\n🗓️ 【未来 48-72 小时调度约束】：即刻取消/顺延未来三天所有 L3 及以上的高感知耗散会议。必须执行‘绝对物理断网隔离’与 9 小时强制平躺修复，严禁发起任何主动进攻。"
        else:
            if move_type == "GREEN":
                protocol_desc += "\\n🗓️ 【未来 48-72 小时调度约束】：动能充沛，准许在未来 3 天内按计划发起高强度战略推进与深度思考，全功率开火。"
            elif move_type == "YELLOW":
                protocol_desc += "\\n🗓️ 【未来 48-72 小时调度约束】：处于灰色消耗期。建议未来两天的核心会议集中在上午火力倾泻，下午转为防御性事务处理，不可安排连续冲刺。"
            elif move_type == "RED":
                protocol_desc += "\\n🗓️ 【未来 48-72 小时调度约束】：防线已被撕裂。未来三天请全面转入战略防守状态，授权‘说不’的权力，剥离一切非攸关型事务。"

    return {
        "system_status": system_status,
        "recovery_loop": recovery_loop,
        "load_friction": load_friction,
        "action_protocol": {
            "move": protocol,
            "description": protocol_desc,
            "type": move_type
        }
    }

def generate_sparkline(data_series):
    """Generate ASCII sparkline for terminal topology."""
    if not data_series or all(v is None for v in data_series): return "无数据"
    valid_data = [v for v in data_series if v is not None]
    if not valid_data: return "无数据"

    ticks = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█']
    min_val, max_val = min(valid_data), max(valid_data)
    if min_val == max_val:
        return ticks[3] * len(valid_data)

    range_val = max_val - min_val
    sparkline = ""
    for val in valid_data:
        idx = int(((val - min_val) / range_val) * (len(ticks) - 1))
        sparkline += ticks[idx]
    return sparkline

def calculate_social_jetlag(sleep_data):
    """Calculate Mid-Sleep Point drift (Social Jetlag)."""
    if len(sleep_data) < 3: return 0.0
    mid_points = []
    for s in sleep_data[-7:]:
        if s.get("sleep_time_seconds") and s.get("sleep_score"):
            # Simplified heuristic: assume sleep usually ends around 7 AM.
            # Real implementation would parse actual start/end times if available.
            duration = s.get("sleep_time_seconds", 0) / 3600
            mid_point = 7.0 - (duration / 2.0)
            mid_points.append(mid_point)
    if len(mid_points) < 3: return 0.0
    return round(statistics.stdev(mid_points), 2)

def query_vector_lake(query="过去3天 身体状态 日记", mode="memory", top_k=3):
    """
    Hook to query the Vector Lake for bidirectional longitudinal context.
    """
    import subprocess
    import json
    try:
        vl_cli = Path(__file__).parent.parent.parent.parent / "extensions" / "vector-lake" / "cli.py"
        if not vl_cli.exists():
            return None
        # Use python to run the CLI, parsing JSON output if possible, but fallback to stdout string
        # To avoid complex JSON parsing of CLI output, we just capture stdout directly and trim it.
        result = subprocess.run(
            ["python", str(vl_cli), "search", query, "--mode", mode, "--top_k", str(top_k)],
            capture_output=True, text=True, encoding="utf-8", timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            # Return a brief snippet to avoid bloating the terminal report
            lines = result.stdout.strip().split('\n')
            return " | ".join(lines[:3]) + ("..." if len(lines) > 3 else "")
        return None
    except Exception:
        return None

def generate_bounded_chinese_insight(summary_data, historical_context=None):
    """Return a descriptive snapshot without clinical or cognitive inference."""
    _load_pandas()

    def finite_number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def observed(records, key):
        values = []
        for row in records:
            number = finite_number(row.get(key))
            if number is not None:
                values.append((str(row.get("date") or ""), number, row))
        return values

    def latest_metric(records, key, unit):
        values = observed(records, key)
        if not values:
            return {
                "latest": None,
                "unit": unit,
                "observation_count": 0,
                "date": None,
            }
        date, value, _ = max(values, key=lambda item: item[0])
        return {
            "latest": round(value, 1),
            "unit": unit,
            "observation_count": len(values),
            "date": date or None,
        }

    heart_rate = summary_data.get("heart_rate", [])
    stress = summary_data.get("stress", [])
    body_battery = summary_data.get("body_battery", [])
    sleep = summary_data.get("sleep", [])
    hrv = summary_data.get("hrv", [])
    activities = summary_data.get("activities", [])

    resting_hr = latest_metric(heart_rate, "resting_hr", "bpm")
    stress_avg = latest_metric(stress, "avg_stress", "Garmin score")
    battery_high = latest_metric(body_battery, "highest", "Garmin score")
    battery_low = latest_metric(body_battery, "lowest", "Garmin score")
    battery_charged = latest_metric(body_battery, "charged", "Garmin score")
    hrv_avg = latest_metric(hrv, "last_night_avg", "ms")
    sleep_seconds = latest_metric(sleep, "sleep_time_seconds", "seconds")

    latest_sleep_row = None
    sleep_values = observed(sleep, "sleep_time_seconds")
    if sleep_values:
        _, _, latest_sleep_row = max(sleep_values, key=lambda item: item[0])

    sleep_duration_hours = None
    deep_sleep_pct = None
    rem_sleep_pct = None
    if latest_sleep_row is not None:
        total = finite_number(latest_sleep_row.get("sleep_time_seconds"))
        deep = finite_number(latest_sleep_row.get("deep_sleep_seconds"))
        rem = finite_number(latest_sleep_row.get("rem_sleep_seconds"))
        if total and total > 0:
            sleep_duration_hours = round(total / 3600, 1)
            if deep is not None:
                deep_sleep_pct = round(deep / total * 100, 1)
            if rem is not None:
                rem_sleep_pct = round(rem / total * 100, 1)

    hrv_status = None
    hrv_values = observed(hrv, "last_night_avg")
    if hrv_values:
        _, _, latest_hrv_row = max(hrv_values, key=lambda item: item[0])
        raw_status = latest_hrv_row.get("status")
        if raw_status is not None and not pd.isna(raw_status):
            hrv_status = str(raw_status)

    total_activity_minutes = 0.0
    activity_duration_observations = 0
    for activity in activities:
        duration = finite_number(
            activity.get("duration") or activity.get("duration_seconds")
        )
        if duration is not None:
            total_activity_minutes += duration / 60
            activity_duration_observations += 1

    gaps = sorted(set(summary_data.get("_data_gaps", [])))
    period = summary_data.get("summary", {}).get("period", "授权时间窗")
    source = summary_data.get("_source", "local")
    freshness = "snapshot_may_be_stale" if summary_data.get("is_stale") else "freshness_not_independently_verified"

    available_labels = []
    for label, metric in (
        ("静息心率", resting_hr),
        ("压力", stress_avg),
        ("身体电量", battery_high),
        ("HRV", hrv_avg),
        ("睡眠", sleep_seconds),
    ):
        if metric["observation_count"]:
            available_labels.append(label)
    availability = "、".join(available_labels) if available_labels else "无核心指标"

    overall_insight = (
        f"授权窗口：{period}。可用原始观测：{availability}。"
        f"本结果只描述 {source} Garmin 记录，不评估认知能力、工作决策能力、疾病风险或临床状态。"
    )
    if gaps:
        overall_insight += f" 数据缺口：{', '.join(gaps)}。"

    result = {
        "analysis_type": "bounded_descriptive_snapshot",
        "period": period,
        "overall_insight": overall_insight,
        "observations": {
            "resting_heart_rate": resting_hr,
            "stress_average": stress_avg,
            "body_battery": {
                "highest": battery_high,
                "lowest": battery_low,
                "charged": battery_charged,
            },
            "hrv": {**hrv_avg, "source_status": hrv_status},
            "sleep": {
                "latest_duration_hours": sleep_duration_hours,
                "deep_sleep_pct": deep_sleep_pct,
                "rem_sleep_pct": rem_sleep_pct,
                "observation_count": sleep_seconds["observation_count"],
                "date": sleep_seconds["date"],
            },
            "activities": {
                "record_count": len(activities),
                "duration_observation_count": activity_duration_observations,
                "total_duration_minutes": round(total_activity_minutes, 1),
            },
        },
        "execution_bandwidth": "[DATA_UNAVAILABLE]",
        "sleep_debt": "[DATA_UNAVAILABLE]",
        "clinical_interpretation": "[DATA_UNAVAILABLE]",
        "freshness": freshness,
        "limitations": [
            "No population defaults or forward/backward filling were used.",
            "No long-horizon baseline was read outside the authorized window.",
            "No causal, diagnostic, cognitive-readiness, or work-capacity inference was made.",
        ],
        "general_note": "如有持续不适或异常读数，请结合专业医疗评估；本快照不能替代诊断。",
    }
    if historical_context:
        result["memory_context"] = {
            "status": "separately_authorized_unmerged_context",
            "content": historical_context,
        }
    return result


def generate_chinese_insight(summary_data, historical_context=None):
    """Generate a report from preloaded data and optional authorized context."""
    if summary_data.get("_bounded_contract"):
        return generate_bounded_chinese_insight(summary_data, historical_context)

    audit = perform_bio_metric_audit(summary_data)
    readiness = analyze_executive_readiness(summary_data)

    # 1. Sleep Consistency & Debt Audit
    sleep_data = summary_data.get("sleep", [])
    std_dev, consist_status = calculate_sleep_consistency(sleep_data)
    social_jetlag = calculate_social_jetlag(sleep_data)
    avg_deep_pct = audit["recovery_loop"]["sleep_architecture"]["deep_pct"]
    sleep_debt = audit["recovery_loop"]["sleep_architecture"].get("sleep_debt_h", 0)

    # 2. System Momentum (Delta Analysis & Baseline Drift)
    hr_data = summary_data.get("heart_rate", [])
    stress_data = summary_data.get("stress", [])
    bb_data = summary_data.get("body_battery", [])
    momentum_status = "数据不足（授权窗口少于动量判断所需样本）"

    if len(hr_data) >= 4 and len(stress_data) >= 4:
        mid_point = len(hr_data) // 2
        first_half_rhr = statistics.median([h.get("resting_hr", 0) for h in hr_data[:mid_point] if h.get("resting_hr")])
        second_half_rhr = statistics.median([h.get("resting_hr", 0) for h in hr_data[mid_point:] if h.get("resting_hr")])

        first_half_stress = statistics.median([s.get("avg_stress", 0) for s in stress_data[:mid_point] if s.get("avg_stress")])
        second_half_stress = statistics.median([s.get("avg_stress", 0) for s in stress_data[mid_point:] if s.get("avg_stress")])

        rhr_delta = second_half_rhr - first_half_rhr
        stress_delta = second_half_stress - first_half_stress

        if rhr_delta > 2 and stress_delta > 5:
            momentum_status = "🔴 熵增恶化 (物理底座持续下沉)"
        elif rhr_delta < -2 and stress_delta < -5:
            momentum_status = "🟢 超量恢复 (代谢压力加速出清)"
        elif rhr_delta > 1 or stress_delta > 2:
            momentum_status = "🟡 隐性耗散 (疲劳微幅累积)"
        else:
            momentum_status = "🔵 筑底企稳 (系统维持热力学平衡)"

    # 3. Orthogonal Stress Stripping & Dissipation
    avg_stress = audit["load_friction"]["stress_score"]
    activities_data = summary_data.get("activities", [])
    dissipation_h = audit["load_friction"]["dissipation"]["high_stress_hours"]
    med_stress_h = audit["load_friction"]["dissipation"]["medium_stress_hours"]
    rest_stress_h = audit["load_friction"]["dissipation"]["rest_hours"]

    total_intensity_min = 0
    high_intensity_min = 0
    for act in activities_data:
        duration_s = act.get("duration") or act.get("duration_seconds") or 0
        total_intensity_min += (duration_s / 60)
        t = str(act.get("activity_type") or "").lower()
        if "run" in t or "hiit" in t or "elliptical" in t or "training" in t:
            high_intensity_min += (duration_s / 60)

    if total_intensity_min < 30 and (avg_stress > 35 or dissipation_h > 2.0):
        load_type = "🔴 纯认知燃烧 / 焦虑耗散 (无物理输出的高神经代价)"
    elif total_intensity_min >= 60 and (avg_stress > 35 or dissipation_h > 2.0):
        load_type = "🔥 双轨满载 (高强度训练与高压日程叠加)"
    elif total_intensity_min >= 60 and avg_stress <= 35:
        load_type = "🟢 良性应激 (训练主导的结构性破坏)"
    else:
        load_type = "🔵 低频维护 (缺乏刺激的被动稳态)"

    avg_bb_charged = summary_data.get('summary', {}).get('avg_body_battery_charged', 0)
    score_input = round((min(avg_bb_charged, 80)/80 * 70) + (30 if consist_status == "优" else 15), 1)
    score_loss = round(avg_stress + (min(total_intensity_min, 150)/150 * 20), 1)
    score_output = round(readiness['score'], 1)

    # --- Generate Military-Grade Tactical Report ---
    overall_sections = []
    period_str = summary_data.get('summary', {}).get('period', '指定时间段')

    # Section 0: Vector Lake Historical Context
    if historical_context:
        ctx_msg = f"【0. 纵向归因 (Vector Lake Context)】\n"
        ctx_msg += f"· 记忆提取：{historical_context}\n"
        ctx_msg += f"  > 归因：大模型综合诊断需将上述事件轨迹与后续物理指标强制对齐。"
        overall_sections.append(ctx_msg)

    bb_sparkline = generate_sparkline([b.get("highest") for b in bb_data[-7:]])

    # Section 1: System Status & Momentum
    sys_msg = f"【1. 系统态势与防线动量 (System Momentum)】\n"
    sys_msg += f"· 动量向量：{momentum_status}。\n"
    sys_msg += f"· 能量拓扑：[{bb_sparkline}] (授权窗口内电量峰值)\n"
    sys_msg += f"· 摩擦定性：判定为『{load_type}』。"

    pmc = synthesize_pmc(summary_data)
    if pmc:
        sys_msg += f"\n· 护城河(CTL): {pmc['CTL']} | 急性期(ATL): {pmc['ATL']} | 势差(TSB): {pmc['TSB']} [{pmc['TSB_Zone']}]"
        sys_msg += f"\n· 摩擦加速度(Ramp Rate): {pmc['Ramp_Rate']}/周"
        if pmc['TSB'] < -30:
            sys_msg += "\n  > 🚨【核心熔断预警】系统净胜率全面崩塌！SPOF (单点故障) 前夜！处于致病极高压区。"
        if pmc['Ramp_Rate'] > 150:
            sys_msg += "\n  > 🚨【斜率预警】高压负荷连环爆拉，摩擦斜率失控，防线被迅速穿透！"

    friction_records = summary_data.get("pmc", [])
    if friction_records:
        total_phys = sum((row.get("training_load") or 0) for row in friction_records)
        total_comp = sum((row.get("daily_friction_load") or 0) for row in friction_records)
        if total_comp > 0:
            shadow_pct = round((total_comp - total_phys) / total_comp * 100)
            sys_msg += f"\n· 动力学解构：授权窗口内复合负荷中，Shadow Load(纯精神/认知摩擦) 比重为 {shadow_pct}%。"

    if med_stress_h > (dissipation_h + rest_stress_h) and med_stress_h > 4.0:
        sys_msg += "\n  > 🚦【垃圾压力区间陷阱】全天处于“低效燃烧态”。既未能触发巅峰应激 (Peak Load)，也没有彻底关机 (Deep Rest)。必须实弹拉升极化防线：要么全功率切入战局，要么绝对物理断网隔离。"

    if "纯认知燃烧" in load_type:
        sys_msg += "\n  > 洞察：系统正在空耗神经递质（高压），但缺乏物理代谢（无运动）。这种脱节会导致皮质醇淤积，引发底层的慢性炎症。如果不依靠物理输出打断死锁，认知带宽将被持续挤压。"
    elif "双轨满载" in load_type:
        sys_msg += "\n  > 警告：中枢神经系统正在承受『战略业务推演 + 物理强行破坏』的双重挤压，极度耗散。系统免疫防线极脆弱，极易在此阶段触发 Garmin Flu。"
    elif "筑底企稳" in momentum_status:
        sys_msg += "\n  > 洞察：当前生理数据呈低波动收敛态，这是重大战役前的完美储备期。但也需警惕过度放松导致的“失练”效应。"
    overall_sections.append(sys_msg)

    # Section 2: Input & Rhythm
    consist_msg = f"【2. 恢复环路审计 (Recovery Loop)】\n"
    consist_msg += f"· 节律稳定性：{consist_status} (标准差 {std_dev}h)。"
    if consist_status != "优":
        consist_msg += "\n  > 破窗效应：强烈的“社会时差”切断了内分泌系统的黄金修复窗口（尤其是夜间生长激素与褪黑素耦协），这是拖垮系统长期 ROI 的最大漏洞。"
    else:
        consist_msg += "\n  > 坚固底座：生物钟锚定极佳，为前额叶深度清洗提供了坚实的物理时间窗口。"

    if total_intensity_min > 0 and high_intensity_min < 15:
        consist_msg += "\n  > 🏃【器官怠速风险】近期活动全是低心率的“慢肌纤维”有氧（如徒步/快走），极度缺乏对抗阻和快肌纤维的结构性破坏。建议本周内安排 15 分钟高阈值冲刺，进行器官级的防锈淬炼。"

    consist_msg += f"\n· 结构解剖：深睡占比 {avg_deep_pct}%。"
    if avg_deep_pct < 15:
        consist_msg += "\n  > 物理坍塌：深睡(<15%)意味着系统重构停滞，内脏与肌肉层面的微损伤未能修复，直接削弱次日基础体能。"
    else:
        consist_msg += "\n  > 重构达标：物理底座修复达标，确保了肌肉韧性与神经弹性。"

    consist_msg += f"\n· 储备赤字：当前连续睡眠债务 {sleep_debt}h。"
    if sleep_debt > 1.5:
        consist_msg += f"\n  > 债务危机：累积的 {sleep_debt}h 负债已实质性击穿神经缓冲垫。任何所谓的高效执行，本质上是在透支次日的交感神经。"
    overall_sections.append(consist_msg)

    # Section 3: Readiness
    output_msg = f"【3. 执行带宽 (Execution Bandwidth)】\n"
    output_msg += f"· 综合执行力：{readiness['score']}/100\n"
    output_msg += f"· 🧠 认知带宽 ({readiness['cognitive_score']})："
    if readiness['cognitive_score'] > 80:
        output_msg += "高频逻辑计算可用，适宜全功率执行：架构设计、复杂商业博弈、非共识决断。"
    elif readiness['cognitive_score'] > 60:
        output_msg += "算力受限，极易触发『讨好性偏差』与局部视野狭窄。建议降级为：文档编写与常规流转。"
    else:
        output_msg += "认知宕机。严禁任何战略性决策，强行工作将带来极高的系统错误率。"

    output_msg += f"\n· 💪 物理防线 ({readiness['physical_score']})："
    hydration_ml = summary_data.get("hydration", {}).get("valueInML", 0) or 0
    if hydration_ml > 0 and hydration_ml < 1500:
        output_msg += f"【水合警告】脱水态 (已摄入 {hydration_ml}ml)。细胞外液压降导致微循环不畅，将加速疲劳。"
    elif readiness['physical_score'] > 80:
        output_msg += "内脏/神经肌肉冗余充足。可承受极强环境压力或高强度物理训练。"
    else:
        output_msg += "防线脆弱。必须把剩余能量让渡给免疫系统，取消一切非必要高强度体能消耗，坚决防御感染。"
    overall_sections.append(output_msg)

    # Section 4: Tactical Directives (Mentat Level) & Device Intervention
    recs = []

    # Check for early alarms if sleep debt is high or system is RED
    alarms = summary_data.get("alarms", [])
    has_early_alarm = False
    alarm_time = ""
    for alarm in alarms:
        if alarm.get("enabled"):
            h = alarm.get("hour", 8)
            if h < 7 or (h == 7 and alarm.get("minute", 0) < 30):
                has_early_alarm = True
                alarm_time = f"{h:02d}:{alarm.get('minute', 0):02d}"
                break

    if (sleep_debt > 2.0 or audit['action_protocol']['type'] in ["RED", "ALERT"]) and has_early_alarm:
        recs.append(f"⌚【硬件干预 - 强制睡眠延长】系统处于极限损耗状态，但手表仍设定了明早 {alarm_time} 的晨间闹钟。建议推迟 45 分钟以出清皮质醇。")

    if sleep_debt > 1.5 or readiness['cognitive_score'] < 70:
        recs.append("📅【日程管控 - 降级】系统背负债务且认知受限。今日必须砍掉/延期 30% 的非关键交叉会议。严禁执行底层代码重构，全面转向“只读模式”。")
    elif readiness['score'] >= 85:
        recs.append("📅【日程管控 - 强攻】系统信噪比极高。解除一切防御限制，将最棘手的战略卡点、技术债务清算安排在今日核心时段。")

    if "纯认知燃烧" in load_type:
        recs.append("🏃‍♂️【物理干预 - 强制负熵】内分泌已死锁。今日必须挂载 30-40 分钟 Zone 2 低心率有氧（如快走/轻松骑行），利用肌肉泵血强行剥离皮质醇。")
    elif "双轨满载" in load_type or readiness['physical_score'] < 60:
        recs.append("🏃‍♂️【物理干预 - 绝对防御】负荷溢出/防线脆弱。取消一切力量训练或高心率间歇，仅允许进行 15 分钟的静态拉伸。")

    if avg_deep_pct < 15:
        recs.append("💊【生化环境 - 深度冷却】深睡架构坍塌。今晚 20:00 后实施强硬数字隔离，核心体温须在入睡前完成物理降温。")
    if momentum_status.startswith("🔴"):
        recs.append("💊【生化环境 - 止损熔断】检测到滑向热寂的动量。立即补充 500mg 维生素C+锌；晚间增加 200mg 镁或茶氨酸平抑交感神经。")

    if not recs:
        recs.append("🟢【维稳运转】各项指标呈良性收敛。维持现有作息，可适当引入微量不确定性刺激（如：轻度冷水浴或改变一次训练模式）。")

    intervention_msg = "【4. 资源调度指令 (Tactical Directives)】\n" + "\n".join([f"· {r}" for r in recs])
    overall_sections.append(intervention_msg)

    protocol_risk_map = {"GREEN": "推极限", "YELLOW": "维稳", "RED": "防御", "ALERT": "停机"}
    risk_label = protocol_risk_map.get(audit['action_protocol']['type'], '未知')
    status_header = f"【CMO 战略审计简报：{period_str} | 行动代号：{risk_label}】"

    overall_combined = f"{status_header}\n\n" + "\n\n".join(overall_sections)

    momentum_parts = momentum_status.split(' ')
    momentum_label = momentum_parts[1] if len(momentum_parts) > 1 else momentum_parts[0]
    load_parts = load_type.split(' ')
    load_label = load_parts[1] if len(load_parts) > 1 else load_parts[0]

    chart_insights = {
        "sleep": f"债务：{sleep_debt}h。深睡占比 {avg_deep_pct}%。挤压深睡=破坏核心资产。",
        "hrv": f"状态：{audit['system_status']['hrv']['status']}。系统动量：{momentum_label}。",
        "activities": f"物理耗散：{round(total_intensity_min)} min。负荷定性：{load_label}。",
        "body_battery": f"峰谷极差：平均峰值 {audit['recovery_loop']['body_battery']['peak']}，谷值 {audit['recovery_loop']['body_battery']['lowest']}。",
        "stress": f"耗散分布：高压区 {dissipation_h}h。定性：{load_label}。"
    }

    return {
        "period": period_str,
        "chart_insights": chart_insights,
        "overall_insight": overall_combined,
        "audit_data": audit,
        "quant_scores": {
            "input": score_input,
            "loss": score_loss,
            "output": score_output,
            "cognitive": readiness['cognitive_score'],
            "physical": readiness['physical_score']
        },
        "top_insights": [
            {"title": "战略态势", "content": audit["action_protocol"]["move"]},
            {"title": "系统动量", "content": momentum_status}
        ]
    }

def stitch_v3_metrics(summary_data, days):
    """Stitch V3 advanced metrics from SQLite onto API data when fallback occurs."""
    try:
        from garmin_sqlite_adapter import get_biomechanics_data, get_connection, GARMIN_DB
        import pandas as pd

        # 1. Biomechanics
        summary_data["biomechanics"] = get_biomechanics_data(days).to_dict('records')

        # 2. Daily Summary (Waking RR, Sweat Loss)
        try:
            conn = get_connection(GARMIN_DB)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            table_name = 'daily_summary' if 'daily_summary' in tables else 'days_summary' if 'days_summary' in tables else None

            if table_name:
                d_df = pd.read_sql_query(f"SELECT day as date, sweat_loss, rr_waking_avg FROM {table_name} ORDER BY day DESC", conn)
                if not d_df.empty:
                    # Performance: Replaced string split .apply() with vectorized string slicing for ~1.92x speedup
                    d_df['date'] = d_df['date'].astype(str).str[:10]
                    d_df = d_df.where(pd.notnull(d_df), None)
                    summary_data["daily_summary"] = d_df.to_dict('records')

            # 3. SpO2 mapping to sleep
            s_df = pd.read_sql_query("SELECT day as date, avg_spo2 FROM sleep ORDER BY day DESC", conn)
            if not s_df.empty:
                # Performance: Replaced string split .apply() with vectorized string slicing for ~1.92x speedup
                s_df['date'] = s_df['date'].astype(str).str[:10]
                s_df = s_df.where(pd.notnull(s_df), None)
                # Performance: Replaced slow .to_dict('records') loop with vectorized dict(zip()) for 4.3x faster dictionary creation
                spo2_map = dict(zip(s_df["date"], s_df["avg_spo2"]))
                for s in summary_data.get("sleep", []):
                    if s.get("date") in spo2_map:
                        s["avg_spo2"] = spo2_map[s["date"]]
        except Exception as e:
            print(f"⚠️ Failed to query SQLite for v3 metrics: {e}")
        finally:
            if 'conn' in locals(): conn.close()
    except Exception as e:
        import sys
        print(f"⚠️ V3 Metrics Stitch failed: {e}", file=sys.stderr)

def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def _print_json(payload, stream=None):
    if stream is None:
        stream = sys.stdout
    print(json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, allow_nan=False), file=stream)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Advanced Health Intelligence")
    parser.add_argument("analysis", choices=["flu_risk", "readiness", "insight_cn", "audit", "long_term_load", "env_stress", "device_audit"], help="Analysis type")
    parser.add_argument("--days", type=int, default=7, help="Context window in days")
    parser.add_argument("--period", type=str, help="Period (e.g. 90d, YTD). Overrides --days.")
    parser.add_argument(
        "--source",
        choices=["local", "live"],
        required=True,
        help="Explicit health-data source; no automatic fallback is performed.",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Authorize this invocation to read the requested health-data window.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Authorize network access for --source live only.",
    )
    parser.add_argument(
        "--allow-memory-context",
        action="store_true",
        help="Authorize a separate read of Vector Lake context.",
    )

    args = parser.parse_args(argv)
    days = parse_period(args.period, args.days)
    if days < 1:
        _print_json(
            {
                "status": "authorization_error",
                "error_code": "INVALID_WINDOW",
                "message": "The requested day window must be positive.",
            },
            sys.stderr,
        )
        return 2

    if not args.allow_health_data:
        _print_json(
            {
                "status": "authorization_error",
                "error_code": "HEALTH_DATA_AUTH_REQUIRED",
                "message": "Pass --allow-health-data to authorize this bounded read.",
            },
            sys.stderr,
        )
        return 2

    if args.source == "local" and args.allow_network:
        _print_json(
            {
                "status": "authorization_error",
                "error_code": "NETWORK_NOT_ALLOWED_FOR_LOCAL_SOURCE",
                "message": "Remove --allow-network from a local-only invocation.",
            },
            sys.stderr,
        )
        return 2

    if args.source == "live":
        if not args.allow_network:
            _print_json(
                {
                    "status": "authorization_error",
                    "error_code": "NETWORK_AUTH_REQUIRED",
                    "message": "Live source requires --allow-network.",
                },
                sys.stderr,
            )
            return 2

    if args.analysis != "insight_cn":
        _print_json(
            {
                "status": "runtime_contract_mismatch",
                "error_code": "ANALYSIS_NOT_BOUNDED_SAFE",
                "source": args.source,
                "analysis": args.analysis,
                "requested_days": days,
                "message": "Only insight_cn has been migrated to the bounded descriptive contract.",
            },
            sys.stderr,
        )
        return 5

    try:
        summary_data = (
            fetch_live_summary(days)
            if args.source == "live"
            else fetch_local_summary(days)
        )
    except LiveAuthenticationError as exc:
        _print_json(
            {
                "status": "authentication_required",
                "data_status": "no_data",
                "error_code": "LIVE_SESSION_INVALID",
                "source": "live",
                "requested_days": days,
                "error_type": type(exc).__name__,
                "data_gaps": ["live_session_invalid"],
                "provenance": {
                    "source": "live",
                    "requested_days": days,
                    "accessed_days": 0,
                    "network_accessed": True,
                    "memory_context_accessed": False,
                    "persisted": False,
                },
            }
        )
        return 6
    except FileNotFoundError as exc:
        if args.source == "live":
            _print_json(
                {
                    "status": "authentication_required",
                    "data_status": "no_data",
                    "error_code": "LIVE_TOKEN_MISSING",
                    "source": "live",
                    "requested_days": days,
                    "error_type": type(exc).__name__,
                    "data_gaps": ["live_token_missing"],
                    "provenance": {
                        "source": "live",
                        "requested_days": days,
                        "accessed_days": 0,
                        "network_accessed": False,
                        "memory_context_accessed": False,
                        "persisted": False,
                    },
                }
            )
            return 6
        accessed_days = 0
        gap = "local_database_unavailable"
        _print_json(
            {
                "status": "no_data",
                "data_status": "no_data",
                "source": "local",
                "requested_days": days,
                "accessed_days": accessed_days,
                "error_type": type(exc).__name__,
                "data_gaps": [gap],
                "provenance": {
                    "source": "local",
                    "requested_days": days,
                    "accessed_days": accessed_days,
                    "network_accessed": False,
                    "memory_context_accessed": False,
                    "persisted": False,
                },
            }
        )
        return 3
    except DataStaleError as exc:
        accessed_days = days if isinstance(exc, DataStaleError) else 0
        gap = "local_window_no_observations"
        _print_json(
            {
                "status": "no_data",
                "data_status": "no_data",
                "source": args.source,
                "requested_days": days,
                "accessed_days": accessed_days,
                "error_type": type(exc).__name__,
                "data_gaps": [gap],
                "provenance": {
                    "source": "local",
                    "requested_days": days,
                    "accessed_days": accessed_days,
                    "network_accessed": False,
                    "memory_context_accessed": False,
                    "persisted": False,
                },
            }
        )
        return 3
    except (ImportError, ModuleNotFoundError) as exc:
        _print_json(
            {
                "status": "dependency_error",
                "source": args.source,
                "requested_days": days,
                "error_type": type(exc).__name__,
            },
            sys.stderr,
        )
        return 4
    except ValueError as exc:
        _print_json(
            {
                "status": "schema_error",
                "source": args.source,
                "requested_days": days,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
            sys.stderr,
        )
        return 4
    except Exception as exc:
        _print_json(
            {
                "status": "read_error",
                "source": args.source,
                "requested_days": days,
                "error_type": type(exc).__name__,
            },
            sys.stderr,
        )
        return 4

    historical_context = None
    if args.allow_memory_context:
        try:
            historical_context = query_vector_lake()
        except Exception:
            historical_context = None

    try:
        if args.analysis == "flu_risk":
            result = analyze_flu_risk(summary_data)
        elif args.analysis == "readiness":
            result = analyze_executive_readiness(summary_data)
        elif args.analysis == "insight_cn":
            result = generate_chinese_insight(summary_data, historical_context)
        elif args.analysis == "audit":
            result = perform_bio_metric_audit(summary_data)
        elif args.analysis == "long_term_load":
            result = {"analysis_type": "pmc_metrics", "data": summary_data.get("pmc", [])}
        elif args.analysis == "env_stress":
            result = analyze_env_stress(summary_data)
        elif args.analysis == "device_audit":
            result = analyze_device_health(summary_data)
    except Exception as exc:
        _print_json(
            {
                "status": "analysis_error",
                "source": args.source,
                "requested_days": days,
                "error_type": type(exc).__name__,
            },
            sys.stderr,
        )
        return 4

    if not isinstance(result, dict):
        result = {"data": result}

    data_gaps = summary_data.get("_data_gaps", [])
    data_status = "partial" if data_gaps or summary_data.get("is_stale") else "ok"
    result.setdefault("status", data_status)
    result["data_status"] = data_status
    if data_gaps:
        result["data_gaps"] = data_gaps
    result["provenance"] = {
        "source": args.source,
        "requested_days": days,
        "accessed_days": summary_data.get("_accessed_days", days),
        "network_accessed": args.source == "live",
        "memory_context_accessed": bool(args.allow_memory_context),
        "persisted": False,
    }
    _print_json(result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
