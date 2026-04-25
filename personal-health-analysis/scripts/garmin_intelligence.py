#!/usr/bin/env python3
"""
@Input:  --analysis (flu_risk, readiness, audit), --days, --period
@Output: JSON Analysis Report with Actionable Insights
@Pos:    Intelligence Layer. Second-order analysis of raw health data.

!!! Maintenance Protocol: Tune thresholds based on user feedback. 
"""

import json
import sys
import argparse
import statistics
from pathlib import Path
from datetime import datetime, timedelta

# Import data fetcher
sys.path.insert(0, str(Path(__file__).parent))
try:
    from garmin_sqlite_adapter import get_summary as sqlite_summary, get_sleep_data as sqlite_sleep, get_hrv_data as sqlite_hrv, get_activities_data as sqlite_activities, get_biomechanics_data as sqlite_biomechanics, DB_DIR, get_daily_friction_matrix
    HAS_SQLITE = DB_DIR.exists()
except ImportError:
    HAS_SQLITE = False

from garmin_auth import get_client
from garmin_data import fetch_summary

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

def fetch_local_summary(days):
    """
    Adapter to convert SQLite data into the same format expected by the intelligence layer.
    """
    print(f"📂 Loading data from local SQLite Data Lake ({days} days)...", file=sys.stderr)
    summary_df = sqlite_summary(days)
    
    # --- Check Data Freshness ---
    if not summary_df.empty and 'date' in summary_df.columns and 'resting_heart_rate' in summary_df.columns:
        valid_dates = summary_df.dropna(subset=['resting_heart_rate'])['date']
        if not valid_dates.empty:
            latest_date_str = valid_dates.max()
            try:
                latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
                if (datetime.now() - latest_date).days >= 1:
                    raise DataStaleError(f"Local data is stale. Latest valid entry is {latest_date_str}.")
            except ValueError:
                pass
                
    sleep_df = sqlite_sleep(days)
    hrv_df = sqlite_hrv(days)
    activities_df = sqlite_activities(days)
    biomechanics_df = sqlite_biomechanics(days)
    
    activities_list = activities_df.to_dict('records') if not activities_df.empty else []
    biomechanics_list = biomechanics_df.to_dict('records') if not biomechanics_df.empty else []
    
    daily_loads = {}
    for act in activities_list:
        if isinstance(act.get('duration'), str):
            act['duration'] = parse_time_to_seconds(act['duration'])
        
        d = act.get('date')
        if d and act.get('training_load') is not None:
            daily_loads[d] = daily_loads.get(d, 0) + act['training_load']
            
    training_load_series = [{"date": d, "acute_load": val} for d, val in daily_loads.items()]

    # Convert DataFrames to the dictionary list format expected by existing logic
    summary_data = {
        "heart_rate": summary_df.rename(columns={"resting_heart_rate": "resting_hr"}).to_dict('records'),
        "stress": summary_df.rename(columns={"stress_avg": "avg_stress"}).to_dict('records'),
        "body_battery": summary_df.rename(columns={"body_battery_highest": "highest"}).to_dict('records'),
        "sleep": sleep_df.to_dict('records'),
        "hrv": hrv_df.rename(columns={"hrv_avg": "last_night_avg"}).to_dict('records'),
        "activities": activities_list,
        "biomechanics": biomechanics_list,
        "daily_summary": summary_df.to_dict('records'),
        "training_load_series": training_load_series,
        "training_status": {},
        "max_metrics": {},
        "body_composition": {}
    }
    
    # Add status field to HRV to match existing logic
    for entry in summary_data["hrv"]:
        entry["status"] = "BALANCED" # Default for local simplified extraction
        
    return summary_data

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
    Detect 'The Garmin Flu' pattern (CMO Level):
    1. RHR spike (> 3 bpm above baseline)
    2. HRV drop (> 10% below baseline)
    3. Respiration Rate spike (> 0.5 brpm above baseline) - Key clinical indicator
    """
    hrv_data = summary_data.get("hrv", [])
    hr_data = summary_data.get("heart_rate", [])
    sleep_data = summary_data.get("sleep", [])
    
    # Need at least 3 days of data
    if len(hrv_data) < 3 or len(hr_data) < 3:
        return {"status": "insufficient_data"}
        
    # Get latest data
    latest_hrv_entry = next((item for item in reversed(hrv_data) if item.get("last_night_avg")), hrv_data[-1] if hrv_data else {})
    latest_hr_entry = next((item for item in reversed(hr_data) if item.get("resting_hr")), hr_data[-1] if hr_data else {})
    latest_sleep = next((item for item in reversed(sleep_data) if item.get("avg_respiration")), {})
    
    # Calculate simple baseline (avg of previous days)
    prev_hrv = [val for d in hrv_data if (val := d.get("last_night_avg")) and d != latest_hrv_entry]
    prev_rhr = [val for d in hr_data if (val := d.get("resting_hr")) and d != latest_hr_entry]
    prev_resp = [val for d in sleep_data if (val := d.get("avg_respiration")) and d != latest_sleep]
    
    if not prev_hrv or not prev_rhr:
        return {"status": "insufficient_baseline"}
        
    avg_hrv_baseline = statistics.median(prev_hrv) if prev_hrv else 0
    avg_rhr_baseline = statistics.median(prev_rhr) if prev_rhr else 0
    avg_resp_baseline = statistics.median(prev_resp) if prev_resp else 14.0
    
    current_hrv = latest_hrv_entry.get("last_night_avg") or avg_hrv_baseline
    current_rhr = latest_hr_entry.get("resting_hr") or avg_rhr_baseline
    current_resp = latest_sleep.get("avg_respiration") or avg_resp_baseline
    
    # Thresholds
    hrv_drop_pct = (avg_hrv_baseline - current_hrv) / avg_hrv_baseline * 100 if avg_hrv_baseline > 0 else 0
    rhr_spike = current_rhr - avg_rhr_baseline
    resp_spike = current_resp - avg_resp_baseline
    
    daily_summary_data = summary_data.get("daily_summary", [])
    latest_daily = next((item for item in reversed(daily_summary_data) if item.get("rr_waking_avg")), {})
    current_waking_resp = latest_daily.get("rr_waking_avg")
    prev_waking_resp = [val for d in daily_summary_data if (val := d.get("rr_waking_avg")) and d != latest_daily]
    avg_waking_resp_baseline = statistics.median(prev_waking_resp) if prev_waking_resp else (current_waking_resp or 14.0)
    waking_resp_spike = (current_waking_resp - avg_waking_resp_baseline) if current_waking_resp else 0

    risk_level = "low"
    reasons = []
    
    if rhr_spike > 5 and hrv_drop_pct > 15 and resp_spike > 0.5:
        risk_level = "CRITICAL"
        reasons.append(f"Respiration spike detected (+{resp_spike:.1f} brpm) - High clinical relevance for infection")
        reasons.append(f"Significant RHR spike (+{rhr_spike:.1f} bpm)")
        reasons.append(f"Major HRV drop (-{hrv_drop_pct:.1f}%)")
    elif rhr_spike > 5 and hrv_drop_pct > 15:
        risk_level = "HIGH"
        reasons.append(f"Significant RHR spike (+{rhr_spike:.1f} bpm)")
        reasons.append(f"Major HRV drop (-{hrv_drop_pct:.1f}%)")
    elif rhr_spike > 3 and hrv_drop_pct > 10:
        risk_level = "MODERATE"
        reasons.append(f"RHR elevated (+{rhr_spike:.1f} bpm)")
        reasons.append(f"HRV dip (-{hrv_drop_pct:.1f}%)")
        
    if waking_resp_spike > 0.5:
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

def synthesize_pmc(days=90):
    """
    Calculate PMC (CTL, ATL, TSB) and Ramp Rate using raw friction matrix directly from Adapter.
    """
    if not HAS_SQLITE: return None
    try:
        from garmin_sqlite_adapter import get_daily_friction_matrix
        df = get_daily_friction_matrix(days)
        if df.empty: return None
        import pandas as pd
        df['CTL'] = df['daily_friction_load'].ewm(span=42, adjust=False).mean()
        df['ATL'] = df['daily_friction_load'].ewm(span=7, adjust=False).mean()
        df['TSB'] = df['CTL'].shift(1) - df['ATL'].shift(1)
        df['Ramp_Rate'] = df['ATL'] - df['ATL'].shift(7)
        latest = df.iloc[-1]
        raw_tsb = latest['TSB']
        tsb = 0 if pd.isna(raw_tsb) else float(raw_tsb)
        ctl = 0 if pd.isna(latest['CTL']) else float(latest['CTL'])
        atl = 0 if pd.isna(latest['ATL']) else float(latest['ATL'])
        ramp = 0 if pd.isna(latest['Ramp_Rate']) else float(latest['Ramp_Rate'])
        dload = 0 if pd.isna(latest['daily_friction_load']) else float(latest['daily_friction_load'])
        
        if tsb > 10: zone = "超量恢复 (Fresh)"
        elif tsb >= -10: zone = "战术稳态 (Grey)"
        elif tsb >= -30: zone = "结构性耗散 (Optimal_Training)"
        else: zone = "熔断先兆 (High_Risk)"
        return {
            'CTL': round(ctl, 1), 'ATL': round(atl, 1), 
            'TSB': round(tsb, 1), 'TSB_Zone': zone,
            'Ramp_Rate': round(ramp, 1),
            'Daily_Load': round(dload, 1)
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None

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
    latest_rhr = next((h.get("resting_hr") for h in reversed(hr_data) if h.get("resting_hr")), 0)
    prev_rhrs = [val for h in hr_data if (val := h.get("resting_hr")) and val != latest_rhr]
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
    cog_rem_score = min(rem_pct / 20, 1.2) * 30
    cog_stress_score = max(0, (50 - avg_stress)) * 1
    cog_hrv_score = 40 if hrv_status == "BALANCED" else 20
    cognitive_score = cog_rem_score + cog_stress_score + cog_hrv_score + (sleep_score * 0.2)
    
    # Pessimistic Penalty: Dissipation & Sleep Debt
    if sleep_debt_h > 1.5:
        cognitive_score -= (sleep_debt_h * 5)
    if dissipation_hours > 2.0:
        cognitive_score -= (dissipation_hours * 4) # Cognitive drain penalty
    
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
    pmc = synthesize_pmc(days=90)
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
    latest_rhr = next((h.get("resting_hr") for h in reversed(hr_data) if h.get("resting_hr")), 0)
    prev_rhrs = [val for h in hr_data if (val := h.get("resting_hr")) and val != latest_rhr]
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
        "bmi": bmi
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
        
    pmc = synthesize_pmc(days=90)
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

def generate_chinese_insight(summary_data):
    """Generate a consolidated health analysis in Chinese with Mentat Expert Logic."""
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
    momentum_status = "平稳运转"
    
    if len(hr_data) >= 4 and len(stress_data) >= 4:
        mid_point = len(hr_data) // 2
        first_half_rhr = statistics.median([val for h in hr_data[:mid_point] if (val := h.get("resting_hr"))])
        second_half_rhr = statistics.median([val for h in hr_data[mid_point:] if (val := h.get("resting_hr"))])
        
        first_half_stress = statistics.median([val for s in stress_data[:mid_point] if (val := s.get("avg_stress"))])
        second_half_stress = statistics.median([val for s in stress_data[mid_point:] if (val := s.get("avg_stress"))])
        
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
    
    bb_sparkline = generate_sparkline([b.get("highest") for b in bb_data[-7:]])
    
    # Section 1: System Status & Momentum
    sys_msg = f"【1. 系统态势与防线动量 (System Momentum)】\n"
    sys_msg += f"· 动量向量：{momentum_status}。\n"
    sys_msg += f"· 能量拓扑：[{bb_sparkline}] (近7天电量峰值)\n"
    sys_msg += f"· 摩擦定性：判定为『{load_type}』。"
    
    pmc = synthesize_pmc(days=90)
    if pmc:
        sys_msg += f"\n· 护城河(CTL): {pmc['CTL']} | 急性期(ATL): {pmc['ATL']} | 势差(TSB): {pmc['TSB']} [{pmc['TSB_Zone']}]"
        sys_msg += f"\n· 摩擦加速度(Ramp Rate): {pmc['Ramp_Rate']}/周"
        if pmc['TSB'] < -30:
            sys_msg += "\n  > 🚨【核心熔断预警】系统净胜率全面崩塌！SPOF (单点故障) 前夜！处于致病极高压区。"
        if pmc['Ramp_Rate'] > 150:
            sys_msg += "\n  > 🚨【斜率预警】高压负荷连环爆拉，摩擦斜率失控，防线被迅速穿透！"
            
    try:
        if HAS_SQLITE:
            from garmin_sqlite_adapter import get_daily_friction_matrix
            df_friction = get_daily_friction_matrix(7)
            if not df_friction.empty:
                total_phys = df_friction['training_load'].sum()
                total_comp = df_friction['daily_friction_load'].sum()
                if total_comp > 0:
                    shadow_pct = round((total_comp - total_phys) / total_comp * 100)
                    sys_msg += f"\n· 动力学解构：近7天复合负荷中，Shadow Load(纯精神/认知摩擦) 压空比重高达 {shadow_pct}%。"
                    if shadow_pct > 80:
                        sys_msg += "\n  > 🧠【热力学脱节】系统遭受着极高的纯认知消耗，但物理输出严重缺位。皮质醇正在淤积，必须在 24 小时内强挂 HIIT 等物理手段打破内分泌死锁。"
    except Exception as e: pass

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
        conn = get_connection(GARMIN_DB)
        d_df = pd.read_sql_query("SELECT day as date, sweat_loss, rr_waking_avg FROM daily_summary ORDER BY day DESC", conn)
        if not d_df.empty:
            d_df['date'] = d_df['date'].apply(lambda x: str(x).split(' ')[0])
            d_df = d_df.where(pd.notnull(d_df), None)
            summary_data["daily_summary"] = d_df.to_dict('records')
        
        # 3. SpO2 mapping to sleep
        s_df = pd.read_sql_query("SELECT day as date, avg_spo2 FROM sleep ORDER BY day DESC", conn)
        if not s_df.empty:
            s_df['date'] = s_df['date'].apply(lambda x: str(x).split(' ')[0])
            s_df = s_df.where(pd.notnull(s_df), None)
            spo2_map = {r["date"]: r["avg_spo2"] for r in s_df.to_dict('records') if "date" in r}
            for s in summary_data.get("sleep", []):
                if s.get("date") in spo2_map:
                    s["avg_spo2"] = spo2_map[s["date"]]
        conn.close()
    except Exception as e:
        import sys
        print(f"⚠️ V3 Metrics Stitch failed: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Advanced Health Intelligence")
    parser.add_argument("analysis", choices=["flu_risk", "readiness", "insight_cn", "audit"], help="Analysis type")
    parser.add_argument("--days", type=int, default=7, help="Context window in days")
    parser.add_argument("--period", type=str, help="Period (e.g. 90d, YTD). Overrides --days.")
    
    args = parser.parse_args()
    days = parse_period(args.period, args.days)
    
    if not HAS_SQLITE:
        print('{"error": "Critical Path Error: Local SQLite database missing. API Fallback is explicitly forbidden by system constraints."}', file=sys.stderr)
        sys.exit(1)
        
    try:
        summary_data = fetch_local_summary(days)
    except Exception as e:
        print(f'{{"error": "Critical Path Error: SQLite load failed ({e}). API Fallback is explicitly forbidden."}}', file=sys.stderr)
        sys.exit(1)
    
    if args.analysis == "flu_risk":
        result = analyze_flu_risk(summary_data)
    elif args.analysis == "readiness":
        result = analyze_executive_readiness(summary_data)
    elif args.analysis == "insight_cn":
        result = generate_chinese_insight(summary_data)
    elif args.analysis == "audit":
        result = perform_bio_metric_audit(summary_data)
        
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
