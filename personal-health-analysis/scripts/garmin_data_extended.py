#!/usr/bin/env python3
"""Fetch one precisely scoped live Garmin metric with two explicit grants."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from garmin_capabilities import (
    CapabilityError,
    consume_capability,
    issue_capability,
    require_capability,
)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_AUTHORIZATION = 3
EXIT_AUTH_FAILURE = 4
EXIT_REQUEST_FAILURE = 5
EXTENDED_OPERATION = "extended_health_data_live"

METRIC_CHOICES = (
    "training_readiness", "training_status", "body_composition", "weigh_ins",
    "spo2", "respiration", "steps", "floors", "intensity_minutes",
    "hydration", "stress_detailed", "max_metrics", "fitness_age",
    "endurance_score", "hill_score", "hr_intraday",
)
RANGE_METRICS = {"weigh_ins", "endurance_score", "hill_score"}


def _get_client(
    *,
    network_capability: object = None,
    health_data_capability: object = None,
    request: dict[str, object] | None = None,
):
    """Import authentication only after the caller authorizes live access."""
    try:
        require_capability(
            network_capability,
            scope="network",
            operation=EXTENDED_OPERATION,
            request=request,
        )
    except CapabilityError as exc:
        raise PermissionError("network_authorization_required") from exc
    try:
        require_capability(
            health_data_capability,
            scope="health_data",
            operation=EXTENDED_OPERATION,
            request=request,
        )
    except CapabilityError as exc:
        raise PermissionError("health_data_authorization_required") from exc
    sys.path.insert(0, str(Path(__file__).parent))
    from garmin_auth import get_client
    return get_client(
        network_capability=network_capability,
        operation=EXTENDED_OPERATION,
        request=request,
    )


def _safe_failure(exc: BaseException, **context) -> dict:
    return {
        "error": "live_request_failed",
        "error_type": type(exc).__name__,
        **context,
    }


def fetch_training_readiness(client, date=None):
    """Fetch daily training readiness score."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_training_readiness(date)
        return {"training_readiness": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_training_status(client, date=None):
    """Fetch training status (load, VO2 max, etc.)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_training_status(date)
        return {"training_status": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_body_composition(client, date=None):
    """Fetch body composition (weight, body fat %, muscle mass, etc.)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_body_composition(date)
        return {"body_composition": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_weigh_ins(client, start_date=None, end_date=None):
    """Fetch weight measurements over time."""
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_weigh_ins(start_date, end_date)
        return {"weigh_ins": data, "start": start_date, "end": end_date}
    except Exception as e:
        return _safe_failure(e, start=start_date, end=end_date)


def fetch_spo2(client, date=None):
    """Fetch blood oxygen (SPO2) data."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_spo2_data(date)
        return {"spo2": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_respiration(client, date=None):
    """Fetch respiration data throughout the day."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_respiration_data(date)
        return {"respiration": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_steps_detailed(client, date=None):
    """Fetch detailed step data."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_steps_data(date)
        return {"steps": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_floors(client, date=None):
    """Fetch floors climbed data."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_floors(date)
        return {"floors": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_intensity_minutes(client, date=None):
    """Fetch intensity minutes (vigorous/moderate activity)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_intensity_minutes_data(date)
        return {"intensity_minutes": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_hydration(client, date=None):
    """Fetch hydration/water intake data."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_hydration_data(date)
        return {"hydration": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_all_day_stress(client, date=None):
    """Fetch detailed stress data throughout the day (time-series)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_all_day_stress(date)
        return {"stress_detailed": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_max_metrics(client, date=None):
    """Fetch max metrics (VO2 max, etc.)."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        data = client.get_max_metrics(date)
        return {"max_metrics": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_fitness_age(client, date=None):
    """Fetch fitness age data."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        data = client.get_fitnessage_data(date)
        return {"fitness_age": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def fetch_endurance_score(client, start=None, end=None):
    """Fetch endurance score."""
    if not start:
        start = datetime.now().strftime("%Y-%m-%d")

    try:
        data = (
            client.get_endurance_score(start, end)
            if end
            else client.get_endurance_score(start)
        )
        return {"endurance_score": data, "start": start, "end": end}
    except Exception as e:
        return _safe_failure(e, start=start, end=end)


def fetch_hill_score(client, start=None, end=None):
    """Fetch hill score."""
    if not start:
        start = datetime.now().strftime("%Y-%m-%d")

    try:
        data = (
            client.get_hill_score(start, end)
            if end
            else client.get_hill_score(start)
        )
        return {"hill_score": data, "start": start, "end": end}
    except Exception as e:
        return _safe_failure(e, start=start, end=end)


def fetch_intraday_heart_rate(client, date=None):
    """Fetch heart rate data throughout the day with timestamps."""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        # get_heart_rates returns time-series data
        data = client.get_heart_rates(date)
        return {"heart_rate_intraday": data, "date": date}
    except Exception as e:
        return _safe_failure(e, date=date)


def _build_request(args) -> dict[str, object]:
    """Validate the exact data window before any live client is initialized."""
    if args.metric in RANGE_METRICS:
        if args.date or not args.start or not args.end:
            raise ValueError("range_metric_requires_start_and_end")
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
        if start > end:
            raise ValueError("start_after_end")
        return {"metric": args.metric, "start": args.start, "end": args.end}
    if not args.date or args.start or args.end:
        raise ValueError("daily_metric_requires_date")
    datetime.strptime(args.date, "%Y-%m-%d")
    return {"metric": args.metric, "date": args.date}


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch extended Garmin health data")
    parser.add_argument("metric", nargs="?", choices=METRIC_CHOICES, help="Type of data to fetch")
    parser.add_argument("--date", help="Required date for a daily metric (YYYY-MM-DD)")
    parser.add_argument("--start", help="Start date for date ranges (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date for date ranges (YYYY-MM-DD)")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly authorize this invocation to contact Garmin",
    )
    parser.add_argument(
        "--allow-health-data",
        action="store_true",
        help="Explicitly authorize this exact metric and date window",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate the request without access"
    )
    return parser


def main(argv: Sequence[str] | None = None):
    args = build_parser().parse_args(argv)
    if args.metric is None:
        print(json.dumps({"ok": False, "status": "usage_error", "error": "metric_required"}))
        return EXIT_USAGE
    try:
        request = _build_request(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "status": "usage_error", "error": str(exc)}))
        return EXIT_USAGE
    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "status": "dry_run",
            "metric": args.metric,
            "request": request,
            "network_accessed": False,
        }))
        return EXIT_OK
    if not args.allow_network:
        print(json.dumps({
            "ok": False,
            "status": "network_authorization_required",
            "metric": args.metric,
        }))
        return EXIT_AUTHORIZATION
    if not args.allow_health_data:
        print(json.dumps({
            "ok": False,
            "status": "health_data_authorization_required",
            "metric": args.metric,
        }))
        return EXIT_AUTHORIZATION

    network_capability = issue_capability(
        scope="network",
        operation=EXTENDED_OPERATION,
        request=request,
    )
    health_data_capability = issue_capability(
        scope="health_data",
        operation=EXTENDED_OPERATION,
        request=request,
    )
    client = _get_client(
        network_capability=network_capability,
        health_data_capability=health_data_capability,
        request=request,
    )
    if not client:
        print(json.dumps({"ok": False, "status": "session_unavailable"}))
        return EXIT_AUTH_FAILURE
    consume_capability(
        health_data_capability,
        scope="health_data",
        operation=EXTENDED_OPERATION,
        request=request,
    )
    
    # Route to appropriate function
    if args.metric == "training_readiness":
        result = fetch_training_readiness(client, args.date)
    elif args.metric == "training_status":
        result = fetch_training_status(client, args.date)
    elif args.metric == "body_composition":
        result = fetch_body_composition(client, args.date)
    elif args.metric == "weigh_ins":
        result = fetch_weigh_ins(client, args.start, args.end)
    elif args.metric == "spo2":
        result = fetch_spo2(client, args.date)
    elif args.metric == "respiration":
        result = fetch_respiration(client, args.date)
    elif args.metric == "steps":
        result = fetch_steps_detailed(client, args.date)
    elif args.metric == "floors":
        result = fetch_floors(client, args.date)
    elif args.metric == "intensity_minutes":
        result = fetch_intensity_minutes(client, args.date)
    elif args.metric == "hydration":
        result = fetch_hydration(client, args.date)
    elif args.metric == "stress_detailed":
        result = fetch_all_day_stress(client, args.date)
    elif args.metric == "max_metrics":
        result = fetch_max_metrics(client, args.date)
    elif args.metric == "fitness_age":
        result = fetch_fitness_age(client, args.date)
    elif args.metric == "endurance_score":
        result = fetch_endurance_score(client, args.start or args.date, args.end)
    elif args.metric == "hill_score":
        result = fetch_hill_score(client, args.start or args.date, args.end)
    elif args.metric == "hr_intraday":
        result = fetch_intraday_heart_rate(client, args.date)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return EXIT_REQUEST_FAILURE if isinstance(result, dict) and "error" in result else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
