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
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from garmin_auth import get_client
from garmin_data import fetch_summary
from garmin_intelligence import generate_chinese_insight, parse_period, HAS_SQLITE, fetch_local_summary, stitch_v3_metrics

TEMPLATE_FILE = Path(__file__).parent.parent / "assets" / "dashboard_v2.html"

def build_overlay_data(summary_data):
    """Align all metrics into date-synchronized arrays for Chart.js."""
    dates = [s["date"] for s in summary_data.get("sleep", []) if s.get("date")]
    if not dates: return None
    
    # Precise field mapping from garmin_data.py
    stress_list = summary_data.get("stress", [])
    stress_map = {s["date"]:((s.get("high_stress_duration") or 0) + (s.get("medium_stress_duration") or 0))/3600 for s in stress_list}
    steps_map = {s["date"]: s.get("steps") or 0 for s in stress_list}
    
    bb_max_map = {b["date"]: b.get("highest") or 0 for b in summary_data.get("body_battery", [])}
    bb_min_map = {b["date"]: b.get("lowest") or 0 for b in summary_data.get("body_battery", [])}
    
    # Correct HR mapping
    hr_list = summary_data.get("heart_rate", [])
    rhr_map = {h["date"]: h.get("resting_hr") or 0 for h in hr_list}
    max_hr_map = {h["date"]: h.get("max_hr") or 0 for h in hr_list}
    
    import pandas as pd
    def clean_nan(val):
        if pd.isna(val): return None
        return float(round(val, 1)) if isinstance(val, (int, float)) else val

    # --- V4.0 PMC Matrix ---
    try:
        from garmin_sqlite_adapter import get_daily_friction_matrix
        df_pmc = get_daily_friction_matrix(90)
        import pandas as pd
        df_pmc['CTL'] = df_pmc['daily_friction_load'].ewm(span=42, adjust=False).mean()
        df_pmc['ATL'] = df_pmc['daily_friction_load'].ewm(span=7, adjust=False).mean()
        df_pmc['TSB'] = df_pmc['CTL'].shift(1) - df_pmc['ATL'].shift(1)
        pmc_map_ctl = {r['date']: clean_nan(r['CTL']) for _, r in df_pmc.iterrows()}
        pmc_map_atl = {r['date']: clean_nan(r['ATL']) for _, r in df_pmc.iterrows()}
        pmc_map_tsb = {r['date']: clean_nan(r['TSB']) for _, r in df_pmc.iterrows()}
        pmc_map_load = {r['date']: clean_nan(r['daily_friction_load']) for _, r in df_pmc.iterrows()}
    except Exception as e:
        print(f"PMC extraction failed: {e}")
        pmc_map_ctl = {}
        pmc_map_atl = {}
        pmc_map_tsb = {}
        pmc_map_load = {}
    # --- END PMC ---

    sleep_list = summary_data.get("sleep", [])
    avg_hr_map = {s["date"]: s.get("avg_hr") for s in sleep_list}
    
    sleep_h_map = {s["date"]:(s.get("sleep_time_seconds") or 0)/3600 for s in sleep_list}
    sleep_deep_h_map = {s["date"]:(s.get("deep_sleep_seconds") or 0)/3600 for s in sleep_list}
    sleep_score_map = {s["date"]: s.get("sleep_score") or 0 for s in sleep_list}
    avg_spo2_map = {s["date"]: clean_nan(s.get("avg_spo2")) for s in sleep_list}
    
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
    
    # Biomechanics & Daily Summary new metrics
    bio_list = summary_data.get("biomechanics", [])
    gct_map = {b["date"]: clean_nan(b.get("avg_ground_contact_time")) for b in bio_list if "date" in b}
    
    daily_list = summary_data.get("daily_summary", [])
    sweat_loss_map = {d["date"]: clean_nan(d.get("sweat_loss")) or 0 for d in daily_list if "date" in d}
    waking_rr_map = {d["date"]: clean_nan(d.get("rr_waking_avg")) for d in daily_list if "date" in d}
    
    readiness_list = []
    weighted_dissipation_map = {}
    for d in dates:
        stress_entry = next((s for s in stress_list if s["date"] == d), {})
        weighted_h = ((stress_entry.get("high_stress_duration") or 0) + (stress_entry.get("medium_stress_duration") or 0)*0.5) / 3600
        weighted_dissipation_map[d] = round(weighted_h, 1)
        
        ss = sleep_score_map.get(d, 0)
        bb = bb_max_map.get(d, 0)
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
        t = ((act.get("activity_type") or "") + " " + (act.get("activity_name") or "")).lower()
        c = act.get("calories", 0) or 0
        
        if "run" in t or "jog" in t: run_map[d] = run_map.get(d, 0) + c
        elif "cycl" in t or "bik" in t: bike_map[d] = bike_map.get(d, 0) + c
        elif "hik" in t or "mountaineer" in t or "walk" in t: hike_map[d] = hike_map.get(d, 0) + c
        elif "hiit" in t or "training" in t or "fitness" in t or "strength" in t or "elliptical" in t: hiit_map[d] = hiit_map.get(d, 0) + c

    return {
        "dates": dates,
        "stress_h": [stress_map.get(d, 0) for d in dates],
        "bb_max": [bb_max_map.get(d, 0) for d in dates],
        "bb_min": [bb_min_map.get(d, 0) for d in dates],
        "rhr": [rhr_map.get(d, 0) for d in dates],
        "max_hr": [max_hr_map.get(d, 0) for d in dates],
        "avg_hr": [avg_hr_map.get(d) for d in dates],
        "sleep_h": [sleep_h_map.get(d, 0) for d in dates],
        "sleep_deep_h": [sleep_deep_h_map.get(d, 0) for d in dates],
        "sleep_light_h": [max(0, sleep_h_map.get(d, 0) - sleep_deep_h_map.get(d, 0)) for d in dates],
        "sleep_score": [sleep_score_map.get(d, 0) for d in dates],
        "hrv": [hrv_map.get(d, 0) for d in dates],
        "calories": [act_cal_map.get(d, 0) for d in dates],
        "steps": [steps_map.get(d, 0) for d in dates],
        "acute_load": [acute_load_map.get(d, 0) for d in dates],
        "act_running": [run_map.get(d, 0) for d in dates],
        "act_cycling": [bike_map.get(d, 0) for d in dates],
        "act_hiking": [hike_map.get(d, 0) for d in dates],
        "act_hiit": [hiit_map.get(d, 0) for d in dates],
        "ctl": [pmc_map_ctl.get(d, 0) for d in dates],
        "atl": [pmc_map_atl.get(d, 0) for d in dates],
        "tsb": [pmc_map_tsb.get(d, 0) for d in dates],
        "pmc_load": [pmc_map_load.get(d) for d in dates],
        "readiness": readiness_list,
        "weighted_dissipation": [weighted_dissipation_map.get(d, 0) for d in dates],
        "spo2_history": [avg_spo2_map.get(d) for d in dates],
        "waking_rr": [waking_rr_map.get(d) for d in dates],
        "sweat_loss": [sweat_loss_map.get(d, 0) for d in dates],
        "gct_trend": [gct_map.get(d) for d in dates]
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
            # 生理年龄等极高阶指标属于 Garmin 纯云端侧黑盒运算，本地 DB 缺少该表维度，采用混合云端补偿
            client = get_client()
            if client:
                from garmin_data import fetch_max_metrics
                summary_data["max_metrics"] = fetch_max_metrics(client, (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'))
        except Exception as e:
            print(f"⚠️  SQLite load failed: {e}. Falling back to API...", file=sys.stderr)
            client = get_client()
            if not client: return
            summary_data = fetch_summary(client, days)
            stitch_v3_metrics(summary_data, days)
    else:
        client = get_client()
        if not client: return
        summary_data = fetch_summary(client, days)
        stitch_v3_metrics(summary_data, days)
    
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
    out_dir = Path(os.path.expanduser("~/.gemini/memory/garmin"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else out_dir / f"tactical_v2_{days}days_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    
    # Write using binary to ensure UTF-8 bytes are exact
    out_path.write_bytes(html.encode('utf-8'))
    print(f"Report: {out_path.resolve().as_uri()}")

if __name__ == "__main__": main()
