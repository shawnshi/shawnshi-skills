import os
import json
import datetime
from core.engine import (
    get_session_list, read_logs, process_sessions, extract_facets_builtin, aggregate_data,
    GOAL_MAP, SAT_MAP, FRIC_MAP, PROFILE_MAP, TEMPLATE_FILE, REPORTS_DIR
)

def generate_report(stats, sessions):
    daily_sorted = sorted(stats["daily_activity"].items())
    daily_labels = [d[0] for d in daily_sorted]
    daily_data = [d[1] for d in daily_sorted]
    
    goal_labels = [GOAL_MAP.get(k, k) for k in stats["goal_dist"].keys()]
    goal_data = list(stats["goal_dist"].values())
    
    sat_labels = [SAT_MAP.get(k, k) for k in stats["satisfaction_dist"].keys()]
    sat_data = list(stats["satisfaction_dist"].values())
    
    fric_labels = [FRIC_MAP.get(k, k) for k in stats["friction_dist"].keys()]
    fric_data = list(stats["friction_dist"].values())
    
    # --- Deep Interpretation Logic ---
    total = stats["total_sessions"]
    active = stats["active_days"]
    avg_msg_per_session = stats["total_messages"] / total if total > 0 else 0
    hours_per_active_day = stats["total_duration_hours"] / active if active > 0 else 0
    
    if active > 20:
        stats_interp = f"呈现典型的‘数字原生’特征。交互密度极高（日均 {hours_per_active_day:.1f} 小时），表明 AI 已非辅助工具，而是您思维架构的实时延伸。当前系统熵值受控，但需警惕过度依赖导致的认知带宽收缩。"
    elif total > 40:
        stats_interp = f"高频碎片化协作模式。平均每会话消息数仅 {avg_msg_per_session:.1f} 条，暗示您倾向于将 AI 用于快速验证或微小任务。建议整合相关需求进入‘深度会话’，以利用大模型的长上下文推理优势。"
    else:
        stats_interp = "任务驱动型协作。交互主要集中在特定交付目标上，系统运行负载分布均衡，处于典型的‘杠杆利用’阶段。"

    volatility = max(daily_data) - min(daily_data) if daily_data else 0
    if volatility > 8:
        daily_interp = "典型的‘潮汐式’工作流。剧烈的波动反映出您正处于从‘战略规划’到‘高强度工程交付’的快速切换中。这种模式心流质量极高，但二阶效应是系统维护可能在高峰期被忽视，导致后续摩擦。"
    else:
        daily_interp = "线性平稳走势。这是一种极度自律的‘架构师节奏’，表明项目边界清晰，需求涌现速度与处理速度完全匹配，系统熵增速度处于历史低位。"

    raw_top_goal = list(stats["goal_dist"].keys())[goal_data.index(max(goal_data))] if goal_data else "other"
    top_goal = GOAL_MAP.get(raw_top_goal, raw_top_goal)
    top_goal_pct = (max(goal_data) / stats["total_sessions"] * 100) if stats["total_sessions"] else 0
    
    if raw_top_goal in ["fix_bug", "debug_investigate"]:
        goal_interp = f"呈现‘防御性堡垒’特征。重心在 {top_goal} 表明当前工具链存在明显的‘逻辑债务’。您正在通过高频的人工干预来维持系统稳定性，而非在边界上扩张。"
    elif raw_top_goal in ["implement_feature", "write_script_tool"]:
        goal_interp = f"纯粹的‘开拓者’模式。{top_goal} 的高占比意味着您正处于数字资产爆发增长期。当前最重要的不是修复，而是‘架构原型’的快速固化。"
    elif raw_top_goal in ["refactor_code"]:
        goal_interp = "处于‘系统性熵减’阶段。您正在通过重构消除复杂的过去，预示下阶段的高效交付。"
    else:
        goal_interp = "多维意图混合。任务目标在多端均匀分布，表明您正在管理复杂的生命周期项目，挑战在调度成本。"

    avg_sat_raw = list(stats["satisfaction_dist"].keys())[sat_data.index(max(sat_data))] if sat_data else "neutral"
    if avg_sat_raw in ["happy", "delighted"]:
        sat_interp = "‘人机合一’的心流。当前的指令与模型能力的匹配度已达最优，应固化当前的协作范式。"
    elif avg_sat_raw in ["frustrated", "annoyed"]:
        sat_interp = "出现显著的认知摩擦。模型对复杂指令有漂移，需彻底的系统性审计与修正。"
    else:
        sat_interp = "‘稳态协作’体验。交互符合预期，但尚未充分探索边缘和高级场景优势。"

    raw_top_fric = list(stats["friction_dist"].keys())[fric_data.index(max(fric_data))] if fric_data else "none"
    top_friction = FRIC_MAP.get(raw_top_fric, raw_top_fric)
    if raw_top_fric == "none":
        fric_interp = "无阻力运行。系统阻力几乎消失，重点应放至高复杂度压力测试验证系统上限。"
    elif raw_top_fric == "misunderstood_request":
        fric_interp = "‘语义鸿沟’为主因。需要增加行业术语及上下文补全。"
    elif raw_top_fric == "buggy_code":
        fric_interp = "‘逻辑健壮性’阻力。产出快但纠错成本极高。应强制推进先测后写的开发循环。"
    else:
        fric_interp = f"检测到 {top_friction} 引发损耗。该类低价值损耗应快速根治屏蔽。"

    if "构建" in goal_interp or "开拓" in goal_interp:
        insight_goal = "这标志着您正处于一个关键的‘生产力跃迁’期。建议将本月产出的核心逻辑抽象为通用技能。"
    else:
        insight_goal = "当前处于‘战略相持阶段’。建议进行一次‘技术债清算’，集中解决高频报错点，释放带宽。"

    if raw_top_fric != "none":
        insight_fric = f"针对 {top_friction} 高频耗损，请通过补充前置校验约束将错误拦截于输出之前。"
    else:
        insight_fric = "当前的流畅度宝贵。建议开始重度探索多 Agent 层递协作。"
    
    if raw_top_goal in ["debug_investigate", "fix_bug"]: profile_key = "Crisis Manager"
    elif raw_top_goal in ["implement_feature", "write_script_tool"]: profile_key = "Builder"
    elif raw_top_goal in ["research", "analyze_data"]: profile_key = "Explorer"
    else: profile_key = "Steady Operator"
    profile = PROFILE_MAP.get(profile_key, profile_key)
    
    if profile_key == "Builder": insight_profile = "您是‘结果导向型’构建者。建议强化对齐交付基准。"
    elif profile_key == "Explorer": insight_profile = "您是‘认知导向型’探险家。通过扩展搜查插件来深化信息差套利。"
    else: insight_profile = "您倾向稳定精准控制。建议细化防误操作等底层保障约束。"

    easter_egg = "本月暂无特定成功高光记录。"
    memorable = [s for s in sessions if s["facets"].get("success_type") not in ["none", None]]
    if memorable:
        success_title = memorable[0]['title']
        success_type = memorable[0]['facets'].get('success_type', '')
        easter_egg = f"在会话 <strong>'{success_title}'</strong> 中，实现了极高的交付结晶 ({success_type})，心流卓越。"

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html_template = f.read()

    html = html_template.format(
        report_title_meta="Gemini CLI 战略审计报告",
        report_title="🚀 个人数字化战略审计报告",
        report_subtitle=f"周期: {daily_labels[0] if daily_labels else 'N/A'} 至 {daily_labels[-1] if daily_labels else 'N/A'} | 状态: 已归档",
        card1_title="总会话数", card1_val=f"{stats['total_sessions']}",
        card2_title="累计时长 (h)", card2_val=f"{stats['total_duration_hours']:.1f}",
        card3_title="Git 提交", card3_val=f"{stats['git_commits']}",
        card4_title="活跃天数", card4_val=f"{stats['active_days']}/30",
        stats_interpretation=stats_interp,
        daily_labels=json.dumps(daily_labels),
        daily_data=json.dumps(daily_data),
        daily_interpretation_html=f'<div class="interpretation"><strong>走势分析：</strong> {daily_interp}</div>',
        goal_labels=json.dumps(goal_labels),
        goal_data=json.dumps(goal_data),
        goal_interpretation_html=f'<div class="interpretation"><strong>意图拆解：</strong> {goal_interp}</div>',
        sat_labels=json.dumps(sat_labels),
        sat_data=json.dumps(sat_data),
        sat_interpretation_html=f'<div class="interpretation"><strong>心流评价：</strong> {sat_interp}</div>',
        fric_labels=json.dumps(fric_labels),
        fric_data=json.dumps(fric_data),
        fric_interpretation_html=f'<div class="interpretation"><strong>阻力诊断：</strong> {fric_interp}</div>',
        top_goal=top_goal,
        top_goal_note=f"，占总会话的 {top_goal_pct:.1f}%",
        insight_goal=insight_goal,
        top_friction=top_friction,
        insight_fric=insight_fric,
        profile=profile,
        avg_satisfaction=sat_labels[sat_data.index(max(sat_data))] if sat_data else "中立",
        insight_profile=insight_profile,
        easter_egg=easter_egg,
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit.html"
    with open(report_path, "w", encoding="utf-8") as f: f.write(html)
    return report_path

def main():
    print("🚀 正在通过 Gemini CLI 启动战略审计...")
    raw_sessions = get_session_list()
    logs = read_logs()
    sessions = process_sessions(raw_sessions, logs)
    
    print(f"正在分析 {len(sessions)} 个会话（内置模型加速中）...")
    sessions = extract_facets_builtin(sessions)
    
    stats = aggregate_data(sessions)
    report_path = generate_report(stats, sessions)
    
    print(f"\n✅ 审计完成！")
    print(f"报告已生成至: {report_path}")
    
    if os.name == 'nt':
        print("正在为您打开报告...")
        os.startfile(report_path)

if __name__ == "__main__":
    main()
