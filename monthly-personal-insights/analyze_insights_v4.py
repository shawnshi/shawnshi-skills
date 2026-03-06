import os
import json
import datetime
import argparse
from core.engine import (
    get_session_list, read_logs, process_sessions, extract_facets_builtin, aggregate_data,
    run_specialized_analyses, generate_executive_summary, sync_to_memory, PERIOD_MAP,
    GOAL_MAP, SAT_MAP, FRIC_MAP, EMOTION_MAP, HELPFULNESS_MAP, SESSION_TYPE_MAP,
    TEMPLATE_FILE, REPORTS_DIR, GEMINI_ROOT
)

def format_narrative_areas(data):
    """Format project areas analysis into HTML."""
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    areas = data.get("areas", [])
    if not areas: return "<p>暂无项目领域数据</p>"
    html = "<ul>"
    for a in areas:
        html += f'<li><strong>{a.get("name","")}</strong> ({a.get("session_count",0)} sessions) — {a.get("description","")}</li>'
    return html + "</ul>"

def format_narrative_style(data):
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    return f'<p>{data.get("narrative","")}</p><p><strong>关键模式：</strong>{data.get("key_pattern","")}</p>'

def format_narrative_works(data):
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    wfs = data.get("impressive_workflows", [])
    html = f'<p>{data.get("intro","")}</p><ul>'
    for w in wfs:
        html += f'<li><strong>{w.get("title","")}</strong> — {w.get("description","")}</li>'
    return html + "</ul>"

def format_narrative_friction(data):
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    cats = data.get("categories", [])
    html = f'<p>{data.get("intro","")}</p>'
    for c in cats:
        examples = ", ".join(c.get("examples", []))
        html += f'<h3>{c.get("category","")}</h3><p>{c.get("description","")}</p><p style="font-size:12px;color:#6c8aff;">例: {examples}</p>'
    return html

def format_narrative_suggestions(data):
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    html = "<h3>🔧 配置建议</h3><ul>"
    for c in data.get("config_additions", []):
        html += f'<li><code>{c.get("addition","")}</code> — {c.get("why","")}</li>'
    html += "</ul><h3>📋 使用模式</h3><ul>"
    for u in data.get("usage_patterns", []):
        html += f'<li><strong>{u.get("title","")}</strong>: {u.get("detail","")}</li>'
    return html + "</ul>"

def format_narrative_horizon(data):
    if not isinstance(data, dict): return "<p>分析数据暂不可用</p>"
    ops = data.get("opportunities", [])
    html = f'<p>{data.get("intro","")}</p><ul>'
    for o in ops:
        html += f'<li><strong>{o.get("title","")}</strong> — {o.get("whats_possible","")}<br><em>{o.get("how_to_try","")}</em></li>'
    return html + "</ul>"

def format_narrative_fun(data):
    if not isinstance(data, dict): return "<p>暂无趣味时刻</p>"
    return f'<h3>{data.get("headline","")}</h3><p>{data.get("detail","")}</p>'

def generate_report(stats, sessions):
    period_label = stats.get("period_label", "N/A")
    
    # Chart data
    daily_sorted = sorted(stats["daily_activity"].items())
    daily_labels = [d[0] for d in daily_sorted]
    daily_data = [d[1] for d in daily_sorted]
    goal_labels = [GOAL_MAP.get(k, k) for k in stats["goal_dist"].keys()]
    goal_data = list(stats["goal_dist"].values())
    sat_labels = [SAT_MAP.get(k, k) for k in stats["satisfaction_dist"].keys()]
    sat_data = list(stats["satisfaction_dist"].values())
    fric_labels = [FRIC_MAP.get(k, k) for k in stats["friction_dist"].keys()]
    fric_data = list(stats["friction_dist"].values())
    emotion_labels = [EMOTION_MAP.get(k, k) for k in stats["emotional_tone_dist"].keys()]
    emotion_data = list(stats["emotional_tone_dist"].values())
    helpfulness_labels = [HELPFULNESS_MAP.get(k, k) for k in stats["helpfulness_dist"].keys()]
    helpfulness_data = list(stats["helpfulness_dist"].values())
    session_type_labels = [SESSION_TYPE_MAP.get(k, k) for k in stats["session_type_dist"].keys()]
    session_type_data = list(stats["session_type_dist"].values())
    
    # Topic cloud HTML
    topic_cloud = stats.get("topic_cloud", {})
    max_count = max(topic_cloud.values()) if topic_cloud else 1
    topic_cloud_html = " ".join([
        f'<span class="topic-tag{" hot" if v >= max_count * 0.6 else ""}">{k} ({v})</span>'
        for k, v in topic_cloud.items()
    ]) if topic_cloud else '<span class="topic-tag">暂无主题数据</span>'

    # Radar data
    total = stats["total_sessions"] or 1
    def pct(dist, keys):
        total_d = sum(dist.values()) or 1
        return min(100, int(sum(dist.get(k, 0) for k in keys) / total_d * 100))
    
    emo_dist = stats["emotional_tone_dist"]
    pos_emo = sum(emo_dist.get(k, 0) for k in ["focused", "flow", "excited"])
    neg_emo = sum(emo_dist.get(k, 0) for k in ["anxious", "frustrated"])
    emo_ratio = pos_emo / max(pos_emo + neg_emo, 1) * 100
    
    radar_labels = ["完成率", "满意度", "低摩擦", "AI有效性", "情感韧性", "会话深度"]
    radar_data = [
        pct(stats["outcome_dist"], ["fully_achieved", "mostly_achieved"]),
        pct(stats["satisfaction_dist"], ["happy", "satisfied", "likely_satisfied"]),
        100 - min(100, int(sum(stats["friction_dist"].values()) / total * 100)),
        pct(stats["helpfulness_dist"], ["very_helpful", "essential"]),
        int(emo_ratio),
        pct(stats["session_type_dist"], ["multi_task", "iterative_refinement"]),
    ]
    
    # Peak hour display
    peak_hours = stats.get("peak_hours", {})
    peak_hour_str = f'{list(peak_hours.keys())[0]}:00' if peak_hours else "N/A"

    # --- P0 Optimization: Cache Check ---
    cache_key = f"{datetime.date.today().isoformat()}_{period_label}_{stats['total_sessions']}"
    cache_file = REPORTS_DIR / "insights_cache_v7.json"
    cache_data = {}
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f: cache_data = json.load(f)
        except Exception: pass
        
    if cache_key in cache_data and "insights" in cache_data[cache_key] and "glance" in cache_data[cache_key]:
        print("  ⚡ 命中缓存，跳过 LLM 专项分析阶段 (Stage 4 & 5)...")
        insights = cache_data[cache_key]["insights"]
        glance = cache_data[cache_key]["glance"]
    else:
        # --- Stage 4: Run specialized analyses ---
        print("  🧠 启动 Stage 4 专项分析 (7 prompts并发)...")
        insights = run_specialized_analyses(stats)
        
        # --- Stage 5: Executive summary ---
        print("  🎯 启动 Stage 5 执行摘要...")
        glance = generate_executive_summary(stats, insights)
        
        # Write to cache
        cache_data[cache_key] = {"insights": insights, "glance": glance}
        try:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print("  💾 Stage 4/5 结果已缓存")
        except Exception as e:
            print(f"    ⚠️ 保存缓存失败: {e}")

    
    # Build narrative HTML
    narrative_html = {
        "project_areas": format_narrative_areas(insights.get("project_areas")),
        "interaction_style": format_narrative_style(insights.get("interaction_style")),
        "what_works": format_narrative_works(insights.get("what_works")),
        "friction": format_narrative_friction(insights.get("friction_analysis")),
        "suggestions": format_narrative_suggestions(insights.get("suggestions")),
        "horizon": format_narrative_horizon(insights.get("on_the_horizon")),
        "fun": format_narrative_fun(insights.get("fun_ending")),
    }

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html_template = f.read()

    replacements = {
        "report_title_meta": f"战略审计报告 - {period_label}",
        "report_title": f"🦅 个人数字化战略审计报告 ({period_label})",
        "report_subtitle": f"数据区间: {daily_labels[0] if daily_labels else 'N/A'} → {datetime.date.today().isoformat()} | 审计级别: 深度行为心理与架构审计",
        "glance_working": glance.get("whats_working", ""),
        "glance_hindering": glance.get("whats_hindering", ""),
        "glance_quick_wins": glance.get("quick_wins", ""),
        "glance_ambitious": glance.get("ambitious_workflows", ""),
        "card_sessions": str(stats["total_sessions"]),
        "card_hours": f'{stats["total_duration_hours"]:.1f}',
        "card_commits": str(stats["git_commits"]),
        "card_active_days": str(stats["active_days"]),
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
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    html = html_template
    for key, value in replacements.items():
        html = html.replace(f"%%{key}%%", value)
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.html"
    with open(report_path, "w", encoding="utf-8") as f: f.write(html)
    
    # Markdown export
    md_report = f"""# 战略审计报告 ({period_label})
> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | v7.0

## At a Glance
- **What's Working**: {glance.get('whats_working', '')}
- **What's Hindering**: {glance.get('whats_hindering', '')}
- **Quick Wins**: {glance.get('quick_wins', '')}
- **Ambitious Workflows**: {glance.get('ambitious_workflows', '')}

## 核心指标
| 指标 | 值 |
|---|---|
| 协作会话 | {stats['total_sessions']} |
| 累计时长 | {stats['total_duration_hours']:.1f}h |
| Git 提交 | {stats['git_commits']} |
| 活跃天数 | {stats['active_days']} |
| 最长连续 | {stats.get('max_streak', 0)}d |
"""
    md_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.md"
    with open(md_path, "w", encoding="utf-8") as f: f.write(md_report)
    print(f"  📄 Markdown 版本: {md_path.name}")
    
    # Auto-sync to memory
    sync_fragment = f"""
## [Strategic Audit: {period_label} - {datetime.date.today().isoformat()}]
- **协作效能**: {stats['total_duration_hours']:.1f}h / {stats['total_sessions']} 会话 / {stats['git_commits']} Git 提交
- **At a Glance**: {glance.get('whats_working', '')[:100]}
- **Quick Wins**: {glance.get('quick_wins', '')[:100]}
"""
    sync_to_memory(sync_fragment)
    
    return report_path

def main():
    parser = argparse.ArgumentParser(description='Strategic Audit Report Generator v7.0')
    parser.add_argument('--period', default='30d', choices=list(PERIOD_MAP.keys()),
                        help='Analysis period: 7d, 30d, 90d, year (default: 30d)')
    args = parser.parse_args()
    
    period_label = f"过去 {PERIOD_MAP[args.period]} 天" if args.period != 'year' else f"{datetime.date.today().year} 年度"
    print(f"🚀 启动战略审计 ({period_label})...")
    raw_sessions = get_session_list()
    logs = read_logs()
    sessions = process_sessions(raw_sessions, logs)
    
    print(f"正在进行多面体深度分析 ({len(sessions)} 个活跃会话)...")
    sessions = extract_facets_builtin(sessions)
    
    stats = aggregate_data(sessions, period=args.period)
    report_path = generate_report(stats, sessions)
    
    print(f"\n✅ 审计完成！报告位置: {report_path}")
    if os.name == 'nt':
        try: os.startfile(report_path)
        except Exception: pass

if __name__ == "__main__":
    main()
