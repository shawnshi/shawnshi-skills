import os
import re
import json
import datetime
import subprocess
import threading
from pathlib import Path
from collections import Counter, defaultdict
# --- Dynamic Configuration ---
GEMINI_ROOT = Path(os.environ.get('USERPROFILE', 'C:/Users/default')) / ".gemini"
SKILL_DIR = GEMINI_ROOT / "skills" / "monthly-personal-insights"
REPORTS_DIR = GEMINI_ROOT / "MEMORY" / "personal-insights"
CACHE_FILE = SKILL_DIR / "facets_cache.json"
ASSETS_DIR = SKILL_DIR / "assets"
TEMPLATE_FILE = ASSETS_DIR / "template.html"
MEMORY_FILE = SKILL_DIR / "memory.md"

# --- Period Configuration ---
PERIOD_MAP = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "year": 365,
}

# Thread safety for cache
cache_lock = threading.Lock()

GOAL_MAP = {
    "debug_investigate": "调试排查", "implement_feature": "实现功能", "fix_bug": "修复Bug",
    "write_script_tool": "编写脚本", "refactor_code": "重构代码", "configure_system": "系统配置",
    "create_pr_commit": "提交PR", "analyze_data": "数据分析", "understand_codebase": "理解代码",
    "write_tests": "编写测试", "write_docs": "文档撰写", "deploy_infra": "部署运维",
    "warmup_minimal": "热身会话", "other": "其他"
}
SAT_MAP = {
    "frustrated": "😫 沮丧", "dissatisfied": "😠 不满", "likely_satisfied": "😐 尚可",
    "satisfied": "🙂 满意", "happy": "😃 开心", "unsure": "❓ 未知"
}
FRIC_MAP = {
    "misunderstood_request": "理解偏差", "wrong_approach": "方案错误", "buggy_code": "代码缺陷",
    "user_rejected_action": "拒绝操作", "claude_got_blocked": "系统卡滞", "excessive_changes": "修改过度",
    "slow_or_verbose": "响应冗长", "user_unclear": "表达不明",
    "wrong_file_or_location": "文件位置错误", "tool_failed": "工具失败",
    "external_issue": "外部问题", "none": "无摩擦"
}
INTENT_MAP = {
    "minimalist": "极简主义 (Minimalist)", "balanced": "均衡平衡 (Balanced)", "verbose": "详尽叙述 (Verbose)"
}
COG_FRIC_MAP = {
    "environmental_win32": "Win32 环境熵增", "encoding_issue": "编码/字符集冲突",
    "logical_misalignment": "逻辑语义偏差", "tool_chain_complexity": "工具链肥大/复杂", "none": "无显著阻力"
}
ARCHETYPE_MAP = {
    "tool_maker": "主权架构师 (Tool Maker)", "strategic_consultant": "战略咨询师 (Consultant)",
    "explorer": "深度探索者 (Explorer)", "execution_operator": "高效操作员 (Operator)", "warmup": "系统热身 (Warmup)"
}
PROFILE_MAP = {
    "Crisis Manager": "危机处理者", "Builder": "高效构建者", "Explorer": "深度探索者", "Steady Operator": "稳健操作员"
}
EMOTION_MAP = {
    "anxious": "😰 焦虑", "frustrated": "😤 受挫", "neutral": "😐 中性",
    "focused": "🎯 专注", "flow": "🌊 心流", "excited": "🚀 兴奋"
}
HELPFULNESS_MAP = {
    "unhelpful": "❌ 无效", "slightly_helpful": "🟡 略有帮助", "moderately_helpful": "🟢 中等",
    "very_helpful": "⭐ 非常有效", "essential": "💯 不可或缺"
}
SESSION_TYPE_MAP = {
    "single_task": "单一任务", "multi_task": "多任务", "iterative_refinement": "迭代精调",
    "exploration": "探索发现", "quick_question": "快问快答"
}
OUTCOME_MAP = {
    "fully_achieved": "✅ 完全达成", "mostly_achieved": "🟢 基本达成",
    "partially_achieved": "🟡 部分达成", "not_achieved": "❌ 未达成", "unclear": "❓ 不确定"
}

def strip_ansi(text):
    """Simple but robust ANSI stripping."""
    return re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', text)

def get_session_list():
    """Returns a list of sessions. Run from GEMINI_ROOT."""
    try:
        result = subprocess.run(
            ["gemini", "--list-sessions"], 
            capture_output=True, text=True, shell=True, 
            cwd=str(GEMINI_ROOT), 
            encoding='utf-8', errors='ignore'
        )
        output = strip_ansi(result.stdout)
        sessions = []
        for line in output.splitlines():
            line = line.strip()
            # Standard UUID pattern with explicit capture group
            match = re.search(r'\[([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\]', line)
            if match:
                sid = match.group(1)
                date = datetime.date.today().isoformat()
                # Handle various date formats
                if "days ago" in line:
                    m = re.search(r"(\d+)\s+days ago", line)
                    if m: date = (datetime.date.today() - datetime.timedelta(days=int(m.group(1)))).isoformat()
                elif "hours ago" in line or "minutes ago" in line:
                    date = datetime.date.today().isoformat()
                elif "yesterday" in line.lower():
                    date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
                else:
                    # Try ISO date pattern in the line
                    dm = re.search(r'(\d{4}-\d{2}-\d{2})', line)
                    if dm: date = dm.group(1)
                sessions.append({"id": sid, "title": line[:60], "date": date})
        print(f"  🔍 从根目录成功提取到 {len(sessions)} 个会话记录")
        return sessions
    except Exception as e:
        print(f"  ❌ 会话提取异常: {e}")
        return []

def read_logs():
    """Read logs from multiple sources for data fusion."""
    merged_logs = []
    
    # Source 1: Gemini CLI tmp logs
    tmp_dir = GEMINI_ROOT / "tmp"
    if tmp_dir.exists():
        all_logs_files = list(tmp_dir.glob("**/logs.json"))
        for log_file in all_logs_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors='ignore') as f:
                    data = json.load(f)
                    if isinstance(data, list): merged_logs.extend(data)
            except Exception: continue
    
    # Source 2: Antigravity brain conversation logs
    brain_dir = GEMINI_ROOT / "antigravity" / "brain"
    if brain_dir.exists():
        ag_log_files = list(brain_dir.glob("**/.system_generated/logs/*.jsonl"))
        for lf in ag_log_files:
            try:
                with open(lf, "r", encoding="utf-8", errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                if isinstance(entry, dict):
                                    merged_logs.append(entry)
                            except json.JSONDecodeError:
                                continue
            except Exception: continue
    
    print(f"  📂 合并记录数: {len(merged_logs)} (多源融合)")
    return merged_logs

def get_recent_skill_activity(days=30):
    """Snapshot of recently modified skill/workflow files as a supplementary metric."""
    skills_dir = GEMINI_ROOT / "skills"
    cutoff = datetime.datetime.now().timestamp() - (days * 86400)
    recent = []
    if skills_dir.exists():
        for p in skills_dir.rglob("*\*"):
            if p.is_file() and p.stat().st_mtime > cutoff:
                recent.append({"path": str(p.relative_to(skills_dir)), "modified": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return recent

def summarize_long_transcript(messages, max_chars=10000):
    """Stage 2: Truncate long transcripts to save token space for Agent log reading."""
    full_text = "\n".join([f"{m.get('type','UNK').upper()}: {str(m.get('message',''))[:1000]}" for m in messages])
    if len(full_text) <= max_chars:
        return full_text
    
    return full_text[:max_chars] + "\n...[Transcript Truncated]..."

def process_sessions(raw_sessions, logs):
    session_messages = defaultdict(list)
    for msg in logs:
        sid = msg.get("sessionId")
        if sid: session_messages[sid].append(msg)
    
    processed = []
    filtered_count = 0
    for s in raw_sessions:
        sid = s["id"]
        title = s.get("title", "")
        msgs = session_messages.get(sid, [])
        if not msgs: continue
        
        # --- Quality Gates (aligned with Claude /insights) ---
        # Gate 1: Skip agent sub-sessions
        if title.startswith("agent-") or "facet-extraction" in title.lower():
            filtered_count += 1
            continue
        # Gate 2: Skip sessions with < 2 user messages  
        user_msgs = [m for m in msgs if m.get('type') in ('user', 'human', 'USER')]
        if len(user_msgs) < 2:
            filtered_count += 1
            continue
        
        # Duration calculation
        try:
            parsed_ts = []
            for m in msgs:
                ts_str = m.get("timestamp", "").replace("Z", "+00:00")
                if ts_str: parsed_ts.append(datetime.datetime.fromisoformat(ts_str))
            duration = (max(parsed_ts) - min(parsed_ts)).total_seconds() if len(parsed_ts) > 1 else 0
        except Exception: duration = 0
        
        # Gate 3: Skip sessions shorter than 1 minute
        if duration > 0 and duration < 60:
            filtered_count += 1
            continue
            
        transcript = summarize_long_transcript(msgs)
        processed.append({
            "id": sid, "title": title, "date": s["date"],
            "count": len(msgs), "user_count": len(user_msgs), "duration_sec": duration,
            "tokens": sum(len(str(m.get("message", ""))) for m in msgs) // 4,
            "timestamp": msgs[0].get("timestamp"),
            "transcript_snapshot": transcript
        })
    print(f"  🎯 匹配会话: {len(processed)} (过滤了 {filtered_count} 个低质量会话)")
    return processed

# ALL LLM AND FACET EXTRACTION FUNCTIONS HAVE BEEN REMOVED FOR V8.0
# The Agent will execute these cognitively.

def get_git_stats():
    """Finds .git root by checking parents from current cwd."""
    p = Path.cwd()
    git_root = None
    for _ in range(5): # Up to 5 levels
        if (p / ".git").exists():
            git_root = p
            break
        p = p.parent
    if not git_root: return 0
    try:
        cmd = ["git", "rev-list", "--count", "HEAD", "--since='1 year ago'"]
        return int(subprocess.check_output(cmd, encoding='utf-8', shell=True, cwd=str(git_root)).strip())
    except Exception: return 0

def filter_by_period(sessions, period="30d"):
    """Filter sessions by time period. Supports: 7d, 30d, 90d, year."""
    days = PERIOD_MAP.get(period, 30)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    filtered = [s for s in sessions if s['date'] >= cutoff]
    if not filtered:
        filtered = sessions  # Fallback to all sessions if filter yields nothing
    return filtered

def aggregate_data(sessions, period="30d"):
    filtered = filter_by_period(sessions, period)
    
    # Compute peak activity hours
    hour_counter = Counter()
    for s in filtered:
        ts = s.get("timestamp", "")
        if ts:
            try:
                h = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
                hour_counter[h] += 1
            except Exception: pass
    
    # Compute active streaks
    dates_sorted = sorted(set(s["date"] for s in filtered))
    max_streak = current_streak = 1
    for i in range(1, len(dates_sorted)):
        try:
            d1 = datetime.date.fromisoformat(dates_sorted[i-1])
            d2 = datetime.date.fromisoformat(dates_sorted[i])
            if (d2 - d1).days == 1:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 1
        except Exception: pass
    
    return {
        "period": period,
        "period_label": f"过去 {PERIOD_MAP.get(period, 30)} 天" if period != "year" else f"{datetime.date.today().year} 年度",
        "total_sessions": len(filtered),
        "total_messages": sum(s["count"] for s in filtered),
        "total_duration_hours": sum(s["duration_sec"] for s in filtered) / 3600,
        "total_tokens": sum(s["tokens"] for s in filtered),
        "active_days": len(set(s["date"] for s in filtered)),
        "max_streak": max_streak if dates_sorted else 0,
        "git_commits": get_git_stats(),
        "peak_hours": dict(hour_counter.most_common(5)),
        "daily_activity": dict(Counter(s["date"] for s in filtered)),
    }

# run_comprehensive_analysis has been removed for V8.0
# The Agent will execute these cognitively.

def sync_to_memory(fragment, memory_file=None):
    """Auto-append insight fragment to memory.md with dedup."""
    mf = memory_file or MEMORY_FILE
    header_marker = fragment.strip().split('\n')[0].strip()
    
    existing_content = ""
    if mf.exists():
        existing_content = mf.read_text(encoding='utf-8')
    
    # Prevent duplicate entries for the same audit period
    if header_marker in existing_content:
        # Replace existing block: find start marker to next ## or end
        import re as _re
        pattern = _re.compile(
            _re.escape(header_marker) + r'.*?(?=\n## |\Z)', _re.DOTALL
        )
        updated = pattern.sub(fragment.strip(), existing_content)
        mf.write_text(updated, encoding='utf-8')
        print(f"  🔄 已更新 memory.md 中的审计记录")
    else:
        with open(mf, "a", encoding="utf-8") as f:
            f.write("\n" + fragment.strip() + "\n")
        print(f"  ✅ 已自动追加审计洞察至 {mf.name}")
    return mf
