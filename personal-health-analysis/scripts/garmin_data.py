#!/usr/bin/env python3
"""
@Input:  --metric (sleep, hrv, etc.), --days, --start, --end
@Output: JSON Stream (Standardized Health Metrics)
@Pos:    Domain Data Layer. Fetches raw data from Garmin API.

!!! Maintenance Protocol: If API endpoints change, update this. Keep JSON structure stable for consumers.

Fetch health data from Garmin Connect.
Outputs JSON to stdout for parsing by the agent.
"""

import json
import sys
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
import concurrent.futures

# Import auth helper
sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client

try:
    from garminconnect import Garmin
except ImportError:
    print('{"error": "garminconnect not installed. Run: pip3 install garminconnect"}', file=sys.stderr)
    sys.exit(1)


def get_date_range(days=None, start=None, end=None):
    """Calculate date range for queries."""
    if start and end:
        return start, end
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days or 7)
    
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

def fetch_with_retry(func, *args, max_retries=3, base_delay=2, **kwargs):
    """Execute a Garmin API call with exponential backoff to handle rate limits (HTTP 429)."""
    retries = 0
    while retries <= max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "too many requests" in error_str or "429" in error_str:
                if retries == max_retries:
                    print(f"⚠️ Rate limit exceeded after {max_retries} retries for {func.__name__}", file=sys.stderr)
                    return None
                delay = base_delay * (2 ** retries)
                print(f"⏳ Rate limited. Backing off for {delay} seconds...", file=sys.stderr)
                time.sleep(delay)
                retries += 1
            else:
                # Other exceptions
                return None
    return None

def fetch_sleep(client, days=7, start=None, end=None):
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
                        "avg_respiration": sleep_dto.get("averageRespirationValue")
                    }
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            sleep_data = [r for r in results if r]
            
        sleep_data.sort(key=lambda x: x["date"])
        return {"sleep": sleep_data, "start": start_date, "end": end_date}
    except Exception as e:
        return {"error": str(e)}


def fetch_hrv(client, days=7, start=None, end=None):
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            hrv_data = [r for r in results if r]

        hrv_data.sort(key=lambda x: x["date"])
        return {"hrv": hrv_data, "start": start_date, "end": end_date}
    except Exception as e:
        return {"error": str(e)}


def fetch_body_battery(client, days=7, start=None, end=None):
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            bb_data = [r for r in results if r]

        bb_data.sort(key=lambda x: x["date"])
        return {"body_battery": bb_data, "start": start_date, "end": end_date}
    except Exception as e:
        return {"error": str(e)}


def fetch_heart_rate(client, days=7, start=None, end=None):
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            hr_data = [r for r in results if r]

        hr_data.sort(key=lambda x: x["date"])
        return {"heart_rate": hr_data, "start": start_date, "end": end_date}
    except Exception as e:
        return {"error": str(e)}


def fetch_activities(client, days=7, start=None, end=None):
    """Fetch activities/workouts."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        activities = fetch_with_retry(client.get_activities_by_date, start_date, end_date, "")
        if not activities: activities = []
        
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
        return {"error": str(e)}


def fetch_stress(client, days=7, start=None, end=None):
    """Fetch stress levels concurrently using user summary for accurate durations."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        stress_data = []
        current = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        dates = [(current + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_dt - current).days + 1)]
        
        def _get_single_day(date_str):
            # Using get_user_summary as it contains pre-calculated durations
            data = fetch_with_retry(client.get_user_summary, date_str)
            if data:
                return {
                    "date": date_str,
                    "avg_stress": data.get("averageStressLevel"),
                    "max_stress": data.get("maxStressLevel"),
                    "rest_stress_duration": data.get("restStressDuration"),
                    "low_stress_duration": data.get("lowStressDuration"),
                    "medium_stress_duration": data.get("mediumStressDuration"),
                    "high_stress_duration": data.get("highStressDuration"),
                    "steps": data.get("totalSteps")
                }
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            stress_data = [r for r in results if r]

        stress_data.sort(key=lambda x: x["date"])
        return {"stress": stress_data, "start": start_date, "end": end_date}
    except Exception as e:
        return {"error": str(e)}


def fetch_training_load_series(client, days=7, start=None, end=None):
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(_get_single_day, dates)
            load_data = [r for r in results if r]

        load_data.sort(key=lambda x: x["date"])
        return {"training_load": load_data}
    except Exception:
        return {"training_load": []}


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
            return {"date": date_str, "valueInML": data.get("valueInML", 0)}
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
    """Fetch BMI and weight data with a 30-day look-back and robust height fallback."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        # 1. Height Logic: Try Profile -> then Try Config -> then Hard Fallback
        height_cm = None
        profile = fetch_with_retry(client.get_user_profile)
        if profile:
            height_cm = profile.get("height")
            
        # Check for local config override if API height is missing
        config_path = Path(__file__).parent.parent / "config.json"
        if (not height_cm or height_cm == 0) and config_path.exists():
            try:
                conf = json.loads(config_path.read_text(encoding='utf-8'))
                height_cm = conf.get("height_cm")
            except Exception:
                pass
        
        # Hard Fallback (Mentat Estimate) to avoid empty display if all else fails
        if not height_cm or height_cm == 0:
            height_cm = 175 # Standard baseline for calculation
        
        # 2. Fetch last 30 days to get the most recent weigh-in
        end_dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = (end_dt - timedelta(days=30)).strftime("%Y-%m-%d")
        
        data = fetch_with_retry(client.get_body_composition, start_date, date_str)
        if data and "dateWeightList" in data and len(data["dateWeightList"]) > 0:
            latest = data["dateWeightList"][-1]
            weight_kg = latest.get("weight", 0) / 1000
            bmi = latest.get("bmi")
            
            # 3. Calculation Logic: Force recalculation if API BMI is None or inaccurate
            if (not bmi or bmi == 0) and height_cm and weight_kg > 0:
                bmi = weight_kg / ((height_cm / 100) ** 2)
                
            return {
                "weight": round(weight_kg, 1),
                "bmi": round(bmi, 1) if bmi else "--",
                "fat_pct": round(latest.get("bodyFat", 0), 1) if latest.get("bodyFat") else "--",
                "date": latest.get("date"),
                "source_height": height_cm
            }
        return {}
    except Exception:
        return {}

def fetch_summary(client, days=7, start=None, end=None):
    """Fetch combined summary with key metrics."""
    start_date, end_date = get_date_range(days, start, end)
    
    try:
        # Fetch multiple data types
        sleep = fetch_sleep(client, days, start, end).get("sleep", [])
        hrv = fetch_hrv(client, days, start, end).get("hrv", [])
        bb = fetch_body_battery(client, days, start, end).get("body_battery", [])
        hr = fetch_heart_rate(client, days, start, end).get("heart_rate", [])
        activities = fetch_activities(client, days, start, end).get("activities", [])
        stress = fetch_stress(client, days, start, end).get("stress", [])
        training_load_series = fetch_training_load_series(client, days, start, end).get("training_load", [])
        
        training_status = fetch_training_status(client, end_date)
        max_metrics = fetch_max_metrics(client, end_date)
        hydration = fetch_hydration(client, end_date)
        body_comp = fetch_body_composition(client, end_date)
        alarms = fetch_alarms(client)
        
        # Calculate averages (handle None values)
        sleep_times = [s.get("sleep_time_seconds") for s in sleep if s.get("sleep_time_seconds")]
        avg_sleep_hours = (sum(sleep_times) / len(sleep_times) / 3600) if sleep_times else 0
        
        sleep_scores = [s.get("sleep_score") for s in sleep if s.get("sleep_score") is not None]
        avg_sleep_score = (sum(sleep_scores) / len(sleep_scores)) if sleep_scores else 0
        
        hrv_values = [h.get("last_night_avg") for h in hrv if h.get("last_night_avg") is not None]
        avg_hrv = (sum(hrv_values) / len(hrv_values)) if hrv_values else 0
        
        rhr_values = [h.get("resting_hr") for h in hr if h.get("resting_hr") is not None]
        avg_rhr = (sum(rhr_values) / len(rhr_values)) if rhr_values else 0
        
        bb_charged_values = [b.get("charged") for b in bb if b.get("charged") is not None]
        avg_bb_charged = (sum(bb_charged_values) / len(bb_charged_values)) if bb_charged_values else 0
        
        return {
            "summary": {
                "period": f"{start_date} to {end_date}",
                "days": days,
                "avg_sleep_hours": round(avg_sleep_hours, 1),
                "avg_sleep_score": round(avg_sleep_score, 1),
                "avg_hrv_ms": round(avg_hrv, 1),
                "avg_resting_hr": round(avg_rhr, 1),
                "avg_body_battery_charged": round(avg_bb_charged, 1),
                "total_activities": len(activities),
                "total_calories": sum(a.get("calories", 0) for a in activities if a.get("calories"))
            },
            "sleep": sleep,
            "hrv": hrv,
            "body_battery": bb,
            "heart_rate": hr,
            "activities": activities,
            "stress": stress,
            "training_load_series": training_load_series,
            "training_status": training_status,
            "max_metrics": max_metrics,
            "hydration": hydration,
            "body_composition": body_comp,
            "alarms": alarms
        }
    
    except Exception as e:
        return {"error": str(e)}


def fetch_profile(client):
    """Fetch user profile."""
    try:
        profile = client.get_full_name()
        stats = client.get_user_summary(datetime.now().strftime("%Y-%m-%d"))
        
        return {
            "profile": {
                "name": profile,
                "display_name": stats.get("displayName"),
                "email": stats.get("email")
            }
        }
    
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Fetch Garmin health data")
    parser.add_argument("metric", choices=["sleep", "hrv", "body_battery", "heart_rate", "activities", "stress", "summary", "profile"],
                       help="Type of data to fetch")
    parser.add_argument("--days", type=int, default=7, help="Number of days to fetch (default: 7)")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    # Get authenticated client
    client = get_client()
    if not client:
        print('{"error": "Not authenticated. Run: python3 scripts/garmin_auth.py login --email YOUR_EMAIL --password YOUR_PASSWORD"}')
        sys.exit(1)
    
    # Fetch requested data
    if args.metric == "sleep":
        result = fetch_sleep(client, args.days, args.start, args.end)
    elif args.metric == "hrv":
        result = fetch_hrv(client, args.days, args.start, args.end)
    elif args.metric == "body_battery":
        result = fetch_body_battery(client, args.days, args.start, args.end)
    elif args.metric == "heart_rate":
        result = fetch_heart_rate(client, args.days, args.start, args.end)
    elif args.metric == "activities":
        result = fetch_activities(client, args.days, args.start, args.end)
    elif args.metric == "stress":
        result = fetch_stress(client, args.days, args.start, args.end)
    elif args.metric == "summary":
        result = fetch_summary(client, args.days, args.start, args.end)
    elif args.metric == "profile":
        result = fetch_profile(client)
    
    # Output JSON
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
