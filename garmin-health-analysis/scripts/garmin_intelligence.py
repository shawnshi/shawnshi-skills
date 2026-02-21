#!/usr/bin/env python3
"""
@Input:  --analysis (flu_risk, readiness, audit), --days
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
from garmin_auth import get_client
from garmin_data import fetch_summary

def analyze_flu_risk(summary_data):
    """
    Detect 'The Garmin Flu' pattern:
    1. RHR spike (> 3 bpm above baseline)
    2. HRV drop (> 10% below baseline)
    """
    hrv_data = summary_data.get("hrv", [])
    hr_data = summary_data.get("heart_rate", [])
    
    # Need at least 3 days of data
    if len(hrv_data) < 3 or len(hr_data) < 3:
        return {"status": "insufficient_data"}
        
    # Get latest data (look for last non-null values)
    latest_hrv_entry = next((item for item in reversed(hrv_data) if item.get("last_night_avg")), hrv_data[-1])
    latest_hr_entry = next((item for item in reversed(hr_data) if item.get("resting_hr")), hr_data[-1])
    
    # Calculate simple baseline (avg of previous days)
    prev_hrv = [d.get("last_night_avg") for d in hrv_data if d.get("last_night_avg") and d != latest_hrv_entry]
    prev_rhr = [d.get("resting_hr") for d in hr_data if d.get("resting_hr") and d != latest_hr_entry]
    
    if not prev_hrv or not prev_rhr:
        return {"status": "insufficient_baseline"}
        
    avg_hrv_baseline = sum(prev_hrv) / len(prev_hrv)
    avg_rhr_baseline = sum(prev_rhr) / len(prev_rhr)
    
    current_hrv = latest_hrv_entry.get("last_night_avg") or avg_hrv_baseline
    current_rhr = latest_hr_entry.get("resting_hr") or avg_rhr_baseline
    
    # Thresholds
    hrv_drop_pct = (avg_hrv_baseline - current_hrv) / avg_hrv_baseline * 100
    rhr_spike = current_rhr - avg_rhr_baseline
    
    risk_level = "low"
    reasons = []
    
    if rhr_spike > 5 and hrv_drop_pct > 15:
        risk_level = "HIGH"
        reasons.append(f"Significant RHR spike (+{rhr_spike:.1f} bpm)")
        reasons.append(f"Major HRV drop (-{hrv_drop_pct:.1f}%)")
    elif rhr_spike > 3 and hrv_drop_pct > 10:
        risk_level = "MODERATE"
        reasons.append(f"RHR elevated (+{rhr_spike:.1f} bpm)")
        reasons.append(f"HRV dip (-{hrv_drop_pct:.1f}%)")
        
    return {
        "analysis_type": "bio_entropy_flu_risk",
        "date": latest_hrv_entry["date"],
        "risk_level": risk_level,
        "metrics": {
            "current_rhr": current_rhr,
            "baseline_rhr": round(avg_rhr_baseline, 1),
            "current_hrv": current_hrv,
            "baseline_hrv": round(avg_hrv_baseline, 1)
        },
        "insights": reasons
    }

def calculate_sleep_consistency(sleep_data):
    """Calculate sleep duration consistency (lower std dev is better)."""
    if not sleep_data or len(sleep_data) < 2:
        return 0, "数据不足"
    
    durations = [s.get("sleep_time_seconds", 0) / 3600 for s in sleep_data if s.get("sleep_time_seconds")]
    if not durations:
        return 0, "数据不足"
        
    std_dev = statistics.stdev(durations)
    return round(std_dev, 2), "高" if std_dev > 1.5 else "中" if std_dev > 0.8 else "优"

def analyze_executive_readiness(summary_data):
    """
    Calculate Daily Executive Readiness Score (0-100) with Cognitive vs Physical split.
    """
    # Get latest non-null data
    sleep_list = summary_data.get("sleep", [])
    bb_list = summary_data.get("body_battery", [])
    stress_list = summary_data.get("stress", [])
    hrv_list = summary_data.get("hrv", [])

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

    # 2. Cognitive Readiness (Focus: REM, HRV, Stress)
    cog_rem_score = min(rem_pct / 20, 1.2) * 30
    cog_stress_score = max(0, (50 - avg_stress)) * 1
    cog_hrv_score = 40 if hrv_status == "BALANCED" else 20
    cognitive_score = min(100, cog_rem_score + cog_stress_score + cog_hrv_score + (sleep_score * 0.2))

    # 3. Physical Readiness (Focus: Deep Sleep, Body Battery, RHR Stability)
    phy_deep_score = min(deep_pct / 15, 1.2) * 30
    phy_bb_score = (bb_peak / 100) * 40
    phy_hrv_score = 30 if hrv_status == "BALANCED" else 10
    physical_score = min(100, phy_deep_score + phy_bb_score + phy_hrv_score)

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
        "recommendation": recommendation
    }

def perform_bio_metric_audit(summary_data):
    """
    Garmin Bio-Metric Audit (The Audit)
    Based on 4 Layers: System Status, Recovery Loop, Load & Friction, Action Protocol.
    """
    # 1. System Status Audit
    hr_data = summary_data.get("heart_rate", [])
    hrv_data = summary_data.get("hrv", [])
    training_status = summary_data.get("training_status", {})
    max_metrics = summary_data.get("max_metrics", {})
    
    # RHR Audit
    latest_rhr = next((h.get("resting_hr") for h in reversed(hr_data) if h.get("resting_hr")), 0)
    prev_rhrs = [h.get("resting_hr") for h in hr_data if h.get("resting_hr") and h.get("resting_hr") != latest_rhr]
    baseline_rhr = sum(prev_rhrs) / len(prev_rhrs) if prev_rhrs else latest_rhr
    rhr_diff = latest_rhr - baseline_rhr if latest_rhr > 0 else 0
    
    rhr_status = "稳定"
    if latest_rhr == 0: rhr_status = "无数据"
    elif rhr_diff < -2: rhr_status = "优异 (心肺耐力提升)"
    elif rhr_diff > 3: rhr_status = "警告 (代谢压力高)"
    
    # HRV Audit
    latest_hrv = next((h.get("last_night_avg") for h in reversed(hrv_data) if h.get("last_night_avg")), 0)
    hrv_status_raw = next((h.get("status") for h in reversed(hrv_data) if h.get("status")), "无数据")
    
    # VO2 Max & Fitness Age
    vo2_max = training_status.get("vo2_max", "--")
    fitness_age = max_metrics.get("fitness_age", "--")

    system_status = {
        "rhr": {"current": latest_rhr, "baseline": round(baseline_rhr, 1), "status": rhr_status},
        "hrv": {"value": latest_hrv, "status": hrv_status_raw},
        "vo2_max": vo2_max,
        "fitness_age": fitness_age
    }

    # 2. Recovery Loop Audit
    sleep_data = summary_data.get("sleep", [])
    latest_sleep = next((s for s in reversed(sleep_data) if s.get("sleep_time_seconds")), {})
    
    total_sleep = latest_sleep.get("sleep_time_seconds", 0)
    deep_sleep = latest_sleep.get("deep_sleep_seconds", 0)
    rem_sleep = latest_sleep.get("rem_sleep_seconds", 0)
    
    deep_pct = (deep_sleep / total_sleep * 100) if total_sleep > 0 else 0
    rem_pct = (rem_sleep / total_sleep * 100) if total_sleep > 0 else 0
    
    bb_data = summary_data.get("body_battery", [])
    latest_bb = next((b for b in reversed(bb_data) if b.get("highest")), {})
    bb_charged = latest_bb.get("charged", 0)
    bb_peak = latest_bb.get("highest", 0)
    
    recovery_loop = {
        "sleep_architecture": {
            "deep_pct": round(deep_pct, 1),
            "rem_pct": round(rem_pct, 1),
            "restlessness": latest_sleep.get("restless_periods", 0)
        },
        "body_battery": {
            "charged": bb_charged,
            "peak": bb_peak
        }
    }

    # 3. Load & Friction Audit
    stress_data = summary_data.get("stress", [])
    latest_stress = next((s for s in reversed(stress_data) if s.get("avg_stress")), {})
    
    load_friction = {
        "stress_score": latest_stress.get("avg_stress", 0),
        "training_load": {
            "ratio": training_status.get("load_ratio", "--"),
            "status": training_status.get("load_status", "无数据")
        }
    }

    # 4. Action Protocol Logic
    protocol = "黄灯 (Fatigue) - 维护性运转"
    protocol_desc = "保持低强度有氧 (Zone 2)，时长缩减 30%。不要追求 PR。"
    move_type = "YELLOW"

    sleep_score = latest_sleep.get("sleep_score", 0) or 0

    if hrv_status_raw == "BALANCED" and sleep_score > 80 and bb_peak > 80:
        protocol = "绿灯 (Prime) - 推极限"
        protocol_desc = "执行高强度间歇 (HIIT) 或长距离训练。这是打破平台的窗口期。"
        move_type = "GREEN"
    elif rhr_diff > 4 or (latest_stress.get("avg_stress", 0) > 45 and hrv_status_raw != "BALANCED"):
        protocol = "警报 (Infection/Overload) - 停机"
        protocol_desc = "身体正在对抗应激或病毒。禁止训练，早睡是唯一任务。"
        move_type = "ALERT"
    elif hrv_status_raw != "BALANCED" or sleep_score < 60:
        protocol = "红灯 (Critical) - 主动刹车"
        protocol_desc = "禁止高强度运动。仅允许散步、冥想、拉伸。"
        move_type = "RED"
    
    if latest_hrv == 0 and latest_rhr == 0:
        protocol = "数据同步中"
        protocol_desc = "未检测到今日有效的生理指标，请确保设备已同步。"
        move_type = "YELLOW"

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

def generate_chinese_insight(summary_data):
    """Generate a consolidated health analysis in Chinese with Expert Logic."""
    audit = perform_bio_metric_audit(summary_data)
    readiness = analyze_executive_readiness(summary_data)
    
    # 1. Sleep Consistency Audit
    sleep_data = summary_data.get("sleep", [])
    std_dev, consist_status = calculate_sleep_consistency(sleep_data)
    
    # 2. Load Decoupling
    avg_stress = audit["load_friction"]["stress_score"]
    total_activities = summary_data.get('summary', {}).get('total_activities', 0)
    load_ratio_str = audit["load_friction"]["training_load"]["ratio"]
    load_ratio = float(load_ratio_str) if isinstance(load_ratio_str, (int, float)) else 0
    
    load_type = "被动熵增 (焦虑/代谢压力)"
    if total_activities > 2 and load_ratio > 0.7:
        load_type = "良性应激 (训练驱动)"
        
    avg_bb_charged = summary_data.get('summary', {}).get('avg_body_battery_charged', 0)
    avg_sleep = summary_data.get("summary", {}).get("avg_sleep_hours", 0)
    avg_score = summary_data.get("summary", {}).get("avg_sleep_score", 0)

    # --- Quantitative Scores ---
    score_input = round((min(avg_bb_charged, 80)/80 * 70) + (30 if consist_status == "优" else 15), 1)
    score_loss = round(avg_stress + (load_ratio * 10), 1)
    score_output = round(readiness['score'], 1)

    # --- Generate Text Report (Expert Level) ---
    overall_sections = []
    period_str = summary_data.get('summary', {}).get('period', '指定时间段')
    
    # 1. Input Side: Biological Rhythm & Recovery Quality
    avg_deep_pct = audit["recovery_loop"]["sleep_architecture"]["deep_pct"]
    consist_msg = f"【1. 输入审计：生物节律与修复质量】\n"
    consist_msg += f"周期内睡眠一致性评价为「{consist_status}」（标准差 {std_dev}h）。"
    if consist_status == "优":
        consist_msg += "极佳的入睡规律构成了强大的生理稳态，这种可预测性是内分泌系统（如皮质醇节律）稳定的基石。"
    else:
        consist_msg += "节律波动较大，这种“社会时差”效应会显著削弱睡眠对认知的修复效率，建议通过固定起床时间来锚定生物钟。"
    
    if avg_deep_pct < 15:
        consist_msg += f"\n监测到深睡占比（{avg_deep_pct}%）低于 15% 的生理修复阈值，暗示物理层面的修复受阻，长期将侵蚀基础免疫力。"
    else:
        consist_msg += f"\n深睡结构良好（{avg_deep_pct}%），确保了物理层面的系统重建。"
    overall_sections.append(consist_msg)

    # 2. Friction Side: Metabolic Stress & Load Decoupling
    friction_msg = f"【2. 损耗审计：代谢摩擦与负荷性质】\n"
    friction_msg += f"当前属于「{load_type}」模式。"
    if load_type.startswith("被动"):
        friction_msg += f"平均压力值 {avg_stress} 且缺乏运动对冲，系统正在产生由于久坐或精神焦虑导致的“无效损耗”。"
        friction_msg += "这会导致系统熵增过快，建议引入规律性的物理刺激（如 Zone 2 运动）来重建代谢灵活性。"
    else:
        friction_msg += f"平均压力主要由高强度的物理负荷驱动。当前 ACWR 负载比为 {load_ratio}，"
        if 0.8 <= load_ratio <= 1.3:
            friction_msg += "处于理想的适能增长区间，系统正在通过超量补偿（Supercompensation）进行自我升级。"
        elif load_ratio > 1.5:
            friction_msg += "负载已进入「危险红区」，受伤风险与免疫抑制概率呈指数级上升，必须进入防守周期。"
        else:
            friction_msg += "负荷强度较低，系统面临“失练”导致的体能衰退风险。"
    overall_sections.append(friction_msg)

    # 3. Output Side: Cognitive vs. Physical Executive Readiness
    output_msg = f"【3. 输出审计：身心分层执行力评估】\n"
    output_msg += f"综合执行准备度得分 {readiness['score']}。\n"
    
    if readiness['cognitive_score'] > 80:
        output_msg += f"- 🧠 认知端（{readiness['cognitive_score']}）：系统处于「高频运行」状态，前额叶皮层功能活跃，非常适合处理复杂决策与创新构思。"
    else:
        output_msg += f"- 🧠 认知端（{readiness['cognitive_score']}）：认知冗余不足，决策质量可能随时间递减，建议避免在疲劳期进行战略性转向。"
        
    if readiness['physical_score'] > 80:
        output_msg += f"\n- 💪 物理端（{readiness['physical_score']}）：动力充沛，神经肌肉募集能力处于波峰，适合执行力量训练或耐力攻坚。"
    else:
        output_msg += f"\n- 💪 物理端（{readiness['physical_score']}）：基础体能受限，系统正在优先保障内脏修复，建议今日以低强度维护为主。"
    overall_sections.append(output_msg)

    # --- Mapping Chart Specific Insights ---
    chart_insights = {
        "sleep": f"一致性：{consist_status}。深睡占比 {avg_deep_pct}%。节律稳定性是修复效率的第一杠杆。",
        "hrv": f"状态：{audit['system_status']['hrv']['status']}。反映了系统对当前 {load_type} 的适应容量。",
        "activities": f"负载比 (ACWR): {load_ratio}。长期负荷状态：{audit['load_friction']['training_load']['status']}。",
        "body_battery": f"平均充能 +{avg_bb_charged}。起床峰值 {audit['recovery_loop']['body_battery']['peak']} 反映了回血的绝对厚度。",
        "stress": f"平均压力 {avg_stress}。{'高压力时长过长，需警惕自主神经系统过热' if avg_stress > 35 else '压力水平维持在健康代偿区间'}。"
    }

    # 4. Strategic Intervention: Personalized Action Plan
    recs = []
    # Sleep/Rhythm recs
    if consist_status != "优":
        recs.append("【锚定生物钟】检测到节律波动。建议即使在周末也保持固定起床时间，波动应控制在 ±30min 内。")
    if avg_deep_pct < 15:
        recs.append("【深睡强化】针对物理修复不足，建议睡前 2 小时停止蓝光摄入，并尝试将卧室温度调低至 18-20°C。")
    
    # Stress/Activity recs
    if load_type.startswith("被动") and avg_stress > 30:
        recs.append("【皮质醇对冲】您的压力多来源于非运动性焦虑。建议每日午后进行 15 分钟的呼吸冥想或 2km 的慢走，主动切换神经系统至副交感模式。")
    elif load_ratio > 1.4:
        recs.append("【防守性减载】当前负荷处于红区。接下来的 3 天内建议将运动强度降低 50%，优先补充蛋白质与充足睡眠以防免疫系统崩溃。")
    
    # Readiness recs
    if readiness['cognitive_score'] < 70:
        recs.append("【认知管理】今日大脑处理复杂信息的信噪比降低。建议将最具挑战性的战略决策或代码重构任务移至明早，今日以执行常规流程为主。")
    
    if not recs:
        recs.append("【持续优化】当前系统运行极佳。建议保持目前的训练与恢复节奏，可在周末尝试引入新的物理刺激。")
        
    intervention_msg = "【4. 战略干预：个性化健康行动建议】\n" + "\n".join([f"· {r}" for r in recs])
    overall_sections.append(intervention_msg)

    protocol_risk_map = {"GREEN": "低", "YELLOW": "中", "RED": "高", "ALERT": "危"}
    risk_label = protocol_risk_map.get(audit['action_protocol']['type'], '中')
    status_header = f"【专家审计：{period_str} | 生理风险：{risk_label}】"
    
    overall_combined = f"{status_header}\n\n" + "\n\n".join(overall_sections)
    
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
            {"title": "行动协议", "content": audit["action_protocol"]["move"]},
            {"title": "审计状态", "content": f"🧠 认知: {readiness['cognitive_score']} | 💪 体能: {readiness['physical_score']}"}
        ]
    }

def main():
    parser = argparse.ArgumentParser(description="Advanced Health Intelligence")
    parser.add_argument("analysis", choices=["flu_risk", "readiness", "insight_cn", "audit"], help="Analysis type")
    parser.add_argument("--days", type=int, default=7, help="Context window")
    
    args = parser.parse_args()
    
    client = get_client()
    if not client:
        print('{"error": "Not authenticated"}', file=sys.stderr)
        sys.exit(1)
        
    summary_data = fetch_summary(client, args.days)
    
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
