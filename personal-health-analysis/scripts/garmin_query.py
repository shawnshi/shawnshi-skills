#!/usr/bin/env python3
"""Query a live Garmin point only after explicit network authorization.

Results include requested/observed timestamps and reject samples outside the
configured tolerance.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).parent))
from garmin_capabilities import consume_capability, issue_capability
from garmin_auth import get_client


POINT_QUERY_OPERATION = "point_query_live"
MAX_TOLERANCE_SECONDS = 3600


def _timezone(timezone_name=None):
    if timezone_name:
        return ZoneInfo(timezone_name), timezone_name
    local = datetime.now().astimezone().tzinfo
    return local, str(local)


def parse_time(time_str, date_str=None, timezone_name=None):
    """Parse various time formats into datetime."""
    if not date_str:
        zone, _label = _timezone(timezone_name)
        date_str = datetime.now(zone).strftime("%Y-%m-%d")
    else:
        zone, _label = _timezone(timezone_name)
    
    # Try different formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%H:%M:%S",
        "%H:%M",
        "%I:%M %p",  # 3:00 PM
        "%I %p",     # 3 PM
    ]
    
    for fmt in formats:
        try:
            if "%Y" in fmt:
                naive = datetime.strptime(time_str, fmt)
            else:
                naive = datetime.strptime(
                    f"{date_str} {time_str}", f"%Y-%m-%d {fmt}"
                )
        except ValueError:
            continue
        candidates = []
        for fold in (0, 1):
            aware = naive.replace(tzinfo=zone, fold=fold)
            round_trip = (
                aware.astimezone(timezone.utc)
                .astimezone(zone)
                .replace(tzinfo=None)
            )
            if round_trip == naive:
                candidates.append(aware)
        if not candidates:
            raise ValueError("nonexistent_local_time")
        if len({candidate.utcoffset() for candidate in candidates}) > 1:
            raise ValueError("ambiguous_local_time")
        return candidates[0]
    
    raise ValueError(f"Could not parse time: {time_str}")


def _point_timestamp(item, timestamp_key="startTimeInSeconds"):
    if timestamp_key in item:
        timestamp = item[timestamp_key]
    elif "startGMT" in item:
        timestamp = item["startGMT"]
        if isinstance(timestamp, str):
            return int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())
    else:
        return None
    try:
        timestamp = float(timestamp)
    except (TypeError, ValueError):
        return None
    return int(timestamp / 1000) if timestamp > 10_000_000_000 else int(timestamp)


def find_closest_datapoint(
    target_time,
    data_array,
    timestamp_key="startTimeInSeconds",
    max_tolerance_seconds=300,
):
    """Find the closest data point to a target time."""
    if (
        max_tolerance_seconds is None
        or max_tolerance_seconds < 0
        or max_tolerance_seconds > MAX_TOLERANCE_SECONDS
    ):
        raise ValueError("max_tolerance_seconds_out_of_range")
    if not data_array:
        return None
    
    target_timestamp = int(target_time.timestamp())
    
    closest = None
    min_diff = float('inf')
    
    for item in data_array:
        ts = _point_timestamp(item, timestamp_key)
        if ts is None:
            continue
        
        diff = abs(ts - target_timestamp)
        if diff < min_diff:
            min_diff = diff
            closest = item
    
    return closest if min_diff <= max_tolerance_seconds else None


def _no_observation(target_time, timezone_label, tolerance):
    return {
        "status": "no_observation",
        "requested_at": target_time.isoformat(),
        "date": target_time.strftime("%Y-%m-%d"),
        "timezone": timezone_label,
        "max_tolerance_seconds": tolerance,
    }


def _observed_metadata(target_time, item, timezone_label, tolerance):
    timestamp = _point_timestamp(item)
    observed = datetime.fromtimestamp(timestamp, tz=target_time.tzinfo)
    return {
        "status": "ok",
        "requested_at": target_time.isoformat(),
        "observed_at": observed.isoformat(),
        "delta_seconds": abs(timestamp - int(target_time.timestamp())),
        "date": target_time.strftime("%Y-%m-%d"),
        "timezone": timezone_label,
        "max_tolerance_seconds": tolerance,
    }


def query_heart_rate_at_time(
    client, time_str, date_str=None, timezone_name=None, max_tolerance_seconds=300
):
    """Get heart rate at a specific time."""
    target_time = parse_time(time_str, date_str, timezone_name)
    _zone, timezone_label = _timezone(timezone_name)
    date = target_time.strftime("%Y-%m-%d")
    
    try:
        # Get intraday heart rate data
        data = client.get_heart_rates(date)
        
        if not data:
            return {"error": "No heart rate data for this date", "date": date}
        
        # Data format varies - try different keys
        hr_array = data.get("heartRateValues") or data.get("allDayHR") or []
        
        # heartRateValues format: [[timestamp_ms, hr_value], ...]
        # Convert to dict format for our function
        if hr_array and isinstance(hr_array[0], list):
            hr_array = [{"startTimeInSeconds": ts//1000, "heartRateValue": val} for ts, val in hr_array]
        
        hr_array = [
            item for item in hr_array
            if 0 < float(item.get("heartRateValue") or item.get("value") or 0) <= 300
        ]
        closest = find_closest_datapoint(
            target_time, hr_array, max_tolerance_seconds=max_tolerance_seconds
        )
        
        if closest:
            return {
                **_observed_metadata(target_time, closest, timezone_label, max_tolerance_seconds),
                "requested_time": time_str,
                "heart_rate": closest.get("heartRateValue") or closest.get("value"),
            }
        else:
            return _no_observation(target_time, timezone_label, max_tolerance_seconds)
    
    except Exception as e:
        return {"error": "live_request_failed", "error_type": type(e).__name__, "date": date}


def query_stress_at_time(
    client, time_str, date_str=None, timezone_name=None, max_tolerance_seconds=300
):
    """Get stress level at a specific time."""
    target_time = parse_time(time_str, date_str, timezone_name)
    _zone, timezone_label = _timezone(timezone_name)
    date = target_time.strftime("%Y-%m-%d")
    
    try:
        data = client.get_all_day_stress(date)
        
        if not data:
            return {"error": "No stress data for this date", "date": date}
        
        stress_values = data.get("stressValuesArray") or []
        
        # Convert [timestamp, value] pairs to dicts
        stress_dicts = [
            {"startTimeInSeconds": ts, "value": val}
            for ts, val in stress_values
            if val is not None and 0 <= float(val) <= 100
        ]
        
        closest = find_closest_datapoint(
            target_time, stress_dicts, max_tolerance_seconds=max_tolerance_seconds
        )
        
        if closest:
            return {
                **_observed_metadata(target_time, closest, timezone_label, max_tolerance_seconds),
                "requested_time": time_str,
                "stress_level": closest.get("value"),
            }
        else:
            return _no_observation(target_time, timezone_label, max_tolerance_seconds)
    
    except Exception as e:
        return {"error": "live_request_failed", "error_type": type(e).__name__, "date": date}


def query_body_battery_at_time(
    client, time_str, date_str=None, timezone_name=None, max_tolerance_seconds=300
):
    """Get Body Battery level at a specific time."""
    target_time = parse_time(time_str, date_str, timezone_name)
    _zone, timezone_label = _timezone(timezone_name)
    date = target_time.strftime("%Y-%m-%d")
    
    try:
        data = client.get_body_battery(date)
        
        if not data or len(data) == 0:
            return {"error": "No Body Battery data for this date", "date": date}
        
        # Body Battery is in bodyBatteryValuesArray
        bb_values = data[0].get("bodyBatteryValuesArray", [])
        
        # Convert [timestamp, value] pairs to dicts
        bb_dicts = [
            {"startTimeInSeconds": ts, "value": val}
            for ts, val in bb_values
            if val is not None and 0 <= float(val) <= 100
        ]
        
        closest = find_closest_datapoint(
            target_time, bb_dicts, max_tolerance_seconds=max_tolerance_seconds
        )
        
        if closest:
            return {
                **_observed_metadata(target_time, closest, timezone_label, max_tolerance_seconds),
                "requested_time": time_str,
                "body_battery": closest.get("value"),
            }
        else:
            return _no_observation(target_time, timezone_label, max_tolerance_seconds)
    
    except Exception as e:
        return {"error": "live_request_failed", "error_type": type(e).__name__, "date": date}


def query_steps_at_time(
    client, time_str, date_str=None, timezone_name=None, max_tolerance_seconds=300
):
    """Get step count at a specific time."""
    target_time = parse_time(time_str, date_str, timezone_name)
    _zone, timezone_label = _timezone(timezone_name)
    date = target_time.strftime("%Y-%m-%d")
    
    try:
        data = client.get_steps_data(date)
        
        if not data:
            return {"error": "No steps data for this date", "date": date}
        
        # Steps are usually cumulative throughout the day
        step_values = data.get("stepsArray") or []
        
        step_values = [
            item for item in step_values
            if float(item.get("steps") if item.get("steps") is not None else item.get("value", -1)) >= 0
        ]
        closest = find_closest_datapoint(
            target_time, step_values, max_tolerance_seconds=max_tolerance_seconds
        )
        
        if closest:
            return {
                **_observed_metadata(target_time, closest, timezone_label, max_tolerance_seconds),
                "requested_time": time_str,
                "steps": closest.get("steps") or closest.get("value"),
            }
        else:
            return _no_observation(target_time, timezone_label, max_tolerance_seconds)
    
    except Exception as e:
        return {"error": "live_request_failed", "error_type": type(e).__name__, "date": date}


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Query Garmin data by time")
    parser.add_argument("metric", choices=["heart_rate", "stress", "body_battery", "steps"],
                       help="Metric to query")
    parser.add_argument("time", help="Time (e.g., '3:00 PM', '15:00', '2024-01-15 14:30')")
    parser.add_argument("--date", help="Required query date (YYYY-MM-DD)")
    parser.add_argument("--timezone", help="Required IANA timezone, for example Asia/Shanghai")
    parser.add_argument("--max-tolerance-seconds", type=int)
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize live Garmin network access for this invocation",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize this exact metric, timestamp, timezone, and tolerance",
    )
    
    args = parser.parse_args()

    if not args.date or not args.timezone or args.max_tolerance_seconds is None:
        print(json.dumps({"status": "EXPLICIT_QUERY_SCOPE_REQUIRED"}))
        return 2
    if not 0 <= args.max_tolerance_seconds <= MAX_TOLERANCE_SECONDS:
        print(json.dumps({"status": "INVALID_TOLERANCE"}))
        return 2
    try:
        target_time = parse_time(args.time, args.date, args.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        print(json.dumps({"status": "INVALID_QUERY_SCOPE"}))
        return 2
    if target_time.strftime("%Y-%m-%d") != args.date:
        print(json.dumps({"status": "QUERY_DATE_MISMATCH"}))
        return 2
    if not args.allow_network:
        print(
            json.dumps(
                {
                    "status": "NETWORK_ACCESS_NOT_AUTHORIZED",
                    "error": "Point queries require --allow-network",
                }
            )
        )
        return 2
    if not args.allow_health_data:
        print(json.dumps({"status": "HEALTH_DATA_ACCESS_NOT_AUTHORIZED"}))
        return 2

    request = {
        "metric": args.metric,
        "requested_at": target_time.isoformat(),
        "timezone": args.timezone,
        "max_tolerance_seconds": args.max_tolerance_seconds,
    }
    network_capability = issue_capability(
        scope="network",
        operation=POINT_QUERY_OPERATION,
        request=request,
    )
    health_data_capability = issue_capability(
        scope="health_data",
        operation=POINT_QUERY_OPERATION,
        request=request,
    )
    client = get_client(
        network_capability=network_capability,
        operation=POINT_QUERY_OPERATION,
        request=request,
    )
    if not client:
        print('{"error": "Not authenticated"}')
        return 1
    consume_capability(
        health_data_capability,
        scope="health_data",
        operation=POINT_QUERY_OPERATION,
        request=request,
    )
    
    if args.metric == "heart_rate":
        result = query_heart_rate_at_time(client, args.time, args.date, args.timezone, args.max_tolerance_seconds)
    elif args.metric == "stress":
        result = query_stress_at_time(client, args.time, args.date, args.timezone, args.max_tolerance_seconds)
    elif args.metric == "body_battery":
        result = query_body_battery_at_time(client, args.time, args.date, args.timezone, args.max_tolerance_seconds)
    elif args.metric == "steps":
        result = query_steps_at_time(client, args.time, args.date, args.timezone, args.max_tolerance_seconds)
    
    print(json.dumps(result, indent=2))
    return 1 if isinstance(result, dict) and "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
