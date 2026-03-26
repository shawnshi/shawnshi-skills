#!/usr/bin/env python3
"""
@Engine: Template-based rendering (ASCII Safe Mode)
@ इंजन: 战术指挥大屏渲染核心
"""

import json
import sys
import argparse
import webbrowser
import os
import base64
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_summary
from garmin_intelligence import generate_chinese_insight, parse_period, HAS_SQLITE, fetch_local_summary

TEMPLATE_FILE = Path(__file__).parent.parent / "assets" / "dashboard_v2.html"

def build_overlay_data(summary_data):
    """Align all metrics into date-synchronized arrays for Chart.js."""
    dates = [s["date"] for s in summary_data.get("sleep", []) if s.get("date")]
    if not dates: return None
    
    # Precise field mapping from garmin_data.py
    stress_list = summary_data.get("stress", [])
    stress_map = {s["date"]:((s.get("high_stress_duration") or 0) + (s.get("medium_stress_duration") or 0))/3600 for s in stress_list}
    steps_map = {s["date"]: s.get("steps") or 0 for s in stress_list}
    
    bb_map = {b["date"]: b.get("highest") or 0 for b in summary_data.get("body_battery", [])}
    
    # Correct HR mapping
    hr_list = summary_data.get("heart_rate", [])
    rhr_map = {h["date"]: h.get("resting_hr") or 0 for h in hr_list}
    max_hr_map = {h["date"]: h.get("max_hr") or 0 for h in hr_list}
    
    sleep_h_map = {s["date"]:(s.get("sleep_time_seconds") or 0)/3600 for s in summary_data.get("sleep", [])}
    sleep_score_map = {s["date"]: s.get("sleep_score") or 0 for s in summary_data.get("sleep", [])}
    
    hrv_list = summary_data.get("hrv", [])
    hrv_map = {h["date"]: h.get("last_night_avg") or 0 for h in hrv_list}
    hrv_status_map = {h["date"]: h.get("status") for h in hrv_list}
    
    act_cal_map = {}
    for act in summary_data.get("activities", []):
        d = act["date"]
        act_cal_map[d] = act_cal_map.get(d, 0) + (act.get("calories") or 0)
    
    # Training Load mapping
    load_list = summary_data.get("training_load_series", [])
    acute_load_map = {l["date"]: l.get("acute_load") or 0 for l in load_list}
    
    readiness_list = []
    weighted_dissipation_map = {}
    for d in dates:
        stress_entry = next((s for s in stress_list if s["date"] == d), {})
        weighted_h = ((stress_entry.get("high_stress_duration") or 0) + (stress_entry.get("medium_stress_duration") or 0)*0.5) / 3600
        weighted_dissipation_map[d] = round(weighted_h, 1)
        
        ss = sleep_score_map.get(d, 0)
        bb = bb_map.get(d, 0)
        hrv_stat = hrv_status_map.get(d, "BALANCED")
        
        score = (ss * 0.4) + (bb * 0.4)
        if hrv_stat == "BALANCED": score += 20
        elif hrv_stat == "UNBALANCED": score += 5
        score -= (weighted_h * 4)
        readiness_list.append(round(max(0, min(100, score)), 1))

    # Activity categorization
    run_map = {}
    bike_map = {}
    hike_map = {}
    hiit_map = {}
    
    for act in summary_data.get("activities", []):
        d = act["date"]
        t = act.get("activity_type", "").lower()
        c = act.get("calories", 0) or 0
        
        if "running" in t: run_map[d] = run_map.get(d, 0) + c
        elif "cycling" in t: bike_map[d] = bike_map.get(d, 0) + c
        elif "hiking" in t or "mountaineer" in t or "walking" in t: hike_map[d] = hike_map.get(d, 0) + c
        elif "hiit" in t or "training" in t or "fitness" in t: hiit_map[d] = hiit_map.get(d, 0) + c

    return {
        "dates": dates,
        "stress_h": [stress_map.get(d, 0) for d in dates],
        "bb_peak": [bb_map.get(d, 0) for d in dates],
        "rhr": [rhr_map.get(d, 0) for d in dates],
        "max_hr": [max_hr_map.get(d, 0) for d in dates],
        "sleep_h": [sleep_h_map.get(d, 0) for d in dates],
        "sleep_score": [sleep_score_map.get(d, 0) for d in dates],
        "hrv": [hrv_map.get(d, 0) for d in dates],
        "calories": [act_cal_map.get(d, 0) for d in dates],
        "steps": [steps_map.get(d, 0) for d in dates],
        "acute_load": [acute_load_map.get(d, 0) for d in dates],
        "act_running": [run_map.get(d, 0) for d in dates],
        "act_cycling": [bike_map.get(d, 0) for d in dates],
        "act_hiking": [hike_map.get(d, 0) for d in dates],
        "act_hiit": [hiit_map.get(d, 0) for d in dates],
        "readiness": readiness_list,
        "weighted_dissipation": [weighted_dissipation_map.get(d, 0) for d in dates]
    }

def render_report(charts_data):
    if not TEMPLATE_FILE.exists(): return "Error: Template missing"
    template = TEMPLATE_FILE.read_text(encoding='utf-8')
    
    audit = charts_data.get("audit_data", {})
    move_type = audit.get("action_protocol", {}).get("type", "YELLOW")
    colors = {"GREEN":"#10B981","RED":"#EF4444","YELLOW":"#F59E0B","PURPLE":"#8B5CF6"}
    status_color = colors.get(move_type, colors["YELLOW"])
    if move_type == "ALERT": status_color = colors["PURPLE"]

    rhr_curr = audit.get("system_status", {}).get("rhr", {}).get("current", 0)
    rhr_base = audit.get("system_status", {}).get("rhr", {}).get("baseline", 0)
    rhr_delta = round(((rhr_curr - rhr_base) / rhr_base * 100), 1) if rhr_base else 0
    
    ov = charts_data.get("overlay_data", {})
    wd_list = ov.get("weighted_dissipation", [])
    weighted_val = wd_list[-1] if wd_list else "--"

    # Encoding data to Base64 to bypass any OS/PowerShell character set issues
    json_str = json.dumps(charts_data, ensure_ascii=False)
    b64_data = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

    replacements = {
        "%%TITLE%%": "GARMIN STRATEGIC AUDIT",
        "%%STATUS_COLOR%%": status_color,
        "%%RHR_TREND_COLOR%%": colors["RED"] if rhr_delta > 0 else colors["GREEN"],
        "%%RHR_DELTA%%": str(rhr_delta),
        "%%WEIGHTED_VAL%%": str(weighted_val),
        "%%DEEP_COLOR%%": colors["GREEN"] if audit.get("recovery_loop", {}).get("sleep_architecture", {}).get("deep_pct", 0) >= 15 else colors["RED"],
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
    
    if HAS_SQLITE:
        try:
            summary_data = fetch_local_summary(days)
        except Exception as e:
            print(f"⚠️  SQLite load failed: {e}. Falling back to API...", file=sys.stderr)
            client = get_client()
            if not client: return
            summary_data = fetch_summary(client, days)
    else:
        client = get_client()
        if not client: return
        summary_data = fetch_summary(client, days)
    
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
    out_dir = Path(r"C:\Users\shich\.gemini\memory\garmin")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else out_dir / f"tactical_v2_{days}days_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    
    # Write using binary to ensure UTF-8 bytes are exact
    out_path.write_bytes(html.encode('utf-8'))
    print(f"Report: {out_path}")

if __name__ == "__main__": main()
