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
from datetime import datetime
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
    fetch_local_summary,
    generate_chinese_insight,
    parse_period,
)
from report_output import build_report_paths

TEMPLATE_FILE = Path(__file__).parent.parent / "assets" / "dashboard_v2.html"
DASHBOARD_LIVE_OPERATION = "dashboard_live"
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
            text = str(value)
            return text[:10] if len(text) >= 10 else text
    return None


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        return round(numeric, 1) if math.isfinite(numeric) else None
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
    result = {}
    for record in records:
        date = _record_date(record)
        if date:
            result[date] = transform(record.get(field))
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
    rows = []
    for record in _records(summary_data.get("sleep", [])):
        date = _record_date(record)
        if date:
            rows.append({"date": date, "score": _clean_value(record.get("sleep_score"))})
    return sorted(rows, key=lambda row: row["date"])


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
    audit = charts_data.get("audit_data", {})
    rhr = audit.get("system_status", {}).get("rhr", {})
    current = _clean_value(rhr.get("current"))
    baseline = _clean_value(rhr.get("baseline"))
    delta = (
        round((float(current) - float(baseline)) / float(baseline) * 100, 1)
        if current is not None and baseline not in (None, 0)
        else None
    )
    overlay = charts_data.get("overlay_data") or {}
    dissipation = overlay.get("weighted_dissipation", [])
    last_dissipation = next(
        (value for value in reversed(dissipation) if value is not None), "--"
    )
    payload = json.dumps(_sanitize_obj(charts_data), ensure_ascii=False, allow_nan=False)
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    replacements = {
        "%%TITLE%%": "Garmin 健康趋势",
        "%%STATUS_COLOR%%": "#475569",
        "%%RHR_DELTA%%": str(delta) if delta is not None else "--",
        "%%WEIGHTED_VAL%%": str(last_dissipation),
        "%%B64_DATA%%": encoded,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def _load_summary(
    days: int,
    source: str,
    *,
    network_capability: object = None,
    health_data_capability: object = None,
    request: dict[str, object] | None = None,
) -> dict[str, Any]:
    if source == "local":
        if not HAS_SQLITE:
            raise RuntimeError("LOCAL_DATA_UNAVAILABLE")
        result = fetch_local_summary(days)
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
            else tuple(LIVE_SUMMARY_COMPONENTS)
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
        start_date, end_date = get_date_range(days)
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
            start_date, end_date = get_date_range(days)
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

    insight = generate_chinese_insight(summary_data)
    charts_data = {
        "overall_insight": insight["overall_insight"],
        "audit_data": insight["audit_data"],
        "period": insight["period"],
        "quant_scores": insight["quant_scores"],
        "overlay_data": build_overlay_data(summary_data),
        "data_source": {
            "requested": args.source,
            "effective": effective_source,
            "live_fallback_attempted": live_fallback_attempted,
            "components": list(selected_components) if effective_source == "live" else [],
        },
    }
    if days >= 14:
        charts_data["heatmap"] = build_heatmap_data(summary_data)

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
