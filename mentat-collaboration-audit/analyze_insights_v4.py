import os
import json
import datetime
import argparse
from core.engine import (
    get_session_list, read_logs, process_sessions, aggregate_data,
    sync_to_memory, PERIOD_MAP, TEMPLATE_FILE, REPORTS_DIR,
    get_agent_audit_path, get_raw_metrics_path
)
from validate_agent_audit import validate_agent_payload

VERSION = '9.0'


def format_narrative_areas(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    areas = data.get('areas', [])
    if not areas:
        return '<p>暂无项目领域数据</p>'
    html = '<ul>'
    for area in areas:
        html += f'<li><strong>{area.get("name", "")}</strong> ({area.get("session_count", 0)} sessions) — {area.get("description", "")}</li>'
    return html + '</ul>'


def format_narrative_style(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    return f'<p>{data.get("narrative", "")}</p><p><strong>关键模式：</strong>{data.get("key_pattern", "")}</p>'


def format_narrative_works(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    workflows = data.get('impressive_workflows', [])
    html = f'<p>{data.get("intro", "")}</p><ul>'
    for workflow in workflows:
        html += f'<li><strong>{workflow.get("title", "")}</strong> — {workflow.get("description", "")}</li>'
    return html + '</ul>'


def format_narrative_friction(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    categories = data.get('categories', [])
    html = f'<p>{data.get("intro", "")}</p>'
    for category in categories:
        examples = ', '.join(category.get('examples', []))
        html += f'<h3>{category.get("category", "")}</h3>'
        if category.get('root_cause_pattern'):
            html += f'<p style="color: var(--danger); font-weight: 500;">🔍 根因模式: {category.get("root_cause_pattern", "")}</p>'
        html += f'<p>{category.get("description", "")}</p><p style="font-size:12px;color:#6c8aff;">例: {examples}</p>'
    return html


def format_narrative_suggestions(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    html = '<h3>🔧 配置建议</h3><ul>'
    for addition in data.get('config_additions', []):
        html += f'<li><code>{addition.get("addition", "")}</code> — {addition.get("why", "")}</li>'
    html += '</ul><h3>📋 使用模式</h3><ul>'
    for usage in data.get('usage_patterns', []):
        html += f'<li><strong>{usage.get("title", "")}</strong>: {usage.get("detail", "")}</li>'
    return html + '</ul>'


def format_narrative_horizon(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>分析数据暂不可用</p>'
    opportunities = data.get('opportunities', [])
    html = f'<p>{data.get("intro", "")}</p><ul>'
    for opportunity in opportunities:
        html += f'<li><strong>{opportunity.get("title", "")}</strong> — {opportunity.get("whats_possible", "")}<br><em>{opportunity.get("how_to_try", "")}</em></li>'
    return html + '</ul>'


def format_narrative_fun(data):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return '<p>暂无趣味时刻数据</p>'
    return f'<h3>{data.get("headline", "")}</h3><p>{data.get("detail", "")}</p>'


def format_narrative_behavioral_analysis(data, workflow_engineering=None):
    if isinstance(data, str):
        return f'<p>{data}</p>'
    if not isinstance(data, dict):
        return ''

    points = data.get('points', [])
    overall = data.get('overall', '')
    summary = data.get('coach_summary', '')
    html = f'<p>{data.get("intro", "")}</p>'

    if summary:
        html += f'<div style="background: rgba(79, 70, 229, 0.05); padding: 24px; border-radius: 12px; margin: 20px 0; border: 1px solid var(--accent);">{summary}</div>'
    elif overall:
        html += f'<div style="background: var(--surface-2); padding: 16px; border-radius: 8px; margin-bottom: 20px; border-left: 3px solid var(--success);"><strong>🌟 总体认知评估：</strong>{overall}</div>'

    if workflow_engineering:
        html += '<h3 style="margin-top: 30px; color: var(--accent);">🛠️ 工作流工程资产 (Workflow Engineering)</h3>'

        prompt_assets = workflow_engineering.get('prompt_assets', [])
        if prompt_assets:
            html += '<h4>📋 提示词资产与前置约束</h4>'
            for asset in prompt_assets:
                html += f'''<div style="background: #f1f5f9; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #475569;">
<div style="font-size: 12px; color: #64748b; margin-bottom: 5px;">针对: {asset.get('target_friction')} | 类型: {asset.get('asset_type')}</div>
<pre style="white-space: pre-wrap; word-break: break-all; background: #fff; padding: 10px; border-radius: 4px; border: 1px solid #e2e8f0; font-family: monospace; font-size: 13px;">{asset.get('copy_paste_template')}</pre>
</div>'''

        automation = workflow_engineering.get('automation_candidates', [])
        if automation:
            html += '<h4>🚀 自动化与 Skill 候选</h4>'
            for candidate in automation:
                html += f'''<div style="background: #eff6ff; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #3b82f6;">
<div style="font-weight: 600; color: #1e40af;">{candidate.get('candidate_name')}</div>
<div style="font-size: 13px; color: #374151; margin-top: 5px;">{candidate.get('rationale')}</div>
<div style="font-size: 12px; font-family: monospace; color: #1d4ed8; margin-top: 8px; padding: 8px; background: rgba(255,255,255,0.5); border-radius: 4px;">{candidate.get('implementation_sketch')}</div>
</div>'''

    if points:
        html += '<details style="margin-top: 20px;"><summary style="cursor: pointer; color: var(--accent); font-weight: 600;">📊 查看 8 维指标深度拆解</summary><div style="margin-top: 15px;">'
        for point in points:
            html += f'<div style="margin-bottom: 15px; padding-left: 10px; border-left: 2px solid var(--primary);"><strong>🔍 {point.get("title", "")}</strong><p style="margin-top: 5px; font-size: 0.95em; color: var(--text-2);">{point.get("description", "")}</p></div>'
        html += '</div></details>'
    return html


def generate_report(stats, sessions, insights):
    period_label = stats.get('period_label', 'N/A')

    daily_sorted = sorted(stats.get('daily_activity', {}).items())
    daily_labels = [entry[0] for entry in daily_sorted]
    daily_data = [entry[1] for entry in daily_sorted]

    goal_dist = insights.get('distributions', {}).get('goal_dist', {'综合': 1})
    sat_dist = insights.get('distributions', {}).get('satisfaction_dist', {'未知': 1})
    fric_dist = insights.get('distributions', {}).get('friction_dist', {'无记录': 1})
    emotion_dist = insights.get('distributions', {}).get('emotional_tone_dist', {'中性': 1})
    anti_patterns_dist = insights.get('distributions', {}).get('interaction_anti_patterns', {'无模式': 1})
    helpfulness_dist = insights.get('distributions', {}).get('helpfulness_dist', {'中等': 1})

    goal_labels = list(goal_dist.keys())
    goal_data = list(goal_dist.values())
    sat_labels = list(sat_dist.keys())
    sat_data = list(sat_dist.values())
    fric_labels = list(fric_dist.keys())
    fric_data = list(fric_dist.values())
    emotion_labels = list(emotion_dist.keys())
    emotion_data = list(emotion_dist.values())
    anti_patterns_labels = list(anti_patterns_dist.keys())
    anti_patterns_data = list(anti_patterns_dist.values())
    helpfulness_labels = list(helpfulness_dist.keys())
    helpfulness_data = list(helpfulness_dist.values())

    topic_cloud = insights.get('distributions', {}).get('topic_cloud', {'Agentic': 1})
    max_count = max(topic_cloud.values()) if topic_cloud else 1
    topic_cloud_html = ' '.join([
        f'<span class="topic-tag{" hot" if value >= max_count * 0.6 else ""}">{key} ({value})</span>'
        for key, value in topic_cloud.items()
    ]) if topic_cloud else '<span class="topic-tag">暂无主题数据</span>'

    radar_labels = ['完成率', '满意度', '低摩擦', 'AI有效性', '情感韧性', '会话深度']
    radar_data = insights.get('distributions', {}).get('radar_data', [80, 80, 80, 80, 80, 80])
    peak_hours = stats.get('peak_hours', {})
    peak_hour_str = f"{list(peak_hours.keys())[0]}:00" if peak_hours else 'N/A'

    glance = insights.get('at_a_glance', {})
    if not isinstance(glance, dict):
        glance = {
            'whats_working': str(glance),
            'whats_hindering': '',
            'quick_wins': '',
            'ambitious_workflows': '',
        }

    narrative_html = {
        'project_areas': format_narrative_areas(insights.get('project_areas')),
        'interaction_style': format_narrative_style(insights.get('interaction_style')),
        'what_works': format_narrative_works(insights.get('what_works')),
        'friction': format_narrative_friction(insights.get('friction_analysis')),
        'suggestions': format_narrative_suggestions(insights.get('suggestions')),
        'horizon': format_narrative_horizon(insights.get('on_the_horizon')),
        'fun': format_narrative_fun(insights.get('fun_ending')),
        'behavioral': format_narrative_behavioral_analysis(insights.get('behavioral_analysis'), insights.get('workflow_engineering')),
    }

    version = insights.get('version', VERSION)
    if version != VERSION:
        print(f'⚠️ Warning: Insight data version ({version}) does not match renderer ({VERSION}). Some sections may be missing.')

    chart_analyses = [''] * 8
    points = insights.get('behavioral_analysis', {}).get('points', [])
    for index in range(min(len(points), 8)):
        chart_analyses[index] = f"<strong>{points[index].get('title', '')}</strong>{points[index].get('description', '')}"
    for index in range(len(points), 8):
        chart_analyses[index] = '<em>(暂无该维度深度解读)</em>'

    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as handle:
        html_template = handle.read()

    replacements = {
        'report_title_meta': f'战略审计报告 - {period_label}',
        'report_title': f'🦅 个人数字化战略审计报告 ({period_label})',
        'report_subtitle': f'数据区间: {daily_labels[0] if daily_labels else "N/A"} → {datetime.date.today().isoformat()} | 审计级别: Agentic Workflow V9.0',
        'glance_working': glance.get('whats_working', ''),
        'glance_hindering': glance.get('whats_hindering', ''),
        'glance_quick_wins': glance.get('quick_wins', ''),
        'glance_ambitious': glance.get('ambitious_workflows', ''),
        'card_sessions': str(stats.get('total_sessions', 0)),
        'card_hours': f"{stats.get('total_duration_hours', 0):.1f}",
        'card_commits': str(stats.get('git_commits', 0)),
        'card_active_days': str(stats.get('active_days', 0)),
        'card_streak': str(stats.get('max_streak', 0)),
        'card_peak_hour': peak_hour_str,
        'daily_labels': json.dumps(daily_labels),
        'daily_data': json.dumps(daily_data),
        'goal_labels': json.dumps(goal_labels),
        'goal_data': json.dumps(goal_data),
        'sat_labels': json.dumps(sat_labels),
        'sat_data': json.dumps(sat_data),
        'fric_labels': json.dumps(fric_labels),
        'fric_data': json.dumps(fric_data),
        'emotion_labels': json.dumps(emotion_labels),
        'emotion_data': json.dumps(emotion_data),
        'radar_labels': json.dumps(radar_labels),
        'radar_data': json.dumps(radar_data),
        'helpfulness_labels': json.dumps(helpfulness_labels),
        'helpfulness_data': json.dumps(helpfulness_data),
        'session_type_labels': json.dumps(anti_patterns_labels),
        'session_type_data': json.dumps(anti_patterns_data),
        'topic_cloud_html': topic_cloud_html,
        'narrative_project_areas': narrative_html['project_areas'],
        'narrative_interaction_style': narrative_html['interaction_style'],
        'narrative_what_works': narrative_html['what_works'],
        'narrative_friction': narrative_html['friction'],
        'narrative_suggestions': narrative_html['suggestions'],
        'narrative_horizon': narrative_html['horizon'],
        'narrative_fun': narrative_html['fun'],
        'narrative_behavioral': narrative_html['behavioral'],
        'analysis_daily': chart_analyses[0],
        'analysis_goal': chart_analyses[1],
        'analysis_sat': chart_analyses[2],
        'analysis_fric': chart_analyses[3],
        'analysis_emotion': chart_analyses[4],
        'analysis_radar': chart_analyses[5],
        'analysis_helpfulness': chart_analyses[6],
        'analysis_session_type': chart_analyses[7],
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    html = html_template
    for key, value in replacements.items():
        html = html.replace(f'%%{key}%%', str(value))
        html = html.replace(f'%% {key} %%', str(value))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.html"
    with open(report_path, 'w', encoding='utf-8') as handle:
        handle.write(html)

    md_sections = []
    md_sections.append(f'# 战略审计报告 ({period_label})')
    md_sections.append(f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | v{VERSION} Agentic Edition")
    md_sections.append('\n## 1. At a Glance')
    md_sections.append(f"- **What's Working**: {glance.get('whats_working', '')}")
    md_sections.append(f"- **What's Hindering**: {glance.get('whats_hindering', '')}")
    md_sections.append(f"- **Quick Wins**: {glance.get('quick_wins', '')}")
    md_sections.append(f"- **Ambitious Workflows**: {glance.get('ambitious_workflows', '')}")
    md_sections.append('\n## 2. 核心指标')
    md_sections.append('| 指标 | 值 |')
    md_sections.append('|---|---|')
    md_sections.append(f"| 协作会话 | {stats.get('total_sessions', 0)} |")
    md_sections.append(f"| 累计时长 | {stats.get('total_duration_hours', 0):.1f}h |")
    md_sections.append(f"| Git 提交 | {stats.get('git_commits', 0)} |")
    md_sections.append(f"| 活跃天数 | {stats.get('active_days', 0)} |")
    md_sections.append(f"| 最长连续 | {stats.get('max_streak', 0)}d |")

    behav = insights.get('behavioral_analysis', {})
    if behav:
        md_sections.append('\n## 3. 🦅 教练解读：行为背后的潜台词')
        md_sections.append(f"{behav.get('intro', '')}")
        if behav.get('overall'):
            md_sections.append(f"\n> **总体认知评估**：{behav.get('overall')}")
        workflow_engineering = insights.get('workflow_engineering', {})
        if workflow_engineering:
            md_sections.append('\n### 🛠️ 工作流工程资产')
            for asset in workflow_engineering.get('prompt_assets', []):
                md_sections.append(f"\n- **{asset.get('asset_type')}** (针对: {asset.get('target_friction')}):")
                md_sections.append(f"```text\n{asset.get('copy_paste_template')}\n```")
            for candidate in workflow_engineering.get('automation_candidates', []):
                md_sections.append(f"\n- **自动化候选: {candidate.get('candidate_name')}**")
                md_sections.append(f"  - 理由: {candidate.get('rationale')}")
                md_sections.append(f"  - 实现: `{candidate.get('implementation_sketch')}`")
        for point in behav.get('points', []):
            md_sections.append(f"\n### 🔍 {point.get('title')}")
            md_sections.append(f"{point.get('description')}")

    friction = insights.get('friction_analysis', {})
    if friction:
        md_sections.append('\n## 4. 摩擦基因审计')
        md_sections.append(f"{friction.get('intro', '')}")
        for category in friction.get('categories', []):
            md_sections.append(f"\n### ⚡ {category.get('category')}")
            if category.get('root_cause_pattern'):
                md_sections.append(f"**根因模式**: {category.get('root_cause_pattern')}")
            md_sections.append(f"{category.get('description', '')}")
            md_sections.append(f"*例: {', '.join(category.get('examples', []))}*")

    areas = insights.get('project_areas', {}).get('areas', [])
    if areas:
        md_sections.append('\n## 5. 项目领域分布')
        for area in areas:
            md_sections.append(f"- **{area.get('name')}** ({area.get('session_count')} sessions): {area.get('description')}")

    suggestions = insights.get('suggestions', {})
    if suggestions:
        md_sections.append('\n## 6. 负熵进化建议')
        for addition in suggestions.get('config_additions', []):
            md_sections.append(f"- **配置补丁**: `{addition.get('addition')}` ({addition.get('why')})")
        for usage in suggestions.get('usage_patterns', []):
            md_sections.append(f"- **交互模式**: **{usage.get('title')}**: {usage.get('detail')}")

    md_report = '\n'.join(md_sections)
    md_path = REPORTS_DIR / f"{datetime.date.today().strftime('%Y%m%d')}_Strategic_Audit_{stats.get('period', '30d')}.md"
    with open(md_path, 'w', encoding='utf-8') as handle:
        handle.write(md_report)
    print(f'  📄 Markdown 版本: {md_path.name}')

    sync_fragment = f"""
## [Strategic Audit: {period_label} - {datetime.date.today().isoformat()}]
- **协作效能**: {stats.get('total_duration_hours', 0):.1f}h / {stats.get('total_sessions', 0)} 会话 / {stats.get('git_commits', 0)} Git 提交
- **At a Glance**: {glance.get('whats_working', '')[:100]}
- **Quick Wins**: {glance.get('quick_wins', '')[:100]}
"""
    sync_to_memory(sync_fragment)

    return report_path


def main():
    parser = argparse.ArgumentParser(description='Strategic Audit Data Pump & Renderer v9.0')
    parser.add_argument('--period', default='30d', choices=list(PERIOD_MAP.keys()), help='Analysis period: 1d, 7d, 30d, 90d, year (default: 30d)')
    parser.add_argument('--extract-only', action='store_true', help='Only extract session raw data and physical metrics')
    parser.add_argument('--render', action='store_true', help='Render final HTML report from agent insights')
    parser.add_argument('--agent-file', type=str, default='', help='Path to the agent generated JSON file with insights')
    args = parser.parse_args()

    if not args.extract_only and not args.render:
        print('❌ 必须指定 --extract-only 或 --render 模式 (Agentic V9.0)')
        return

    period_label = f"过去 {PERIOD_MAP[args.period]} 天" if args.period != 'year' else f"{datetime.date.today().year} 年度"

    if args.extract_only:
        print(f'🚀 启动物理数据泵 ({period_label})...')
        raw_sessions = get_session_list()
        logs = read_logs()
        sessions = process_sessions(raw_sessions, logs)
        stats = aggregate_data(sessions, period=args.period)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = get_raw_metrics_path(args.period)
        with open(out_file, 'w', encoding='utf-8') as handle:
            json.dump({'stats': stats, 'sessions': sessions}, handle, ensure_ascii=False, indent=2)
        print(f'✅ 物理数据提取完毕，等待 Agent 认知推演。数据位置: {out_file}')
        return

    agent_file = args.agent_file or str(get_agent_audit_path())
    if not os.path.exists(agent_file):
        print('❌ 必须提供存在的 --agent-file 来指定 agent 推理出的洞察结果文件')
        return

    raw_file = get_raw_metrics_path(args.period)
    if os.path.exists(raw_file):
        with open(raw_file, 'r', encoding='utf-8') as handle:
            raw_data = json.load(handle)
            stats = raw_data.get('stats', {})
            sessions = raw_data.get('sessions', [])
    else:
        print('⚠️ 未找到 raw_metrics 数据，仅使用最小框架渲染')
        stats = {'period': args.period, 'period_label': period_label}
        sessions = []

    with open(agent_file, 'r', encoding='utf-8') as handle:
        insights = json.load(handle)

    validation_errors = validate_agent_payload(insights)
    if validation_errors:
        print('❌ 洞察 JSON 未通过 V9 校验门：')
        for error in validation_errors:
            print(f' - {error}')
        return

    report_path = generate_report(stats, sessions, insights)
    print(f'\n✅ 审计 HTML/MD 生成完成！报告位置: {report_path}')

    if os.name == 'nt':
        try:
            os.startfile(report_path)
        except Exception:
            pass


if __name__ == '__main__':
    main()
