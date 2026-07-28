#!/usr/bin/env python3
"""
@Engine: Template-based rendering (ASCII Safe Mode)
@ इंजन: 战术指挥大屏渲染核心
"""

import json
import sys
import argparse
import webbrowser
import base64
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_summary
from garmin_intelligence import generate_chinese_insight, parse_period, HAS_SQLITE, fetch_local_summary, stitch_v3_metrics
from report_output import build_report_paths

TEMPLATE_FILE = Path(__file__).parent.parent / "assets" / "dashboard_v2.html"

def build_overlay_data(summary_data):
    """Align all metrics into date-synchronized arrays for Chart.js."""
    dates = [s["date"] for s in summary_data.get("sleep", []) if s.get("date")]
    if not dates: return None

    import pandas as pd

    def clean_nan(val):
        if val is None or pd.isna(val):
            return None
        return float(round(val, 1)) if isinstance(val, (int, float)) else val

    def seconds_to_hours(value):
        value = clean_nan(value)
        return round(float(value) / 3600, 3) if value is not None else None

    def complete_duration_hours(*values):
        cleaned = [clean_nan(value) for value in values]
        if any(value is None for value in cleaned):
            return None
        return sum(float(value) for value in cleaned) / 3600

    # Preserve missing observations as nulls for Chart.js rather than plotting
    # fabricated zeroes.
    stress_list = summary_data.get("stress", [])
    stress_map = {
        s["date"]: complete_duration_hours(
            s.get("high_stress_duration"), s.get("medium_stress_duration")
        )
        for s in stress_list
    }
    steps_map = {s["date"]: clean_nan(s.get("steps")) for s in stress_list}

    bb_max_map = {
        b["date"]: clean_nan(b.get("highest"))
        for b in summary_data.get("body_battery", [])
    }
    bb_min_map = {
        b["date"]: clean_nan(b.get("lowest"))
        for b in summary_data.get("body_battery", [])
    }

    hr_list = summary_data.get("heart_rate", [])
    rhr_map = {h["date"]: clean_nan(h.get("resting_hr")) for h in hr_list}
    max_hr_map = {h["date"]: clean_nan(h.get("max_hr")) for h in hr_list}

    # Experimental CTL/ATL/TSB curves are disabled unless a traceable method
    # is explicitly enabled. The chart never reconstructs them with hidden
    # time constants.
    pmc_map_ctl = {}
    pmc_map_atl = {}
    pmc_map_tsb = {}
    pmc_map_load = {}
    firmware_map = {}
    try:
        from garmin_sqlite_adapter import get_devices_info
        df_devices = get_devices_info()
        firmware_str = ", ".join(
            [str(v) for v in df_devices["software_version"].unique()]
        ) if not df_devices.empty else None
        firmware_map = {dates[-1]: firmware_str} if dates and firmware_str else {}
    except Exception:
        pass

    sleep_list = summary_data.get("sleep", [])
    avg_hr_map = {s["date"]: s.get("avg_hr") for s in sleep_list}
    
    sleep_h_map = {
        s["date"]: seconds_to_hours(s.get("sleep_time_seconds")) for s in sleep_list
    }
    sleep_deep_h_map = {
        s["date"]: seconds_to_hours(s.get("deep_sleep_seconds")) for s in sleep_list
    }
    sleep_score_map = {
        s["date"]: clean_nan(s.get("sleep_score")) for s in sleep_list
    }
    avg_spo2_map = {s["date"]: clean_nan(s.get("avg_spo2")) for s in sleep_list}
    
    hrv_list = summary_data.get("hrv", [])
    hrv_map = {
        h["date"]: clean_nan(h.get("last_night_avg")) for h in hrv_list
    }
    hrv_status_map = {h["date"]: h.get("status") for h in hrv_list}
    
    act_cal_map = {}
    temp_map = {}
    for act in summary_data.get("activities", []):
        d = act["date"]
        calories = clean_nan(act.get("calories"))
        if calories is not None:
            act_cal_map[d] = act_cal_map.get(d, 0) + calories
        temperature = clean_nan(act.get("temperature"))
        if temperature is not None:
            temp_map[d] = temperature
    
    # Training Load mapping
    load_list = summary_data.get("training_load_series", [])
    acute_load_map = {
        l["date"]: clean_nan(l.get("acute_load")) for l in load_list
    }
    
    # Biomechanics & Daily Summary new metrics
    bio_list = summary_data.get("biomechanics", [])
    gct_map = {b["date"]: clean_nan(b.get("avg_ground_contact_time")) for b in bio_list if "date" in b}
    
    daily_list = summary_data.get("daily_summary", [])
    sweat_loss_map = {
        d["date"]: clean_nan(d.get("sweat_loss"))
        for d in daily_list
        if "date" in d
    }
    waking_rr_map = {d["date"]: clean_nan(d.get("rr_waking_avg")) for d in daily_list if "date" in d}
    
    readiness_list = []
    weighted_dissipation_map = {}
    # Performance: Replaced O(N^2) generator next() scan with O(N) dictionary lookup for readiness calculation
    stress_dict = {s["date"]: s for s in stress_list if "date" in s}
    for d in dates:
        stress_entry = stress_dict.get(d, {})
        high_duration = clean_nan(stress_entry.get("high_stress_duration"))
        medium_duration = clean_nan(stress_entry.get("medium_stress_duration"))
        weighted_dissipation_map[d] = (
            round((float(high_duration) + float(medium_duration) * 0.5) / 3600, 1)
            if high_duration is not None and medium_duration is not None
            else None
        )
        
        readiness_list.append(None)

    # Activity categorization
    run_map = {}
    bike_map = {}
    hike_map = {}
    hiit_map = {}
    
    for act in summary_data.get("activities", []):
        d = act["date"]
        t = (str(act.get("activity_type") or "") + " " + str(act.get("activity_name") or "")).lower()
        c = clean_nan(act.get("calories"))
        if c is None:
            continue
        
        if "run" in t or "jog" in t: run_map[d] = run_map.get(d, 0) + c
        elif "cycl" in t or "bik" in t: bike_map[d] = bike_map.get(d, 0) + c
        elif "hik" in t or "mountaineer" in t or "walk" in t: hike_map[d] = hike_map.get(d, 0) + c
        elif "hiit" in t or "training" in t or "fitness" in t or "strength" in t or "elliptical" in t: hiit_map[d] = hiit_map.get(d, 0) + c

    return {
        "dates": dates,
        "stress_h": [stress_map.get(d) for d in dates],
        "bb_max": [bb_max_map.get(d) for d in dates],
        "bb_min": [bb_min_map.get(d) for d in dates],
        "rhr": [rhr_map.get(d) for d in dates],
        "max_hr": [max_hr_map.get(d) for d in dates],
        "avg_hr": [avg_hr_map.get(d) for d in dates],
        "sleep_h": [sleep_h_map.get(d) for d in dates],
        "sleep_deep_h": [sleep_deep_h_map.get(d) for d in dates],
        "sleep_light_h": [
            max(0, sleep_h_map[d] - sleep_deep_h_map[d])
            if sleep_h_map.get(d) is not None
            and sleep_deep_h_map.get(d) is not None
            else None
            for d in dates
        ],
        "sleep_score": [sleep_score_map.get(d) for d in dates],
        "hrv": [hrv_map.get(d) for d in dates],
        "calories": [act_cal_map.get(d) for d in dates],
        "steps": [steps_map.get(d) for d in dates],
        "acute_load": [acute_load_map.get(d) for d in dates],
        "act_running": [run_map.get(d) for d in dates],
        "act_cycling": [bike_map.get(d) for d in dates],
        "act_hiking": [hike_map.get(d) for d in dates],
        "act_hiit": [hiit_map.get(d) for d in dates],
        "ctl": [pmc_map_ctl.get(d) for d in dates],
        "atl": [pmc_map_atl.get(d) for d in dates],
        "tsb": [pmc_map_tsb.get(d) for d in dates],
        "pmc_load": [pmc_map_load.get(d) for d in dates],
        "readiness": readiness_list,
        "weighted_dissipation": [weighted_dissipation_map.get(d) for d in dates],
        "spo2_history": [avg_spo2_map.get(d) for d in dates],
        "waking_rr": [waking_rr_map.get(d) for d in dates],
        "sweat_loss": [sweat_loss_map.get(d) for d in dates],
        "gct_trend": [gct_map.get(d) for d in dates],
        "temperature_trend": [temp_map.get(d) for d in dates],
        "software_version": firmware_map.get(dates[-1]) if dates else None
    }

def render_report(charts_data):
    if not TEMPLATE_FILE.exists(): return "Error: Template missing"
    template = TEMPLATE_FILE.read_text(encoding='utf-8')
    
    audit = charts_data.get("audit_data", {})
    colors = {"NEUTRAL": "#64748B", "UP": "#10B981", "DOWN": "#EF4444"}
    status_color = colors["NEUTRAL"]

    rhr_curr = audit.get("system_status", {}).get("rhr", {}).get("current")
    rhr_base = audit.get("system_status", {}).get("rhr", {}).get("baseline")
    rhr_delta = (
        round(((rhr_curr - rhr_base) / rhr_base * 100), 1)
        if rhr_curr is not None and rhr_base not in (None, 0)
        else None
    )
    
    ov = charts_data.get("overlay_data") or {}
    wd_list = ov.get("weighted_dissipation", [])
    weighted_val = wd_list[-1] if wd_list and wd_list[-1] is not None else "--"

    def sanitize_obj(obj):
        import math
        import pandas as pd
        if isinstance(obj, dict):
            return {k: sanitize_obj(v) for k, v in obj.items()}
        elif isinstance(obj, list) or isinstance(obj, tuple):
            return [sanitize_obj(v) for v in obj]
        elif isinstance(obj, float):
            if pd.isna(obj) or math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        return obj

    clean_charts_data = sanitize_obj(charts_data)
    
    # Encoding data to Base64 to bypass any OS/PowerShell character set issues
    json_str = json.dumps(clean_charts_data, ensure_ascii=False, allow_nan=False)
    b64_data = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

    replacements = {
        "%%TITLE%%": "GARMIN HEALTH TRENDS",
        "%%STATUS_COLOR%%": status_color,
        "%%RHR_TREND_COLOR%%": (
            colors["DOWN"] if rhr_delta is not None and rhr_delta > 0
            else colors["UP"] if rhr_delta is not None
            else colors["NEUTRAL"]
        ),
        "%%RHR_DELTA%%": str(rhr_delta) if rhr_delta is not None else "--",
        "%%WEIGHTED_VAL%%": str(weighted_val),
        "%%DEEP_COLOR%%": colors["NEUTRAL"],
        "%%B64_DATA%%": b64_data
    }
    
    for k, v in replacements.items():
        template = template.replace(k, v)
    return template

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("chart", choices=["dashboard", "overlay"])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--period", type=str)
    parser.add_argument("--output")
    args = parser.parse_args()
    
    days = parse_period(args.period, args.days)
    fetch_days = days
    
    summary_data = None
    if HAS_SQLITE:
        try:
            summary_data = fetch_local_summary(fetch_days)
        except Exception as e:
            print(f"⚠️ Local SQLite load failed or stale ({e}). Falling back to Live API...", file=sys.stderr)
            summary_data = None
            
    client = get_client()
    if not summary_data:
        if not client:
            print("Critical Path Error: Live API Auth failed and SQLite is unavailable.", file=sys.stderr)
            sys.exit(1)
            
        try:
            summary_data = fetch_summary(client, fetch_days)
        except Exception as e:
            print(f"Critical Path Error: API load failed ({e}).", file=sys.stderr)
            sys.exit(1)

    # 生理年龄等极高阶指标属于 Garmin 纯云端侧黑盒运算，本地 DB 缺少该表维度，采用混合云端补偿
    if summary_data and client and "max_metrics" not in summary_data:
        try:
            from garmin_data import fetch_max_metrics
            summary_data["max_metrics"] = fetch_max_metrics(client, (datetime.now() - timedelta(days=fetch_days)).strftime('%Y-%m-%d'))
        except Exception:
            pass
    
    charts_data = {}
    if summary_data:
        res = generate_chinese_insight(summary_data)
        charts_data.update({
            "overall_insight": res["overall_insight"],
            "audit_data": res["audit_data"],
            "period": res["period"],
            "quant_scores": res["quant_scores"]
        })
        charts_data["overlay_data"] = build_overlay_data(summary_data)
        if days >= 14:
            charts_data["heatmap"] = [{"date": s["date"], "score": s.get("sleep_score", 0)} for s in summary_data.get("sleep", [])]

    html = render_report(charts_data)
    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = build_report_paths(days=days, create_dir=True)["html"]
    
    # Write using binary to ensure UTF-8 bytes are exact
    out_path.write_bytes(html.encode('utf-8'))
    print(f"Report: {out_path.resolve().as_uri()}")

if __name__ == "__main__": main()
