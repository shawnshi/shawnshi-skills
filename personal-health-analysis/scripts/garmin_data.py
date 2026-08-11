#!/usr/bin/env python3
"""
@Input:  metric, bounded date options, --source local|live, and explicit health-data grants
@Output: JSON health metrics with coverage and component status
@Pos:    Local-first data layer; live Garmin access is explicit and fail-closed.

!!! Maintenance Protocol: If API endpoints change, update this. Keep JSON structure stable for consumers.

Read explicitly authorized local Garmin data by default. Every health-data read requires
--allow-health-data. Live Garmin Connect access also requires --source live,
--allow-network, and an explicit window.
"""

import argparse
import concurrent.futures
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from garmin_auth import get_client
from garmin_capabilities import consume_capability, issue_capability


SUMMARY_MAX_WORKERS = 1
LIVE_DATA_OPERATION = "health_data_live"
LIVE_SUMMARY_COMPONENTS = (
    "sleep",
    "hrv",
    "body_battery",
    "heart_rate",
    "activities",
    "stress",
    "training_load_series",
)
LIVE_SUMMARY_OMITTED_COMPONENTS = (
    "training_status",
    "max_metrics",
    "hydration",
    "body_composition",
    "alarms",
)
LOCAL_OBSERVATION_FIELDS = {
    "sleep": (
        "sleep_time_seconds",
        "deep_sleep_seconds",
        "light_sleep_seconds",
        "rem_sleep_seconds",
        "sleep_score",
        "avg_respiration",
        "avg_spo2",
    ),
    "hrv": ("last_night_avg",),
    "heart_rate": ("resting_hr", "max_hr"),
    "body_battery": ("highest", "lowest", "charged"),
    "stress": ("avg_stress",),
    "activities": (
        "activity_id",
        "distance",
        "duration",
        "calories",
        "training_load",
    ),
}

def get_date_range(days=None, start=None, end=None):
    """Return an inclusive, validated range containing exactly ``days`` dates."""
    if bool(start) != bool(end):
        raise ValueError("--start and --end must be supplied together")
    if start and end:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Dates must use YYYY-MM-DD") from exc
        if start_date > end_date:
            raise ValueError("--start must not be later than --end")
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    requested_days = 7 if days is None else days
    if (
        not isinstance(requested_days, int)
        or isinstance(requested_days, bool)
        or requested_days < 1
    ):
        raise ValueError("--days must be a positive integer")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=requested_days - 1)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

class LiveRequestError(RuntimeError):
    """Stable, non-sensitive live request failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_live_failure(exc: BaseException) -> dict[str, str]:
    return {
        "error": getattr(exc, "code", "live_request_failed"),
        "error_type": type(exc).__name__,
    }


def fetch_with_retry(func, *args, max_retries=0, base_delay=0, **kwargs):
    """Execute once; rate limits are terminal so the caller can stop safely."""
    del max_retries, base_delay
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        message = str(exc).casefold()
        code = "rate_limited" if "too many requests" in message or "429" in message else "live_request_failed"
        raise LiveRequestError(code) from exc


def _map_with_workers(worker, items, max_workers=5):
    """Map a daily fetch with a bounded pool, or inline when already orchestrated."""
    items = list(items)
    if max_workers <= 1 or len(items) <= 1:
        return [worker(item) for item in items]
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max_workers, len(items))
    ) as executor:
        return list(executor.map(worker, items))


def fetch_sleep(client, days=7, start=None, end=None, max_workers=5):
    """Fetch sleep data concurrently."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        sleep_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_sleep_data, date_str)
            if data:
                sleep_dto = data.get("dailySleepDTO", {})
                if sleep_dto:
                    return {
                        "date": date_str,
                        "sleep_time_seconds": sleep_dto.get("sleepTimeSeconds"),
                        "deep_sleep_seconds": sleep_dto.get("deepSleepSeconds"),
                        "light_sleep_seconds": sleep_dto.get("lightSleepSeconds"),
                        "rem_sleep_seconds": sleep_dto.get("remSleepSeconds"),
                        "awake_seconds": sleep_dto.get("awakeSleepSeconds"),
                        "sleep_score": sleep_dto.get("sleepScores", {}).get("overall", {}).get("value"),
                        "restless_periods": data.get("restlessMomentsCount"),
                        "avg_hr": sleep_dto.get("averageHeartRate"),
                        "avg_hrv": data.get("avgOvernightHrv"),
                        "avg_respiration": sleep_dto.get("averageRespirationValue"),
                        "avg_spo2": sleep_dto.get("averageSpO2Value"),
                    }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        sleep_data = [r for r in results if r]
            
        sleep_data.sort(key=lambda x: x["date"])
        return {"sleep": sleep_data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_hrv(client, days=7, start=None, end=None, max_workers=5):
    """Fetch HRV data concurrently."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        hrv_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_hrv_data, date_str)
            if data and "hrvSummary" in data:
                summary = data["hrvSummary"]
                return {
                    "date": date_str,
                    "last_night_avg": summary.get("lastNightAvg"),
                    "last_night_5min_high": summary.get("lastNight5MinHigh"),
                    "last_night_5min_low": summary.get("lastNight5MinLow"),
                    "weekly_avg": summary.get("weeklyAvg"),
                    "baseline_balanced_low": summary.get("baselineBalancedLow"),
                    "baseline_balanced_high": summary.get("baselineBalancedHigh"),
                    "status": summary.get("status")
                }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        hrv_data = [r for r in results if r]

        hrv_data.sort(key=lambda x: x["date"])
        return {"hrv": hrv_data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_body_battery(client, days=7, start=None, end=None, max_workers=5):
    """Fetch Body Battery data concurrently."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        bb_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_body_battery, date_str)
            if data and len(data) > 0:
                day_data = data[0]
                values_array = day_data.get("bodyBatteryValuesArray", [])
                values = [v[1] for v in values_array if len(v) > 1]
                return {
                    "date": date_str,
                    "charged": day_data.get("charged"),
                    "drained": day_data.get("drained"),
                    "highest": max(values) if values else None,
                    "lowest": min(values) if values else None
                }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        bb_data = [r for r in results if r]

        bb_data.sort(key=lambda x: x["date"])
        return {"body_battery": bb_data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_heart_rate(client, days=7, start=None, end=None, max_workers=5):
    """Fetch heart rate data concurrently."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        hr_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_heart_rates, date_str)
            if data:
                return {
                    "date": date_str,
                    "resting_hr": data.get("restingHeartRate"),
                    "max_hr": data.get("maxHeartRate"),
                    "min_hr": data.get("minHeartRate")
                }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        hr_data = [r for r in results if r]

        hr_data.sort(key=lambda x: x["date"])
        return {"heart_rate": hr_data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_activities(client, days=7, start=None, end=None):
    """Fetch activities/workouts."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        activities = fetch_with_retry(client.get_activities_by_date, start_date, end_date, "")
        if not activities:
            activities = []
        
        activity_list = []
        for activity in activities:
            activity_list.append({
                "date": activity.get("startTimeLocal", "").split(" ")[0],
                "activity_type": activity.get("activityType", {}).get("typeKey"),
                "activity_name": activity.get("activityName"),
                "duration_seconds": activity.get("duration"),
                "distance_meters": activity.get("distance"),
                "calories": activity.get("calories"),
                "avg_hr": activity.get("averageHR"),
                "max_hr": activity.get("maxHR"),
                "elevation_gain": activity.get("elevationGain"),
                "avg_speed": activity.get("averageSpeed")
            })
        
        return {"activities": activity_list, "start": start_date, "end": end_date, "count": len(activity_list)}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_stress(client, days=7, start=None, end=None, max_workers=5):
    """Fetch only the daily stress endpoint for the requested dates."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        stress_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_stress_data, date_str)
            if data:
                return {
                    "date": date_str,
                    "avg_stress": data.get("averageStressLevel"),
                    "max_stress": data.get("maxStressLevel"),
                    "rest_stress_duration": data.get("restStressDuration"),
                    "low_stress_duration": data.get("lowStressDuration"),
                    "medium_stress_duration": data.get("mediumStressDuration"),
                    "high_stress_duration": data.get("highStressDuration"),
                }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        stress_data = [r for r in results if r]

        stress_data.sort(key=lambda x: x["date"])
        return {"stress": stress_data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_live_failure(e)


def fetch_training_load_series(client, days=7, start=None, end=None, max_workers=5):
    """Fetch acute training load series concurrently."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        load_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            data = fetch_with_retry(client.get_training_status, date_str)
            if data:
                recent = data.get("mostRecentTrainingStatus", {})
                status_data = recent.get("latestTrainingStatusData", {})
                if status_data:
                    entry = list(status_data.values())[0]
                    return {
                        "date": date_str,
                        "acute_load": entry.get("acuteTrainingLoadDTO", {}).get("acuteTrainingLoad"),
                        "load_ratio": entry.get("acuteTrainingLoadDTO", {}).get("dailyAcuteChronicWorkloadRatio")
                    }
            return None

        results = _map_with_workers(_get_single_day, dates, max_workers)
        load_data = [r for r in results if r]

        load_data.sort(key=lambda x: x["date"])
        return {"training_load": load_data}
    except Exception as exc:
        return _safe_live_failure(exc)


def fetch_training_status(client, date_str=None):
    """Fetch training status and load ratio."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = fetch_with_retry(client.get_training_status, date_str)
        if data:
            recent_status = data.get("mostRecentTrainingStatus", {})
            status_data_map = recent_status.get("latestTrainingStatusData", {})
            
            status_entry = {}
            if status_data_map:
                status_entry = list(status_data_map.values())[0]
            
            acute_chronic_ratio = status_entry.get("acuteTrainingLoadDTO", {}).get("dailyAcuteChronicWorkloadRatio", "--")
            
            vo2_max = "--"
            recent_vo2 = data.get("mostRecentVO2Max", {})
            if recent_vo2:
                vo2_max = recent_vo2.get("generic", {}).get("vo2MaxValue", "--")

            return {
                "date": date_str,
                "status": status_entry.get("trainingStatusFeedbackPhrase", "无数据"),
                "load_ratio": acute_chronic_ratio,
                "load_status": status_entry.get("acwrStatusFeedback", "无数据"),
                "vo2_max": vo2_max
            }
        return {}
    except Exception:
        return {}


def fetch_max_metrics(client, date_str=None):
    """Fetch Fitness Age and VO2 Max with a 7-day look-back."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    # Try last 7 days to find latest fitness age
    try:
        end_dt = datetime.strptime(date_str, "%Y-%m-%d")
        for i in range(7):
            target_date = (end_dt - timedelta(days=i)).strftime("%Y-%m-%d")
            fa_data = fetch_with_retry(client.get_fitnessage_data, target_date)
            if fa_data and fa_data.get("fitnessAge"):
                return {"fitness_age": round(fa_data.get("fitnessAge"), 1)}
        return {"fitness_age": "--"}
    except Exception:
        return {"fitness_age": "--"}

def fetch_hydration(client, date_str=None):
    """Fetch hydration/water intake data for the specified date."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        data = fetch_with_retry(client.get_hydration_data, date_str)
        if data:
            return {"date": date_str, "valueInML": data.get("valueInML")}
        return {}
    except Exception:
        return {}

def fetch_alarms(client):
    """Fetch alarms from all connected devices."""
    alarms = []
    try:
        devices = fetch_with_retry(client.get_devices)
        if devices:
            for device in devices:
                device_id = device.get("deviceId")
                if device_id:
                    device_alarms = fetch_with_retry(client.get_device_alarms, device_id)
                    if device_alarms:
                        alarms.extend(device_alarms)
    except Exception as e:
        print(f"⚠️ Could not fetch alarms: {e}", file=sys.stderr)
    return alarms

def fetch_body_composition(client, date_str=None):
    """Fetch body-composition data without inventing missing anthropometrics."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        # Height may come from the authorized Garmin profile or an explicit
        # user-provided local configuration. Never substitute a population
        # average: doing so would turn missing data into a fabricated BMI.
        height_cm = None
        height_source = None
        profile = fetch_with_retry(client.get_user_profile)
        if profile:
            height_cm = profile.get("height")
            if height_cm:
                height_source = "garmin_profile"
            
        # Check for local config override if API height is missing
        config_path = Path(__file__).parent.parent / "config.json"
        if (not height_cm or height_cm == 0) and config_path.exists():
            try:
                conf = json.loads(config_path.read_text(encoding='utf-8'))
                height_cm = conf.get("height_cm")
                if height_cm:
                    height_source = "user_config"
            except Exception:
                pass
        
        # 2. Fetch last 30 days to get the most recent weigh-in
        end_dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = (end_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        
        data = fetch_with_retry(client.get_body_composition, start_date, date_str)
        if data and "dateWeightList" in data and len(data["dateWeightList"]) > 0:
            latest = data["dateWeightList"][-1]
            weight_grams = latest.get("weight")
            weight_kg = (
                weight_grams / 1000
                if isinstance(weight_grams, (int, float))
                and not isinstance(weight_grams, bool)
                else None
            )
            bmi = latest.get("bmi")
            
            # Recalculate only when both measured weight and an authorized
            # height are available.
            if (
                (not bmi or bmi == 0)
                and height_cm
                and weight_kg is not None
                and weight_kg > 0
            ):
                bmi = weight_kg / ((height_cm / 100) ** 2)

            data_gaps = []
            if weight_kg is None:
                data_gaps.append("Weight unavailable because Garmin did not provide a measured weight")
            if not bmi:
                data_gaps.append(
                    "BMI unavailable because Garmin did not provide BMI and the required measured weight and authorized height were not both available"
                )

            return {
                "weight": round(weight_kg, 1) if weight_kg is not None else None,
                "bmi": round(bmi, 1) if bmi else "--",
                "fat_pct": round(latest.get("bodyFat", 0), 1) if latest.get("bodyFat") else "--",
                "date": latest.get("date"),
                "source_height": height_cm,
                "height_source": height_source,
                "data_gaps": data_gaps,
            }
        return {}
    except Exception:
        return {}

def _normalize_live_summary_components(components=None):
    if components is None:
        return LIVE_SUMMARY_COMPONENTS
    if not isinstance(components, (list, tuple)) or not components:
        raise ValueError("live_summary_components_required")
    if any(not isinstance(item, str) for item in components):
        raise ValueError("live_summary_component_invalid")
    if len(set(components)) != len(components):
        raise ValueError("live_summary_component_duplicate")
    unknown = set(components) - set(LIVE_SUMMARY_COMPONENTS)
    if unknown:
        raise ValueError("live_summary_component_invalid")
    return tuple(item for item in LIVE_SUMMARY_COMPONENTS if item in components)


def fetch_summary(client, days=7, start=None, end=None, *, components=None):
    """Fetch the fixed, window-bounded live-summary component set.

    Profile, device, alarm, body-composition and look-back endpoints are
    intentionally excluded.  Callers bind ``LIVE_SUMMARY_COMPONENTS`` and the
    exact date range into both live capabilities before invoking this function.
    """
    start_date, end_date = get_date_range(days, start, end)
    selected_components = _normalize_live_summary_components(components)
    
    try:
        # Execute components serially.  This deliberately trades latency for a
        # strict stop boundary: after a 429 no later component can begin.
        task_specs = {
            "sleep": (
                lambda: fetch_sleep(client, None, start_date, end_date, max_workers=1),
                "sleep",
                [],
            ),
            "hrv": (
                lambda: fetch_hrv(client, None, start_date, end_date, max_workers=1),
                "hrv",
                [],
            ),
            "body_battery": (
                lambda: fetch_body_battery(
                    client, None, start_date, end_date, max_workers=1
                ),
                "body_battery",
                [],
            ),
            "heart_rate": (
                lambda: fetch_heart_rate(
                    client, None, start_date, end_date, max_workers=1
                ),
                "heart_rate",
                [],
            ),
            "activities": (
                lambda: fetch_activities(client, None, start_date, end_date),
                "activities",
                [],
            ),
            "stress": (
                lambda: fetch_stress(client, None, start_date, end_date, max_workers=1),
                "stress",
                [],
            ),
            "training_load_series": (
                lambda: fetch_training_load_series(
                    client, None, start_date, end_date, max_workers=1
                ),
                "training_load",
                [],
            ),
        }
        task_specs = {
            name: spec
            for name, spec in task_specs.items()
            if name in selected_components
        }

        requested_days = (
            datetime.strptime(end_date, "%Y-%m-%d")
            - datetime.strptime(start_date, "%Y-%m-%d")
        ).days + 1
        component_results = {name: [] for name in LIVE_SUMMARY_COMPONENTS}
        component_status = {
            name: {
                "status": "not_requested",
                "observed_days": 0,
                "observed_records": 0,
            }
            for name in LIVE_SUMMARY_COMPONENTS
        }
        for name, (task, result_key, default) in task_specs.items():
            try:
                raw_result = task()
                if isinstance(raw_result, dict) and raw_result.get("error"):
                    if raw_result["error"] == "rate_limited":
                        raise LiveRequestError("rate_limited")
                    component_results[name] = default
                    component_status[name] = {
                        "status": "error",
                        "observed_days": 0,
                        "observed_records": 0,
                    }
                    continue
                component_results[name] = (
                    raw_result.get(result_key, default)
                    if result_key and isinstance(raw_result, dict)
                    else raw_result if raw_result is not None else default
                )
                value = component_results[name]
                if isinstance(value, list):
                    observed_dates = {
                        item.get("date")
                        for item in value
                        if isinstance(item, dict) and item.get("date")
                    }
                    observed_records = len(value)
                    status = (
                        "no_data"
                        if observed_records == 0
                        else "complete"
                        if len(observed_dates) >= requested_days
                        else "partial"
                    )
                    component_status[name] = {
                        "status": status,
                        "observed_days": len(observed_dates),
                        "observed_records": observed_records,
                    }
                else:
                    available = value not in (None, {}, [])
                    component_status[name] = {
                        "status": "available" if available else "no_data",
                        "observed_days": 1 if available else 0,
                        "observed_records": 1 if available else 0,
                    }
            except LiveRequestError:
                raise
            except Exception as exc:
                print(
                    f"⚠️ Summary component '{name}' failed ({type(exc).__name__}).",
                    file=sys.stderr,
                )
                component_results[name] = default
                component_status[name] = {
                    "status": "error",
                    "observed_days": 0,
                    "observed_records": 0,
                }

        sleep = component_results["sleep"]
        hrv = component_results["hrv"]
        bb = component_results["body_battery"]
        hr = component_results["heart_rate"]
        activities = component_results["activities"]
        stress = component_results["stress"]
        training_load_series = component_results["training_load_series"]
        
        # Calculate averages (handle None values)
        sleep_times = [s.get("sleep_time_seconds") for s in sleep if s.get("sleep_time_seconds")]
        avg_sleep_hours = (sum(sleep_times) / len(sleep_times) / 3600) if sleep_times else None
        
        sleep_scores = [s.get("sleep_score") for s in sleep if s.get("sleep_score") is not None]
        avg_sleep_score = (sum(sleep_scores) / len(sleep_scores)) if sleep_scores else None
        
        hrv_values = [h.get("last_night_avg") for h in hrv if h.get("last_night_avg") is not None]
        avg_hrv = (sum(hrv_values) / len(hrv_values)) if hrv_values else None
        
        rhr_values = [h.get("resting_hr") for h in hr if h.get("resting_hr") is not None]
        avg_rhr = (sum(rhr_values) / len(rhr_values)) if rhr_values else None
        
        bb_charged_values = [b.get("charged") for b in bb if b.get("charged") is not None]
        avg_bb_charged = (sum(bb_charged_values) / len(bb_charged_values)) if bb_charged_values else None

        def _rounded(value):
            return round(value, 1) if value is not None else None

        activities_observed = component_status["activities"]["status"] in {
            "partial",
            "complete",
        }
        calories_observed = activities_observed and all(
            isinstance(activity, dict)
            and activity.get("calories") is not None
            and isinstance(activity.get("calories"), (int, float))
            and not isinstance(activity.get("calories"), bool)
            for activity in activities
        )
        total_activities = len(activities) if activities_observed else None
        total_calories = (
            sum(activity["calories"] for activity in activities)
            if calories_observed
            else None
        )
        
        return {
            "summary": {
                "period": f"{start_date} to {end_date}",
                "days": requested_days,
                "avg_sleep_hours": _rounded(avg_sleep_hours),
                "avg_sleep_score": _rounded(avg_sleep_score),
                "avg_hrv_ms": _rounded(avg_hrv),
                "avg_resting_hr": _rounded(avg_rhr),
                "avg_body_battery_charged": _rounded(avg_bb_charged),
                "total_activities": total_activities,
                "total_calories": total_calories,
            },
            "sleep": sleep,
            "hrv": hrv,
            "body_battery": bb,
            "heart_rate": hr,
            "activities": activities,
            "stress": stress,
            "training_load_series": training_load_series,
            # Compatibility placeholders are retained for local consumers, but
            # no live endpoint is called for these omitted components.
            "training_status": {},
            "max_metrics": {},
            "hydration": {},
            "body_composition": {},
            "alarms": [],
            "authorized_scope": {
                "start": start_date,
                "end": end_date,
                "components": list(selected_components),
                "omitted_components": [
                    *(
                        name
                        for name in LIVE_SUMMARY_COMPONENTS
                        if name not in selected_components
                    ),
                    *LIVE_SUMMARY_OMITTED_COMPONENTS,
                ],
            },
            "coverage": {
                "start": start_date,
                "end": end_date,
                "requested_days": requested_days,
                "components": component_status,
            },
            "component_status": component_status,
        }
    
    except Exception as e:
        return _safe_live_failure(e)


def fetch_profile(client):
    """Fetch only the explicitly declared full-name profile field."""
    try:
        profile = fetch_with_retry(client.get_full_name)
        return {
            "profile": {
                "name": profile,
            },
            "authorized_scope": {"fields": ["full_name"]},
        }
    
    except Exception as e:
        return _safe_live_failure(e)


def _frame_records(frame):
    """Convert a local pandas frame to JSON-safe records without filling gaps."""
    if frame is None or frame.empty:
        return []
    clean = frame.astype(object).where(frame.notna(), None)
    return clean.to_dict("records")


def _local_component_coverage(name, records, requested_days):
    fields = LOCAL_OBSERVATION_FIELDS[name]
    observed_records = [
        item
        for item in records
        if isinstance(item, dict)
        and any(item.get(field) is not None for field in fields)
    ]
    observed_dates = {
        item.get("date") for item in observed_records if item.get("date")
    }
    observed_days = len(observed_dates)
    if not observed_records:
        status = "no_data"
    elif observed_days >= requested_days:
        status = "complete"
    else:
        status = "partial"
    return {
        "status": status,
        "observed_days": observed_days,
        "observed_records": len(observed_records),
    }


def _local_metric_result(name, records, requested_days):
    coverage = _local_component_coverage(name, records, requested_days)
    return {
        name: records,
        "source": "local",
        "status": coverage["status"],
        "coverage": {"requested_days": requested_days, **coverage},
    }


def _fetch_local_metric(metric, days=7, start=None, end=None, *, _verified=False):
    """Fetch supported metrics from the local read-only Garmin SQLite adapter."""
    if start or end:
        raise ValueError("Explicit --start/--end ranges are not supported by the local adapter")
    from garmin_sqlite_adapter import (
        ACTIVITIES_DB,
        GARMIN_DB,
        get_activities_data,
        get_hrv_data,
        get_sleep_data,
        get_summary,
        verified_database_read_window,
    )

    if not _verified:
        database_paths = (
            [GARMIN_DB, ACTIVITIES_DB]
            if metric == "summary"
            else [ACTIVITIES_DB]
            if metric == "activities"
            else [GARMIN_DB]
        )
        window = verified_database_read_window(database_paths)
        with window:
            result = _fetch_local_metric(
                metric,
                days,
                start,
                end,
                _verified=True,
            )
        result["data_integrity"] = window.public_summary()
        return result

    if metric == "profile":
        raise ValueError("profile is available only from explicitly authorized live access")
    if metric == "sleep":
        return _local_metric_result("sleep", _frame_records(get_sleep_data(days)), days)
    if metric == "hrv":
        frame = get_hrv_data(days).rename(columns={"hrv_avg": "last_night_avg"})
        return _local_metric_result("hrv", _frame_records(frame), days)
    if metric == "activities":
        return _local_metric_result(
            "activities", _frame_records(get_activities_data(days)), days
        )

    summary_frame = get_summary(days)
    mappings = {
        "heart_rate": {
            "resting_heart_rate": "resting_hr",
        },
        "body_battery": {
            "body_battery_highest": "highest",
            "body_battery_lowest": "lowest",
            "body_battery_charged": "charged",
        },
        "stress": {"stress_avg": "avg_stress"},
    }
    if metric in mappings:
        records = _frame_records(summary_frame.rename(columns=mappings[metric]))
        return _local_metric_result(metric, records, days)
    if metric != "summary":
        raise ValueError(f"Metric '{metric}' is not supported by the local adapter")

    sleep = _fetch_local_metric("sleep", days, _verified=True)["sleep"]
    hrv = _fetch_local_metric("hrv", days, _verified=True)["hrv"]
    heart_rate = _fetch_local_metric("heart_rate", days, _verified=True)["heart_rate"]
    body_battery = _fetch_local_metric("body_battery", days, _verified=True)["body_battery"]
    stress = _fetch_local_metric("stress", days, _verified=True)["stress"]
    activities = _fetch_local_metric("activities", days, _verified=True)["activities"]
    components = {
        "sleep": sleep,
        "hrv": hrv,
        "heart_rate": heart_rate,
        "body_battery": body_battery,
        "stress": stress,
        "activities": activities,
    }
    status = {
        name: _local_component_coverage(name, records, days)
        for name, records in components.items()
    }
    component_states = {item["status"] for item in status.values()}
    if component_states == {"complete"}:
        summary_status = "complete"
    elif component_states == {"no_data"}:
        summary_status = "no_data"
    else:
        summary_status = "partial"
    return {
        **components,
        "daily_summary": _frame_records(summary_frame),
        "source": "local",
        "status": summary_status,
        "coverage": {"requested_days": days, "components": status},
        "component_status": status,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin health data")
    parser.add_argument("metric", choices=["sleep", "hrv", "body_battery", "heart_rate", "activities", "stress", "summary", "profile"],
                       help="Type of data to fetch")
    parser.add_argument("--days", type=int, help="Explicit live window; local defaults to 7")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument("--source", choices=["local", "live"], default="local")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize live Garmin network access for this invocation",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize reading health data for the exact metric and window",
    )
    
    args = parser.parse_args()
    
    try:
        if args.days is not None and (args.start or args.end):
            raise ValueError("--days cannot be combined with --start/--end")
        effective_days = 7 if args.source == "local" and args.days is None else args.days
        start_date, end_date = get_date_range(effective_days, args.start, args.end)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

    if args.source == "local" and not args.allow_health_data:
        print(json.dumps({"status": "health_data_authorization_required"}))
        return 2

    if args.source == "local":
        try:
            result = _fetch_local_metric(
                args.metric, effective_days, args.start, args.end
            )
        except Exception as exc:
            error_code = "local_data_unavailable"
            if type(exc).__name__ == "LocalDatabaseChangedError":
                error_code = "database_changed_during_read"
            elif (
                type(exc).__name__ == "LocalDatabaseReadError"
                and re.fullmatch(r"[a-z0-9_]+", str(exc) or "")
            ):
                error_code = str(exc)
            print(
                json.dumps(
                    {"status": "read_error", "error_code": error_code},
                    ensure_ascii=False,
                )
            )
            return 1
    else:
        if not args.allow_network:
            print(json.dumps({"status": "network_authorization_required"}))
            return 2
        if not args.allow_health_data:
            print(json.dumps({"status": "health_data_authorization_required"}))
            return 2
        if args.days is None and not (args.start and args.end):
            print(json.dumps({"status": "explicit_live_window_required"}))
            return 2
        request = {
            "metric": args.metric,
            "source": "live",
            "start": start_date,
            "end": end_date,
        }
        if args.metric == "summary":
            request["components"] = list(LIVE_SUMMARY_COMPONENTS)
        elif args.metric == "profile":
            request["fields"] = ["full_name"]
        network_capability = issue_capability(
            scope="network",
            operation=LIVE_DATA_OPERATION,
            request=request,
        )
        health_data_capability = issue_capability(
            scope="health_data",
            operation=LIVE_DATA_OPERATION,
            request=request,
        )
        client = get_client(
            network_capability=network_capability,
            operation=LIVE_DATA_OPERATION,
            request=request,
        )
        if not client:
            print('{"error": "Live Garmin authentication failed"}')
            return 1
        consume_capability(
            health_data_capability,
            scope="health_data",
            operation=LIVE_DATA_OPERATION,
            request=request,
        )
        fetchers = {
            "sleep": fetch_sleep,
            "hrv": fetch_hrv,
            "body_battery": fetch_body_battery,
            "heart_rate": fetch_heart_rate,
            "activities": fetch_activities,
            "stress": fetch_stress,
            "summary": fetch_summary,
        }
        if args.metric == "profile":
            result = fetch_profile(client)
        elif args.metric == "summary":
            result = fetch_summary(
                client,
                args.days,
                args.start,
                args.end,
                components=request["components"],
            )
        else:
            result = fetchers[args.metric](
                client, args.days, args.start, args.end
            )
    
    if args.source == "live" and isinstance(result, dict) and result.get("error"):
        print(json.dumps(result, ensure_ascii=False))
        return 1

    # Output JSON
    # This CLI intentionally returns user-authorized health metrics to its local caller.
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
