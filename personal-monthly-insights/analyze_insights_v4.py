import os
import json
import datetime
import argparse
from core.engine import (
    get_session_list, read_logs, process_sessions, aggregate_data,
    sync_to_memory, PERIOD_MAP, TEMPLATE_FILE, REPORTS_DIR, GEMINI_ROOT
)

def format_narrative_areas(data):
    """Format project areas analysis into HTML."""
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    areas = data.get("areas", [])
    if not areas: return "<p>暂无项目领域数据</p>"
    html = "<ul>"
    for a in areas:
        html += f'<li><strong>{a.get("name","")}</strong> ({a.get("session_count",0)} sessions) — {a.get("description","")}</li>'
    return html + "</ul>"

def format_narrative_style(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    return f'<p>{data.get("narrative","")}</p><p><strong>关键模式：</strong>{data.get("key_pattern","")}</p>'

def format_narrative_works(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    wfs = data.get("impressive_workflows", [])
    html = f'<p>{data.get("intro","")}</p><ul>'
    for w in wfs:
        html += f'<li><strong>{w.get("title","")}</strong> — {w.get("description","")}</li>'
    return html + "</ul>"

def format_narrative_friction(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    cats = data.get("categories", [])
    html = f'<p>{data.get("intro","")}</p>'
    for c in cats:
        examples = ", ".join(c.get("examples", []))
        html += f'<h3>{c.get("category","")}</h3><p>{c.get("description","")}</p><p style="font-size:12px;color:#6c8aff;">例: {examples}</p>'
    return html

def format_narrative_suggestions(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    html = "<h3>🔧 配置建议</h3><ul>"
    for c in data.get("config_additions", []):
        html += f'<li><code>{c.get("addition","")}</code> — {c.get("why","")}</li>'
    html += "</ul><h3>📋 使用模式</h3><ul>"
    for u in data.get("usage_patterns", []):
        html += f'<li><strong>{u.get("title","")}</strong>: {u.get("detail","")}</li>'
    return html + "</ul>"

def format_narrative_horizon(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    ops = data.get("opportunities", [])
    html = f'<p>{data.get("intro","")}</p><ul>'
    for o in ops:
        html += f'<li><strong>{o.get("title","")}</strong> — {o.get("whats_possible","")}<br><em>{o.get("how_to_try","")}</em></li>'
    return html + "</ul>"

def format_narrative_fun(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return "<p>暂无趣味时刻数据</p>"
    return f'<h3>{data.get("headline","")}</h3><p>{data.get("detail","")}</p>'

def format_narrative_behavioral_analysis(data):
    if isinstance(data, str): return f"<p>{data}</p>"
    if not isinstance(data, dict): return ""
    pts = data.get("points", [])
    overall = data.get("overall", "")
    html = f'<p>{data.get("intro","")}</p>'
    if overall:
        html += f'<div style="background: var(--surface-2); padding: 16px; border-radius: 8px; margin-bottom: 20px; border-left: 3px solid var(--success);"><strong>🌟 总体认知评估：</strong>{overall}</div>'
    return html

def generate_report(stats, sessions, insights):
    period_label = stats.get("period_label", "N/A")
    
    # Chart data (gracefully handle missing facet distributions which were removed in V8.0)
    daily_sorted = sorted(stats.get("daily_activity", {}).items())
    daily_labels = [d[0] for d in daily_sorted]
    daily_data = [d[1] for d in daily_sorted]
    
    goal_dist = insights.get("distributions", {}).get("goal_dist", {"综合": 1})
    goal_labels = list(goal_dist.keys())
    goal_data = list(goal_dist.values())
    
    sat_dist = insights.get("distributions", {}).get("satisfaction_dist", {"未知": 1})
    sat_labels = list(sat_dist.keys())
    sat_data = list(sat_dist.values())
    
    fric_dist = insights.get("distributions", {}).get("friction_dist", {"无记录": 1})
    fric_labels = list(fric_dist.keys())
    fric_data = list(fric_dist.values())
    
    emotion_dist = insights.get("distributions", {}).get("emotional_tone_dist", {"中性": 1})
    emotion_labels = list(emotion_dist.keys())
    emotion_data = list(emotion_dist.values())
    
    helpfulness_dist = insights.get("distributions", {}).get("helpfulness_dist", {"中等": 1})
    helpfulness_labels = list(helpfulness_dist.keys())
    helpfulness_data = list(helpfulness_dist.values())
    
    session_type_dist = insights.get("distributions", {}).get("session_type_dist", {"混合": 1})
    session_type_labels = list(session_type_dist.keys())
    session_type_data = list(session_type_dist.values())
    
    # Topic cloud HTML
    topic_cloud = insights.get("distributions", {}).get("topic_cloud", {"Agentic": 1})
    max_count = max(topic_cloud.values()) if topic_cloud else 1
    topic_cloud_html = " ".join([
        f'<span class="topic-tag{" hot" if v >= max_count * 0.6 else ""}">{k} ({v})</span>'
        for k, v in topic_cloud.items()
    ]) if topic_cloud else '<span class="topic-tag">暂无主题数据</span>'

    # Radar data fallback
    radar_labels = ["完成率", "满意度", "低摩擦", "AI有效性", "情感韧性", "会话深度"]
    radar_data = insights.get("distributions", {}).get("radar_data", [80, 80, 80, 80, 80, 80])
    
    # Peak hour display
    peak_hours = stats.get("peak_hours", {})
    peak_hour_str = f'{list(peak_hours.keys())[0]}:00' if peak_hours else "N/A"

    glance = insights.get("at_a_glance", {})
    if not isinstance(glance, dict):
        glance = {"whats_working": str(glance), "whats_hindering": "", "quick_wins": "", "ambitious_workflows": ""}

    # Build narrative HTML
    narrative_html = {
        "project_areas": format_narrative_areas(insights.get("project_areas")),
        "interaction_style": format_narrative_style(insights.get("interaction_style")),
        "what_works": format_narrative_works(insights.get("what_works")),
        "friction": format_narrative_friction(insights.get("friction_analysis")),
        "suggestions": format_narrative_suggestions(insights.get("suggestions")),
        "horizon": format_narrative_horizon(insights.get("on_the_horizon")),
        "fun": format_narrative_fun(insights.get("fun_ending")),
        "behavioral": format_narrative_behavioral_analysis(insights.get("behavioral_analysis")),
    }

    # Extract individual chart analyses
    chart_analyses = [""] * 8
    points = insights.get("behavioral_analysis", {}).get("points", [])
    for i in range(min(len(points), 8)):
        title = points[i].get("title", "")
        desc = points[i].get("description", "")
        chart_analyses[i] = f'<strong>{title}</strong>{desc}'
        
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html_template = f.read()

    replacements = {
        "report_title_meta": f"战略审计报告 - {period_label}",
        "report_title": f"🦅 个人数字化战略审计报告 ({period_label})",
        "report_subtitle": f"数据区间: {daily_labels[0] if daily_labels else 'N/A'} → {datetime.date.today().isoformat()} | 审计级别: Agentic Workflow V8.0",
        "glance_working": glance.get("whats_working", "") if isinstance(glance, dict) else "",
        "glance_hindering": glance.get("whats_hindering", "") if isinstance(glance, dict) else "",
        "glance_quick_wins": glance.get("quick_wins", "") if isinstance(glance, dict) else "",
        "glance_ambitious": glance.get("ambitious_workflows", "") if isinstance(glance, dict) else "",
        "card_sessions": str(stats.get("total_sessions", 0)),
        "card_hours": f'{stats.get("total_duration_hours", 0):.1f}',
        "card_commits": str(stats.get("git_commits", 0)),
        "card_active_days": str(stats.get("active_days", 0)),
        "card_streak": str(stats.get("max_streak", 0)),
        "card_peak_hour": peak_hour_str,
        "daily_labels": json.dumps(daily_labels), "daily_data": json.dumps(daily_data),
        "goal_labels": json.dumps(goal_labels), "goal_data": json.dumps(goal_data),
        "sat_labels": json.dumps(sat_labels), "sat_data": json.dumps(sat_data),
        "fric_labels": json.dumps(fric_labels), "fric_data": json.dumps(fric_data),
        "emotion_labels": json.dumps(emotion_labels), "emotion_data": json.dumps(emotion_data),
        "radar_labels": json.dumps(radar_labels), "radar_data": json.dumps(radar_data),
        "helpfulness_labels": json.dumps(helpfulness_labels), "helpfulness_data": json.dumps(helpfulness_data),
        "session_type_labels": json.dumps(session_type_labels), "session_type_data": json.dumps(session_type_data),
        "topic_cloud_html": topic_cloud_html,
        "narrative_project_areas": narrative_html["project_areas"],
        "narrative_interaction_style": narrative_html["interaction_style"],
        "narrative_what_works": narrative_html["what_works"],
        "narrative_friction": narrative_html["friction"],
        "narrative_suggestions": narrative_html["suggestions"],
        "narrative_horizon": narrative_html["horizon"],
        "narrative_fun": narrative_html["fun"],
        "narrative_behavioral": narrative_html["behavioral"],
        "analysis_daily": chart_analyses[0],
        "analysis_goal": chart_analyses[1],
        "analysis_sat": chart_analyses[2],
        "analysis_fric": chart_analyses[3],
        "analysis_emotion": chart_analyses[4],
        "analysis_radar": chart_analyses[5],
        "analysis_helpfulness": chart_analyses[6],
        "analysis_session_type": chart_analyses[7],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    html = html_template
    for key, value in replacements.items():
        html = html.replace(f"%%{key}%%", str(value))
        html = html.replace(f"%% {key} %%", str(value))
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.html"
    with open(report_path, "w", encoding="utf-8") as f: f.write(html)
    
    # Markdown export
    md_report = f"""# 战略审计报告 ({period_label})
> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | v8.0 Agentic Edition

## At a Glance
- **What's Working**: {glance.get('whats_working', '')}
- **What's Hindering**: {glance.get('whats_hindering', '')}
- **Quick Wins**: {glance.get('quick_wins', '')}
- **Ambitious Workflows**: {glance.get('ambitious_workflows', '')}

## 核心指标
| 指标 | 值 |
|---|---|
| 协作会话 | {stats.get('total_sessions', 0)} |
| 累计时长 | {stats.get('total_duration_hours', 0):.1f}h |
| Git 提交 | {stats.get('git_commits', 0)} |
| 活跃天数 | {stats.get('active_days', 0)} |
| 最长连续 | {stats.get('max_streak', 0)}d |
"""
    md_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.md"
    with open(md_path, "w", encoding="utf-8") as f: f.write(md_report)
    print(f"  📄 Markdown 版本: {md_path.name}")
    
    # Auto-sync to memory
    sync_fragment = f"""
## [Strategic Audit: {period_label} - {datetime.date.today().isoformat()}]
- **协作效能**: {stats.get('total_duration_hours', 0):.1f}h / {stats.get('total_sessions', 0)} 会话 / {stats.get('git_commits', 0)} Git 提交
- **At a Glance**: {glance.get('whats_working', '')[:100]}
- **Quick Wins**: {glance.get('quick_wins', '')[:100]}
"""
    sync_to_memory(sync_fragment)
    
    return report_path

def main():
    parser = argparse.ArgumentParser(description='Strategic Audit Data Pump & Renderer v8.0')
    parser.add_argument('--period', default='30d', choices=list(PERIOD_MAP.keys()),
                        help='Analysis period: 7d, 30d, 90d, year (default: 30d)')
    parser.add_argument('--extract-only', action='store_true',
                        help='Only extract session raw data and physical metrics (Agentic V8.0)')
    parser.add_argument('--render', action='store_true',
                        help='Render final HTML report from agent insights (Agentic V8.0)')
    parser.add_argument('--agent-file', type=str, default='',
                        help='Path to the agent generated JSON file with insights')
    args = parser.parse_args()
    
    if not args.extract_only and not args.render:
        print("❌ 必须指定 --extract-only 或 --render 模式 (Agentic V8.0)")
        return
        
    period_label = f"过去 {PERIOD_MAP[args.period]} 天" if args.period != 'year' else f"{datetime.date.today().year} 年度"
    
    if args.extract_only:
        print(f"🚀 启动物理数据泵 ({period_label})...")
        raw_sessions = get_session_list()
        logs = read_logs()
        sessions = process_sessions(raw_sessions, logs)
        stats = aggregate_data(sessions, period=args.period)
        
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = REPORTS_DIR / f"raw_metrics_{args.period}.json"
        
        output_data = {
            "stats": stats,
            "sessions": sessions
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 物理数据提取完毕，等待 Agent 认知推演。数据位置: {out_file}")
        
    elif args.render:
        if not args.agent_file or not os.path.exists(args.agent_file):
            print("❌ 必须提供 --agent-file 来指定 agent 推理出的洞察结果文件")
            return
            
        # load raw data to get basic stats
        raw_file = REPORTS_DIR / f"raw_metrics_{args.period}.json"
        
        if os.path.exists(raw_file):
            with open(raw_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                stats = raw_data.get("stats", {})
                sessions = raw_data.get("sessions", [])
        else:
            print("⚠️ 未找到 raw_metrics 数据，仅使用 mock 框架渲染")
            stats = {"period_label": period_label}
            sessions = []
            
        with open(args.agent_file, "r", encoding="utf-8") as f:
            insights = json.load(f)
            
        report_path = generate_report(stats, sessions, insights)
        print(f"\n✅ 审计 HTML/MD 生成完成！报告位置: {report_path}")

        # Try to open only if configured to do so
        if os.name == 'nt':
            try: os.startfile(report_path)
            except Exception: pass

if __name__ == "__main__":
    main()
