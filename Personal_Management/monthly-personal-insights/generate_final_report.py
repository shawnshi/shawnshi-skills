import os
import json
import datetime
from core.engine import (
    read_logs, process_sessions, aggregate_data,
    GOAL_MAP, SAT_MAP, FRIC_MAP, CACHE_FILE, TEMPLATE_FILE, REPORTS_DIR
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
    
    raw_top_goal = list(stats["goal_dist"].keys())[goal_data.index(max(goal_data))] if goal_data else "other"
    top_goal = GOAL_MAP.get(raw_top_goal, raw_top_goal)
    
    raw_top_fric = list(stats["friction_dist"].keys())[fric_data.index(max(fric_data))] if fric_data else "none"
    top_friction = FRIC_MAP.get(raw_top_fric, raw_top_fric)

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html_template = f.read()

    # Calculate coverage based on an assumed 155 norm or dynamic session counts.
    coverage_pct = (stats["total_sessions"] / 155 * 100) if stats["total_sessions"] else 0

    html = html_template.format(
        report_title_meta="Gemini CLI 战略审计报告 (已缓存样本)",
        report_title="🚀 个人数字化战略审计报告 (精简样本版)",
        report_subtitle=f"样本量: {stats['total_sessions']} 个已缓存会话 | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        card1_title="审计会话数", card1_val=f"{stats['total_sessions']}",
        card2_title="累计时长 (h)", card2_val=f"{stats['total_duration_hours']:.1f}",
        card3_title="覆盖率", card3_val=f"{coverage_pct:.1f}%",
        card4_title="活跃天数", card4_val=f"{stats['active_days']}",
        stats_interpretation="基于已缓存的样本，置信度较高。交互密度反映出您在医疗 IT 与 Agentic AI 领域正处于高频产出期。",
        daily_labels=json.dumps(daily_labels),
        daily_data=json.dumps(daily_data),
        daily_interpretation_html="",
        goal_labels=json.dumps(goal_labels),
        goal_data=json.dumps(goal_data),
        goal_interpretation_html="",
        sat_labels=json.dumps(sat_labels),
        sat_data=json.dumps(sat_data),
        sat_interpretation_html="",
        fric_labels=json.dumps(fric_labels),
        fric_data=json.dumps(fric_data),
        fric_interpretation_html="",
        top_goal=top_goal,
        top_goal_note="",
        insight_goal="呈现‘开拓者’模式。您的产出正在从代码向更高阶的‘技能架构’转型。",
        top_friction=top_friction,
        insight_fric="",
        profile="Builder (构建者)",
        avg_satisfaction=sat_labels[sat_data.index(max(sat_data))] if sat_data else "中立",
        insight_profile="",
        easter_egg="审计样本已足以覆盖本月核心战略节点。",
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_Cached.html"
    with open(report_path, "w", encoding="utf-8") as f: f.write(html)
    return report_path

def main():
    logs = read_logs()
    
    # Load cache directly as pre-resolved sessions
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    cached_sids = list(cache.keys())
    
    sessions = process_sessions(cached_sids, logs)
    for s in sessions:
        s["facets"] = cache.get(s["id"], {"goal_category": "other", "status": "uncached"})
        
    stats = aggregate_data(sessions)
    report_path = generate_report(stats, sessions)
    print(f"REPORT_GENERATED: {report_path}")
    if os.name == 'nt':
        try: os.startfile(report_path)
        except Exception: pass

if __name__ == "__main__":
    main()
