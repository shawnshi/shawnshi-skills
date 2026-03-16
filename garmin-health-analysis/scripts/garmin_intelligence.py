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
    prev_hrv = [d.get("last_night_avg") for d in hrv_data if d.get("last_night_avg") and d != latest_hrv_entry]
    prev_rhr = [d.get("resting_hr") for d in hr_data if d.get("resting_hr") and d != latest_hr_entry]
    prev_resp = [d.get("avg_respiration") for d in sleep_data if d.get("avg_respiration") and d != latest_sleep]
    
    if not prev_hrv or not prev_rhr:
        return {"status": "insufficient_baseline"}
        
    avg_hrv_baseline = statistics.median(prev_hrv) if prev_hrv else 0
    avg_rhr_baseline = statistics.median(prev_rhr) if prev_rhr else 0
    avg_resp_baseline = statistics.median(prev_resp) if prev_resp else 14.0
    
    current_hrv = latest_hrv_entry.get("last_night_avg") or avg_hrv_baseline
    current_rhr = latest_hr_entry.get("resting_hr") or avg_rhr_baseline
    current_resp = latest_sleep.get("avg_respiration") or avg_resp_baseline
    
    # Thresholds
    hrv_drop_pct = (avg_hrv_baseline - current_hrv) / avg_hrv_baseline * 100
    rhr_spike = current_rhr - avg_rhr_baseline
    resp_spike = current_resp - avg_resp_baseline
    
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

    # Calculate RHR Diff (Metabolic Pressure)
    latest_rhr = next((h.get("resting_hr") for h in reversed(hr_data) if h.get("resting_hr")), 0)
    prev_rhrs = [h.get("resting_hr") for h in hr_data if h.get("resting_hr") and h.get("resting_hr") != latest_rhr]
    baseline_rhr = statistics.median(prev_rhrs) if prev_rhrs else latest_rhr
    rhr_diff = latest_rhr - baseline_rhr if latest_rhr > 0 else 0

    # Calculate Sleep Debt
    target_sleep_s = 27000
    sleep_debt_s = sum(max(0, target_sleep_s - s.get("sleep_time_seconds", target_sleep_s)) for s in sleep_list[-3:] if s.get("sleep_time_seconds"))
    sleep_debt_h = sleep_debt_s / 3600

    # 2. Cognitive Readiness (Focus: REM, HRV, Stress)
    cog_rem_score = min(rem_pct / 20, 1.2) * 30
    cog_stress_score = max(0, (50 - avg_stress)) * 1
    cog_hrv_score = 40 if hrv_status == "BALANCED" else 20
    cognitive_score = cog_rem_score + cog_stress_score + cog_hrv_score + (sleep_score * 0.2)
    
    # Pessimistic Penalty: Sleep Debt
    if sleep_debt_h > 1.5:
        cognitive_score -= (sleep_debt_h * 5)
    cognitive_score = max(0, min(100, cognitive_score))

    # 3. Physical Readiness (Focus: Deep Sleep, Body Battery, RHR Stability)
    phy_deep_score = min(deep_pct / 15, 1.2) * 30
    phy_bb_score = (bb_peak / 100) * 40
    phy_hrv_score = 30 if hrv_status == "BALANCED" else 10
    physical_score = phy_deep_score + phy_bb_score + phy_hrv_score
    
    # Pessimistic Penalty: High RHR
    if rhr_diff > 3:
        physical_score *= 0.8
    physical_score = max(0, min(100, physical_score))

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
    baseline_rhr = statistics.median(prev_rhrs) if prev_rhrs else latest_rhr
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
    
    # Calculate rolling 3-day sleep debt (target 7.5h = 27000s)
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
    protocol_desc = "储备不足。保持低强度有氧 (Zone 2)，时长缩减 30%。优先补充镁/茶氨酸等神经修复剂。"
    move_type = "YELLOW"

    sleep_score = latest_sleep.get("sleep_score", 0) or 0

    if hrv_status_raw == "BALANCED" and sleep_score > 80 and bb_peak > 80 and sleep_debt_h < 1.5 and rhr_diff <= 2:
        protocol = "绿灯 (Prime) - 推极限"
        protocol_desc = "防线巩固。执行高强度间歇 (HIIT) 或长距离训练。认知冗余充足，适合进行破局性商业决策。"
        move_type = "GREEN"
    elif rhr_diff > 4 or (latest_stress.get("avg_stress", 0) > 45 and hrv_status_raw != "BALANCED") or sleep_debt_h > 4:
        protocol = "警报 (Infection/Overload) - 停机"
        protocol_desc = "系统边缘崩溃可能。身体正在对抗过度应激或病毒，且睡眠债务极高。禁止高要求决策与大规律运动，增加深度补水，建议补充维生素C/锌预防感染。"
        move_type = "ALERT"
    elif hrv_status_raw != "BALANCED" or sleep_score < 60 or sleep_debt_h > 2.5:
        protocol = "红灯 (Critical) - 主动刹车"
        protocol_desc = "系统代偿严重不足。禁止神经要求高的大型决策与高强度训练。仅允许主动恢复。必须限制今日的交叉会议与咖啡因摄入。"
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
    
    # 1. Sleep Consistency & Debt Audit
    sleep_data = summary_data.get("sleep", [])
    std_dev, consist_status = calculate_sleep_consistency(sleep_data)
    avg_deep_pct = audit["recovery_loop"]["sleep_architecture"]["deep_pct"]
    sleep_debt = audit["recovery_loop"]["sleep_architecture"].get("sleep_debt_h", 0)

    # 2. System Momentum (Delta Analysis - Half-Life Split)
    hr_data = summary_data.get("heart_rate", [])
    stress_data = summary_data.get("stress", [])
    momentum_status = "平稳运转"
    
    if len(hr_data) >= 4 and len(stress_data) >= 4:
        mid_point = len(hr_data) // 2
        first_half_rhr = statistics.median([h.get("resting_hr", 0) for h in hr_data[:mid_point] if h.get("resting_hr")])
        second_half_rhr = statistics.median([h.get("resting_hr", 0) for h in hr_data[mid_point:] if h.get("resting_hr")])
        
        first_half_stress = statistics.median([s.get("avg_stress", 0) for s in stress_data[:mid_point] if s.get("avg_stress")])
        second_half_stress = statistics.median([s.get("avg_stress", 0) for s in stress_data[mid_point:] if s.get("avg_stress")])
        
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

    # 3. Orthogonal Stress Stripping
    avg_stress = audit["load_friction"]["stress_score"]
    activities_data = summary_data.get("activities", [])
    
    # Calculate Total High Intensity Minutes for the period
    total_intensity_min = 0
    for act in activities_data:
        duration_s = act.get("duration", 0)
        total_intensity_min += (duration_s / 60)

    if total_intensity_min < 30 and avg_stress > 35:
        load_type = "🔴 纯认知燃烧 / 焦虑耗散 (无物理输出的高神经代价)"
    elif total_intensity_min >= 60 and avg_stress > 35:
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
    
    # Section 1: System Status & Momentum
    sys_msg = f"【1. 系统态势与动量 (System Momentum)】\n"
    sys_msg += f"· 动量向量：{momentum_status}。\n"
    sys_msg += f"· 摩擦定性：判定为『{load_type}』。"
    if "纯认知燃烧" in load_type:
        sys_msg += "\n  > 洞察：系统正在空耗神经递质（高压），但缺乏物理代谢（无运动）。这种脱节会导致皮质醇淤积，引发底层的慢性炎症。如果只靠静坐休息，无法打断这一热力学死锁。"
    elif "双轨满载" in load_type:
        sys_msg += "\n  > 警告：中枢神经系统正在承受『战略业务推演 + 物理强行破坏』的双重挤压，处于极度耗散状态。系统的免疫防线极为脆弱，极易在此阶段触发 Garmin Flu。"
    elif "筑底企稳" in momentum_status:
        sys_msg += "\n  > 洞察：当前生理数据呈现低波动的收敛态，这是重大战役前的完美储备期。但也需警惕过度放松导致的“失练 (Detraining)”效应，代谢引擎不可彻底熄火。"
    overall_sections.append(sys_msg)

    # Section 2: Input & Rhythm
    consist_msg = f"【2. 恢复环路审计 (Recovery Loop)】\n"
    consist_msg += f"· 节律稳定性：{consist_status} (标准差 {std_dev}h)。"
    if consist_status != "优":
        consist_msg += "\n  > 破窗效应：强烈的“社会时差”导致生物钟漂移。节律的不规律直接切断了内分泌系统的黄金修复窗口（尤其是夜间生长激素与褪黑素的耦协），这是拖垮系统长期 ROI 的最大隐性漏洞。"
    else:
        consist_msg += "\n  > 坚固底座：生物钟锚定极佳，为前额叶的深度清洗与内脏修复提供了坚实的物理时间窗口。"
    
    consist_msg += f"\n· 结构解剖：深睡占比 {avg_deep_pct}%。"
    if avg_deep_pct < 15:
        consist_msg += "\n  > 物理坍塌：深睡(<15%)意味着系统重构陷入停滞，内脏与肌肉层面的微损伤未能被修复，导致次日基础体能受限，甚至表现为晨起心率异常。"
    else:
        consist_msg += "\n  > 重构达标：物理底座修复达标，确保了肌肉韧性与神经弹性。"
        
    consist_msg += f"\n· 储备赤字：当前连续睡眠债务 {sleep_debt}h。"
    if sleep_debt > 1.5:
        consist_msg += f"\n  > 债务危机：累积的 {sleep_debt}h 负债已实质性击穿神经缓冲垫。此时如果在业务上获得认知高分，往往是依靠交感神经与肾上腺素硬撑，随时面临断崖式崩溃。"
    overall_sections.append(consist_msg)

    # Section 3: Readiness
    output_msg = f"【3. 执行带宽 (Execution Bandwidth)】\n"
    output_msg += f"· 综合执行力：{readiness['score']}/100\n"
    output_msg += f"· 🧠 认知带宽 ({readiness['cognitive_score']})："
    if readiness['cognitive_score'] > 80:
        output_msg += "高频逻辑计算可用，前额叶皮层未受抑制。适宜全功率执行：系统架构设计、复杂商业博弈、非共识型战略决断。"
    elif readiness['cognitive_score'] > 60:
        output_msg += "算力受限，逻辑推演能力下降。极易触发『讨好性偏差』与局部视野狭窄。建议降级工作流：仅处理已有框架内的文档编写与常规邮件。"
    else:
        output_msg += "认知宕机。严禁任何战略性决策，强行工作将带来极高的系统错误率与后期的“架构重构成本”。"
        
    output_msg += f"\n· 💪 物理防线 ({readiness['physical_score']})："
    if readiness['physical_score'] > 80:
        output_msg += "内脏/神经肌肉冗余充足。可承受极强环境压力（如：红眼航班差旅、连续多场高压会战）或高强度物理训练。"
    else:
        output_msg += "防线脆弱。必须把剩余能量全部让渡给免疫系统，取消一切非必要的高强度体能消耗，坚决防御突发感染。"
    overall_sections.append(output_msg)

    # Section 4: Tactical Directives (Mentat Level)
    recs = []
    
    # 1. 调度
    if sleep_debt > 1.5 or readiness['cognitive_score'] < 70:
        recs.append("📅【日程管控 - 降级】背负睡眠债务且认知受限。今日必须砍掉/延期 30% 的非关键交叉会议。严禁执行底层代码重构，全面转向“只读模式 (Read-only)”。")
    elif readiness['score'] >= 85:
        recs.append("📅【日程管控 - 强攻】系统信噪比极高。解除一切防御限制，将最棘手的战略卡点、技术债务清算以及高难度对话安排在今日核心时段。")

    # 2. 物理
    if "纯认知燃烧" in load_type:
        recs.append("🏃‍♂️【物理干预 - 强制负熵】内分泌已死锁。今日必须作为 [P0] 级任务，挂载 30-40 分钟 Zone 2 低心率有氧（如快走/轻松骑行），利用肌肉泵血强行剥离皮质醇。")
    elif "双轨满载" in load_type or readiness['physical_score'] < 60:
        recs.append("🏃‍♂️【物理干预 - 绝对防御】负荷溢出/防线脆弱。取消一切力量训练或高心率间歇，仅允许进行 15 分钟的静态拉伸或筋膜枪放松。")

    # 3. 生化与环境
    if avg_deep_pct < 15:
        recs.append("💊【生化环境 - 深度冷却】深睡架构坍塌。今晚 20:00 后实施强硬数字隔离（断绝蓝光），核心体温须在入睡前完成物理降温（如：热水澡后进入设定为 19°C 的冷气室）。")
    if momentum_status.startswith("🔴"):
        recs.append("💊【生化环境 - 止损熔断】检测到滑向热寂的动量。立即补充 500mg 维生素C + 锌对抗底层炎症；晚间增加 200mg 镁或茶氨酸，强行平抑亢进的交感神经。")

    if not recs:
        recs.append("🟢【维稳运转】各项指标呈良性收敛。维持现有作息、物理训练与饮食结构，可适当引入微量的不确定性刺激（如：轻度冷水浴或改变一次训练模式）。")
        
    intervention_msg = "【4. 资源调度指令 (Tactical Directives)】\n" + "\n".join([f"· {r}" for r in recs])
    overall_sections.append(intervention_msg)

    protocol_risk_map = {"GREEN": "推极限", "YELLOW": "维稳", "RED": "防御", "ALERT": "停机"}
    risk_label = protocol_risk_map.get(audit['action_protocol']['type'], '未知')
    status_header = f"【CMO 战略审计简报：{period_str} | 行动代号：{risk_label}】"
    
    overall_combined = f"{status_header}\n\n" + "\n\n".join(overall_sections)

    # --- Mapping Chart Specific Insights ---
    chart_insights = {
        "sleep": f"债务：{sleep_debt}h。深睡占比 {avg_deep_pct}%。任何挤压深睡的行为均视为对长期资产的破坏。",
        "hrv": f"状态：{audit['system_status']['hrv']['status']}。系统动量：{momentum_status.split(' ')[1]}。",
        "activities": f"物理耗散：{round(total_intensity_min)} min。负荷定性：{load_type.split(' ')[1]}。",
        "body_battery": f"峰谷极差：平均峰值 {audit['recovery_loop']['body_battery']['peak']}，谷值 {audit['recovery_loop']['body_battery']['lowest']}。",
        "stress": f"定性：{load_type.split(' ')[1]}。"
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
