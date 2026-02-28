import os
import re
import json
import datetime
import subprocess
from pathlib import Path
from collections import Counter, defaultdict

# --- Configuration ---
GEMINI_ROOT = Path(r"C:\Users\shich\.gemini")
SKILL_DIR = GEMINI_ROOT / "skills" / "monthly-personal-insights"
REPORTS_DIR = SKILL_DIR / "reports"
CACHE_FILE = SKILL_DIR / "facets_cache.json"
ASSETS_DIR = SKILL_DIR / "assets"
TEMPLATE_FILE = ASSETS_DIR / "template.html"

# --- Prompts ---
FACET_PROMPT = """Analyze the following Gemini CLI session transcript and extract qualitative facets in JSON format.
Transcript:
{transcript}

Return ONLY a JSON object with these keys:
- goal_category: One of [debug_investigate, implement_feature, fix_bug, write_script_tool, refactor_code, configure_system, create_pr_commit, analyze_data, understand_codebase, write_tests, write_docs, deploy_infra, warmup_minimal, other]
- satisfaction: One of [frustrated, annoyed, neutral, okay, happy, delighted]
- outcome: One of [completed, partial, failed, abandoned, ongoing]
- friction_type: One of [misunderstood_request, wrong_approach, buggy_code, user_rejected_action, claude_got_blocked, excessive_changes, slow_or_verbose, user_unclear, none]
- session_type: One of [single_task, multi_task, exploratory, recursive, interactive_fix]
- success_type: One of [excellent_reasoning, high_velocity, deep_insight, elegant_solution, proactive_fix, thorough_testing, none]
- summary: A 1-sentence summary of the session.
- language: Primary language used.
"""

# --- Mapping Dictionaries ---
GOAL_MAP = {
    "debug_investigate": "调试排查", "implement_feature": "实现功能", "fix_bug": "修复Bug",
    "write_script_tool": "编写脚本", "refactor_code": "重构代码", "configure_system": "系统配置",
    "create_pr_commit": "提交PR", "analyze_data": "数据分析", "understand_codebase": "理解代码",
    "write_tests": "编写测试", "write_docs": "文档撰写", "deploy_infra": "部署运维",
    "warmup_minimal": "热身会话", "other": "其他"
}
SAT_MAP = {
    "frustrated": "😫 沮丧", "annoyed": "😠 烦躁", "neutral": "😐 中立",
    "okay": "🙂 还可以", "happy": "😃 开心", "delighted": "🤩 惊艳"
}
FRIC_MAP = {
    "misunderstood_request": "理解偏差", "wrong_approach": "方案错误", "buggy_code": "代码缺陷",
    "user_rejected_action": "拒绝操作", "claude_got_blocked": "系统卡滞", "excessive_changes": "修改过度",
    "slow_or_verbose": "响应冗长", "user_unclear": "表达不明", "none": "无摩擦"
}
PROFILE_MAP = {
    "Crisis Manager": "危机处理者", "Builder": "高效构建者", "Explorer": "深度探索者", "Steady Operator": "稳健操作员"
}

# --- Core Logic Methods ---

def get_session_list():
    """Returns a list of sessions from `gemini --list-sessions`."""
    try:
        result = subprocess.run(["gemini", "--list-sessions"], capture_output=True, encoding='utf-8', shell=True)
        if result.returncode != 0: return []
        sessions = []
        pattern = re.compile(r"^\s*\d+\.\s+(.*?)\s+\((.*?)\)\s+\[(.*?)\]")
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if match:
                title, time_str, sid = match.groups()
                days_ago = 0
                if "day" in time_str:
                    days_ago = int(re.search(r"\d+", time_str).group())
                elif "hour" in time_str or "minute" in time_str or "Just now" in time_str:
                    days_ago = 0
                date = datetime.date.today() - datetime.timedelta(days=days_ago)
                sessions.append({"id": sid, "title": title, "date": date.isoformat(), "days_ago": days_ago})
        return sessions
    except Exception:
        return []

def read_logs():
    """Reads logs.json from the most recently modified tmp subdirectory."""
    tmp_dir = GEMINI_ROOT / "tmp"
    all_logs = list(tmp_dir.glob("**/logs.json"))
    if not all_logs:
        print("⚠️ 未找到任何 logs.json 文件")
        return []
    log_file = max(all_logs, key=lambda p: p.stat().st_mtime)
    print(f"  📂 使用日志文件: {log_file}")
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list): return []
            return data
    except Exception as e:
        print(f"⚠️ 读取日志异常: {e}")
        return []

def process_sessions(raw_sessions, logs):
    """Correlates logs with raw session IDs and populates necessary fields."""
    session_messages = defaultdict(list)
    for msg in logs:
        session_messages[msg.get("sessionId")].append(msg)
    
    processed = []
    is_cached_mode = (raw_sessions and isinstance(raw_sessions[0], str))
    
    if is_cached_mode:
        for sid in raw_sessions:
            msgs = session_messages.get(sid, [])
            if not msgs: continue
            try:
                ts = [datetime.datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")) for m in msgs]
                duration = (max(ts) - min(ts)).total_seconds()
            except Exception:
                duration = 0
            token_estimate = sum(len(m.get("message", "")) for m in msgs) // 4
            processed.append({
                "id": sid,
                "title": msgs[0].get("message", "Session")[:50],
                "date": msgs[0]["timestamp"][:10],
                "messages": msgs,
                "count": len(msgs),
                "duration_sec": duration,
                "tokens": token_estimate,
                "timestamp": msgs[0]["timestamp"] if msgs else None
            })
    else:
        for s in raw_sessions:
            sid = s["id"]
            msgs = session_messages.get(sid, [])
            if len(msgs) < 2: continue 
            try:
                ts = [datetime.datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")) for m in msgs]
                duration = (max(ts) - min(ts)).total_seconds()
            except Exception:
                duration = 0
            if duration < 60 and len(msgs) < 3: continue 
            token_estimate = sum(len(m.get("message", "")) for m in msgs) // 4 
            processed.append({
                "id": sid,
                "title": s["title"],
                "date": s["date"],
                "messages": msgs,
                "count": len(msgs),
                "duration_sec": duration,
                "tokens": token_estimate,
                "timestamp": msgs[0]["timestamp"] if msgs else None
            })
    return processed

def extract_json_from_text(text):
    """Safely extracts JSON payload from mixed output text."""
    # Pattern 1: Match code blocks (with or without `json` specified)
    pattern1 = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
    match = pattern1.search(text)
    if match:
        return json.loads(match.group(1))
    
    # Pattern 2: Fallback exact JSON block matcher anywhere in text
    pattern2 = re.compile(r"(\{.*\})", re.DOTALL)
    match = pattern2.search(text)
    if match:
        return json.loads(match.group(1))
        
    raise ValueError("Valid JSON not found in model output text")

def extract_facets_builtin(sessions):
    """Uses the `gemini` command to analyze sessions and cache output."""
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception: pass

    new_sessions = [s for s in sessions if s["id"] not in cache]
    to_analyze = new_sessions[:50] 
    
    for s in to_analyze:
        transcript_parts = []
        for m in s["messages"][:15]:
            msg_text = m.get('message', '')
            if len(msg_text) > 500: msg_text = msg_text[:500] + "..."
            transcript_parts.append(f"{m['type'].upper()}: {msg_text}")
        
        transcript = "\n".join(transcript_parts)
        prompt = FACET_PROMPT.format(transcript=transcript)
        
        print(f"  正在分析会话: {s['title'][:40]}...")
        
        try:
            cmd = [
                "gemini", "-p", prompt,
                "--allowed-mcp-server-names", "none",
                "--extensions", "none",
                "--raw-output",
                "--approval-mode", "yolo",
                "--accept-raw-output-risk"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True, encoding='utf-8')
            cache[s["id"]] = extract_json_from_text(result.stdout)
        except Exception as e:
            cache[s["id"]] = {"goal_category": "other", "error": str(e)}
            
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

    for s in sessions:
        s["facets"] = cache.get(s["id"], {"goal_category": "other", "status": "uncached"})
    return sessions

def get_git_stats():
    """Simple calculation of git commits in the last 30 days"""
    try:
        cmd = ["git", "rev-list", "--count", "HEAD", "--since='30 days ago'"]
        commits = subprocess.check_output(cmd, encoding='utf-8', shell=True).strip()
        return int(commits)
    except Exception: return 0

def aggregate_data(sessions):
    """Revolves around extracted facets to compute top-level statistics."""
    stats = {
        "total_sessions": len(sessions),
        "total_messages": sum(s["count"] for s in sessions),
        "total_duration_hours": sum(s["duration_sec"] for s in sessions) / 3600,
        "total_tokens": sum(s["tokens"] for s in sessions),
        "active_days": len(set(s["date"] for s in sessions)),
        "git_commits": get_git_stats(),
        "goal_dist": Counter(s["facets"].get("goal_category", "other") for s in sessions),
        "satisfaction_dist": Counter(s["facets"].get("satisfaction", "neutral") for s in sessions),
        "friction_dist": Counter(s["facets"].get("friction_type", "none") for s in sessions),
        "daily_activity": Counter(s["date"] for s in sessions),
    }
    return stats
