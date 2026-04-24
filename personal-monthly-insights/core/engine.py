import os
import re
import json
import datetime
import subprocess
import threading
from pathlib import Path
from collections import Counter, defaultdict

USER_HOME = Path(os.environ.get('USERPROFILE', str(Path.home())))
SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get('PMI_DATA_ROOT', str(USER_HOME / '.gemini')))
CLI_ROOT = Path(os.environ.get('PMI_CLI_ROOT', str(DATA_ROOT)))
REPORTS_DIR = Path(os.environ.get('PMI_REPORTS_DIR', str(DATA_ROOT / 'MEMORY' / 'raw' / 'personal-insights')))
CACHE_FILE = Path(os.environ.get('PMI_CACHE_FILE', str(SKILL_DIR / 'facets_cache.json')))
ASSETS_DIR = SKILL_DIR / 'assets'
TEMPLATE_FILE = Path(os.environ.get('PMI_TEMPLATE_FILE', str(ASSETS_DIR / 'template.html')))
MEMORY_FILE = Path(os.environ.get('PMI_MEMORY_FILE', str(SKILL_DIR / 'memory.md')))

PERIOD_MAP = {
    '1d': 1,
    '7d': 7,
    '30d': 30,
    '90d': 90,
    'year': 365,
}

cache_lock = threading.Lock()

GOAL_MAP = {
    'debug_investigate': '调试排查', 'implement_feature': '实现功能', 'fix_bug': '修复Bug',
    'write_script_tool': '编写脚本', 'refactor_code': '重构代码', 'configure_system': '系统配置',
    'create_pr_commit': '提交PR', 'analyze_data': '数据分析', 'understand_codebase': '理解代码',
    'write_tests': '编写测试', 'write_docs': '文档撰写', 'deploy_infra': '部署运维',
    'warmup_minimal': '热身会话', 'other': '其他'
}
SAT_MAP = {
    'frustrated': '😫 沮丧', 'dissatisfied': '😠 不满', 'likely_satisfied': '😐 尚可',
    'satisfied': '🙂 满意', 'happy': '😃 开心', 'unsure': '❓ 未知'
}
FRIC_MAP = {
    'misunderstood_request': '理解偏差', 'wrong_approach': '方案错误', 'buggy_code': '代码缺陷',
    'user_rejected_action': '拒绝操作', 'claude_got_blocked': '系统卡滞', 'excessive_changes': '修改过度',
    'slow_or_verbose': '响应冗长', 'user_unclear': '表达不明',
    'wrong_file_or_location': '文件位置错误', 'tool_failed': '工具失败',
    'external_issue': '外部问题', 'none': '无摩擦'
}
INTENT_MAP = {
    'minimalist': '极简主义 (Minimalist)', 'balanced': '均衡平衡 (Balanced)', 'verbose': '详尽叙述 (Verbose)'
}
COG_FRIC_MAP = {
    'environmental_win32': 'Win32 环境熵增', 'encoding_issue': '编码/字符集冲突',
    'logical_misalignment': '逻辑语义偏差', 'tool_chain_complexity': '工具链肥大/复杂', 'none': '无显著阻力'
}
ARCHETYPE_MAP = {
    'tool_maker': '主权架构师 (Tool Maker)', 'strategic_consultant': '战略咨询师 (Consultant)',
    'explorer': '深度探索者 (Explorer)', 'execution_operator': '高效操作员 (Operator)', 'warmup': '系统热身 (Warmup)'
}
PROFILE_MAP = {
    'Crisis Manager': '危机处理者', 'Builder': '高效构建者', 'Explorer': '深度探索者', 'Steady Operator': '稳健操作员'
}
EMOTION_MAP = {
    'anxious': '😰 焦虑', 'frustrated': '😤 受挫', 'neutral': '😐 中性',
    'focused': '🎯 专注', 'flow': '🌊 心流', 'excited': '🚀 兴奋'
}
HELPFULNESS_MAP = {
    'unhelpful': '❌ 无效', 'slightly_helpful': '🟡 略有帮助', 'moderately_helpful': '🟢 中等',
    'very_helpful': '⭐ 非常有效', 'essential': '💯 不可或缺'
}
SESSION_TYPE_MAP = {
    'single_task': '单一任务', 'multi_task': '多任务', 'iterative_refinement': '迭代精调',
    'exploration': '探索发现', 'quick_question': '快问快答'
}
OUTCOME_MAP = {
    'fully_achieved': '✅ 完全达成', 'mostly_achieved': '🟢 基本达成',
    'partially_achieved': '🟡 部分达成', 'not_achieved': '❌ 未达成', 'unclear': '❓ 不确定'
}


def get_raw_metrics_path(period):
    return REPORTS_DIR / f'raw_metrics_{period}.json'


def get_agent_audit_path():
    return REPORTS_DIR / 'agent_audit_result.json'


# Pre-compiled regex patterns to improve parsing performance
ANSI_CLEAN = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
UUID_PATTERN = re.compile(r'\[([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\]')
DAYS_AGO_PATTERN = re.compile(r'(\d+)\s+days ago')
ISO_DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')


def strip_ansi(text):
    return ANSI_CLEAN.sub('', text)


def get_session_list():
    try:
        result = subprocess.run(
            ['gemini', '--list-sessions'],
            capture_output=True,
            text=True,
            shell=True,
            cwd=str(CLI_ROOT),
            encoding='utf-8',
            errors='ignore'
        )
        output = strip_ansi(result.stdout)
        sessions = []
        for line in output.splitlines():
            line = line.strip()
            match = UUID_PATTERN.search(line)
            if match:
                sid = match.group(1)
                date = datetime.date.today().isoformat()
                if 'days ago' in line:
                    m = DAYS_AGO_PATTERN.search(line)
                    if m:
                        date = (datetime.date.today() - datetime.timedelta(days=int(m.group(1)))).isoformat()
                elif 'hours ago' in line or 'minutes ago' in line:
                    date = datetime.date.today().isoformat()
                elif 'yesterday' in line.lower():
                    date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
                else:
                    dm = ISO_DATE_PATTERN.search(line)
                    if dm:
                        date = dm.group(1)
                sessions.append({'id': sid, 'title': line[:60], 'date': date})
        print(f'  🔍 从运行时根目录提取到 {len(sessions)} 个会话记录')
        return sessions
    except Exception as exc:
        print(f'  ❌ 会话提取异常: {exc}')
        return []


def read_logs():
    merged_logs = []

    tmp_dir = DATA_ROOT / 'tmp'
    if tmp_dir.exists():
        for log_file in tmp_dir.glob('**/logs.json'):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as handle:
                    data = json.load(handle)
                    if isinstance(data, list):
                        merged_logs.extend(data)
            except Exception:
                continue

    brain_dir = DATA_ROOT / 'antigravity' / 'brain'
    if brain_dir.exists():
        for log_file in brain_dir.glob('**/.system_generated/logs/*.jsonl'):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if isinstance(entry, dict):
                                merged_logs.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue

    print(f'  📂 合并记录数: {len(merged_logs)} (多源融合)')
    return merged_logs


def summarize_long_transcript(messages, max_chars=10000):
    full_text = '\n'.join([f"{m.get('type', 'UNK').upper()}: {str(m.get('message', ''))[:1000]}" for m in messages])
    if len(full_text) <= max_chars:
        return full_text
    return full_text[:max_chars] + '\n...[Transcript Truncated]...'


def process_sessions(raw_sessions, logs):
    session_messages = defaultdict(list)
    for message in logs:
        sid = message.get('sessionId')
        if sid:
            session_messages[sid].append(message)

    processed = []
    filtered_count = 0
    for session in raw_sessions:
        sid = session['id']
        title = session.get('title', '')
        messages = session_messages.get(sid, [])
        if not messages:
            continue

        if title.startswith('agent-') or 'facet-extraction' in title.lower():
            filtered_count += 1
            continue

        user_msgs = [m for m in messages if m.get('type') in ('user', 'human', 'USER')]
        if len(user_msgs) < 2:
            filtered_count += 1
            continue

        try:
            parsed_ts = []
            for message in messages:
                ts_str = message.get('timestamp', '').replace('Z', '+00:00')
                if ts_str:
                    parsed_ts.append(datetime.datetime.fromisoformat(ts_str))
            duration = (max(parsed_ts) - min(parsed_ts)).total_seconds() if len(parsed_ts) > 1 else 0
        except Exception:
            duration = 0

        if duration > 0 and duration < 60:
            filtered_count += 1
            continue

        transcript = summarize_long_transcript(messages)
        processed.append({
            'id': sid,
            'title': title,
            'date': session['date'],
            'count': len(messages),
            'user_count': len(user_msgs),
            'duration_sec': duration,
            'tokens': sum(len(str(m.get('message', ''))) for m in messages) // 4,
            'timestamp': messages[0].get('timestamp'),
            'transcript_snapshot': transcript,
        })
    print(f'  🎯 匹配会话: {len(processed)} (过滤了 {filtered_count} 个低质量会话)')
    return processed


def get_git_stats():
    path = Path.cwd()
    git_root = None
    for _ in range(5):
        if (path / '.git').exists():
            git_root = path
            break
        path = path.parent
    if not git_root:
        return 0
    try:
        cmd = ['git', 'rev-list', '--count', 'HEAD', "--since=1 year ago"]
        return int(subprocess.check_output(cmd, encoding='utf-8', shell=True, cwd=str(git_root)).strip())
    except Exception:
        return 0


def filter_by_period(sessions, period='30d'):
    days = PERIOD_MAP.get(period, 30)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    filtered = [s for s in sessions if s['date'] >= cutoff]
    if not filtered:
        filtered = sessions
    return filtered


def aggregate_data(sessions, period='30d'):
    filtered = filter_by_period(sessions, period)

    hour_counter = Counter()
    for session in filtered:
        ts = session.get('timestamp', '')
        if ts:
            try:
                hour = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).hour
                hour_counter[hour] += 1
            except Exception:
                pass

    dates_sorted = sorted(set(s['date'] for s in filtered))
    max_streak = current_streak = 1
    for index in range(1, len(dates_sorted)):
        try:
            d1 = datetime.date.fromisoformat(dates_sorted[index - 1])
            d2 = datetime.date.fromisoformat(dates_sorted[index])
            if (d2 - d1).days == 1:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 1
        except Exception:
            pass

    return {
        'period': period,
        'period_label': f"过去 {PERIOD_MAP.get(period, 30)} 天" if period != 'year' else f"{datetime.date.today().year} 年度",
        'total_sessions': len(filtered),
        'total_messages': sum(s['count'] for s in filtered),
        'total_duration_hours': sum(s['duration_sec'] for s in filtered) / 3600,
        'total_tokens': sum(s['tokens'] for s in filtered),
        'active_days': len(set(s['date'] for s in filtered)),
        'max_streak': max_streak if dates_sorted else 0,
        'git_commits': get_git_stats(),
        'peak_hours': dict(hour_counter.most_common(5)),
        'daily_activity': dict(Counter(s['date'] for s in filtered)),
    }


def sync_to_memory(fragment, memory_file=None):
    mf = Path(memory_file) if memory_file else MEMORY_FILE
    header_marker = fragment.strip().split('\n')[0].strip()

    existing_content = ''
    if mf.exists():
        existing_content = mf.read_text(encoding='utf-8')

    if header_marker in existing_content:
        pattern = re.compile(re.escape(header_marker) + r'.*?(?=\n## |\Z)', re.DOTALL)
        updated = pattern.sub(fragment.strip(), existing_content)
        mf.write_text(updated, encoding='utf-8')
        print('  🔄 已更新 memory.md 中的审计记录')
    else:
        with open(mf, 'a', encoding='utf-8') as handle:
            handle.write('\n' + fragment.strip() + '\n')
        print(f'  ✅ 已自动追加审计洞察至 {mf.name}')
    return mf
