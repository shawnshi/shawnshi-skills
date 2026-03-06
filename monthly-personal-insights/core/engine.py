import os
import re
import json
import datetime
import subprocess
import threading
from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# --- Prompts ---
FACET_PROMPT = """Analyze this AI coding assistant session and extract structured facets.
CRITICAL GUIDELINES:
1. **goal_categories**: Count ONLY what the USER explicitly asked for.
   - ONLY count when user says "can you...", "please...", "I need...", etc.
2. **user_satisfaction_counts**: Base ONLY on explicit user signals.
   - "great!", "perfect!" -> happy
   - "thanks", "looks good" -> satisfied
   - continuing without complaint -> likely_satisfied
   - "that's not right", "try again" -> dissatisfied
   - "this is broken" -> frustrated
3. **friction_counts**: Be specific about what went wrong.
4. If very short or just warmup, use warmup_minimal for goal_category.

SESSION:
{transcript}

RESPOND WITH ONLY A VALID JSON OBJECT matching this schema:
{{
    "underlying_goal": "What the user fundamentally wanted to achieve",
    "goal_categories": {{"category_name": count}},
    "outcome": "fully_achieved | mostly_achieved | partially_achieved | not_achieved | unclear",
    "user_satisfaction_counts": {{"level": count}},
    "claude_helpfulness": "unhelpful | slightly_helpful | moderately_helpful | very_helpful | essential",
    "session_type": "single_task | multi_task | iterative_refinement | exploration | quick_question",
    "friction_counts": {{"friction_type": count}},
    "friction_detail": "One sentence describing friction or empty",
    "primary_success": "none | fast_accurate_search | correct_code_edits | good_explanations | proactive_help | multi_file_changes | good_debugging",
    "emotional_tone": "anxious | frustrated | neutral | focused | flow | excited",
    "topic_tags": ["tag1", "tag2"],
    "brief_summary": "One sentence: what user wanted and whether they got it"
}}

Valid goal categories: debug_investigate, implement_feature, fix_bug, write_script_tool, refactor_code, configure_system, create_pr_commit, analyze_data, understand_codebase, write_tests, write_docs, deploy_infra, warmup_minimal, other
Valid friction types: misunderstood_request, wrong_approach, buggy_code, user_rejected_action, claude_got_blocked, excessive_changes, slow_or_verbose, user_unclear, wrong_file_or_location, tool_failed, external_issue, none
Valid satisfaction levels: frustrated, dissatisfied, likely_satisfied, satisfied, happy, unsure
"""

SUMMARIZE_PROMPT = """Summarize this portion of an AI coding session transcript. Focus on:
1. What the user asked for
2. What the AI did (tools used, files modified)
3. Any friction or issues
4. The outcome
Keep it concise - 3-5 sentences. Preserve specific details like file names, error messages, and user feedback.

TRANSCRIPT CHUNK:
{chunk}
"""

# --- Stage 4 Specialized Analysis Prompts ---
PROJECT_AREAS_PROMPT = """Analyze this usage data and identify project areas.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "areas": [ {{ "name": "Area name", "session_count": N, "description": "2-3 sentences about what was worked on." }} ] }}
Include 4-5 areas.

DATA:
{data}
"""

INTERACTION_STYLE_PROMPT = """Analyze this usage data and describe the user's interaction style.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "narrative": "2-3 paragraphs analyzing HOW the user interacts. Use second person 'you'. Use **bold** for key insights.", "key_pattern": "One sentence summary of most distinctive interaction style" }}

DATA:
{data}
"""

WHAT_WORKS_PROMPT = """Analyze this usage data and identify what's working well. Use second person.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "intro": "1 sentence of context", "impressive_workflows": [ {{ "title": "Short title", "description": "2-3 sentences describing the impressive workflow." }} ] }}
Include 3 impressive workflows.

DATA:
{data}
"""

FRICTION_ANALYSIS_PROMPT = """Analyze this usage data and identify friction points. Use second person.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "intro": "1 sentence summarizing friction patterns", "categories": [ {{ "category": "Name", "description": "1-2 sentences.", "examples": ["Specific example", "Another"] }} ] }}
Include 3 friction categories with 2 examples each.

DATA:
{data}
"""

SUGGESTIONS_PROMPT = """Analyze this usage data and suggest improvements for the user's AI coding workflow.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "config_additions": [ {{ "addition": "A specific rule or instruction to add to the AI config", "why": "1 sentence why" }} ], "usage_patterns": [ {{ "title": "Short title", "suggestion": "1-2 sentence summary", "detail": "3-4 sentences explaining how this applies" }} ] }}
Include 2-3 items for each category. PRIORITIZE instructions that appear MULTIPLE TIMES in the data.

DATA:
{data}
"""

ON_THE_HORIZON_PROMPT = """Analyze this usage data and identify future opportunities for AI-assisted development.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "intro": "1 sentence about evolving AI-assisted development", "opportunities": [ {{ "title": "Short title", "whats_possible": "2-3 ambitious sentences", "how_to_try": "1-2 sentences" }} ] }}
Include 3 opportunities. Think BIG - autonomous workflows, parallel agents.

DATA:
{data}
"""

FUN_ENDING_PROMPT = """Analyze this usage data and find a memorable moment.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "headline": "A memorable qualitative moment - something human, funny, or surprising.", "detail": "Brief context about when/where this happened" }}

DATA:
{data}
"""

AT_A_GLANCE_PROMPT = """Write an "At a Glance" summary for an AI coding usage insights report. Use this 4-part structure:
1. **What's working** - User's unique interaction style and impactful accomplishments.
2. **What's hindering** - Split into (a) AI's fault and (b) user-side friction. Be honest but constructive.
3. **Quick wins to try** - Specific workflow techniques.
4. **Ambitious workflows** - What workflows will become possible with better models?
Keep each section to 2-3 sentences. Use a coaching tone.
RESPOND WITH ONLY A VALID JSON OBJECT:
{{ "whats_working": "...", "whats_hindering": "...", "quick_wins": "...", "ambitious_workflows": "..." }}

DATA:
{data}

PREVIOUS INSIGHTS:
{insights}
"""

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
        for p in skills_dir.rglob("*"):
            if p.is_file() and p.stat().st_mtime > cutoff:
                recent.append({"path": str(p.relative_to(skills_dir)), "modified": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat()})
    return recent

def summarize_long_transcript(messages, max_chars=30000, chunk_size=25000):
    """Stage 2: Summarize long transcripts in chunks before facet extraction."""
    full_text = "\n".join([f"{m.get('type','UNK').upper()}: {str(m.get('message',''))[:1000]}" for m in messages])
    if len(full_text) <= max_chars:
        return full_text
    
    # Split into chunks and summarize each
    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
    summaries = []
    for i, chunk in enumerate(chunks[:5]):  # Max 5 chunks
        prompt = SUMMARIZE_PROMPT.format(chunk=chunk)
        try:
            cmd = ["gemini", "-p", prompt, "--raw-output", "--approval-mode", "yolo", "--accept-raw-output-risk"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True, encoding='utf-8', errors='ignore', cwd=str(GEMINI_ROOT), timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                summaries.append(result.stdout.strip())
            else:
                summaries.append(chunk[:500] + "...")
        except Exception:
            summaries.append(chunk[:500] + "...")
    
    return "\n---\n".join(summaries)

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
            
        processed.append({
            "id": sid, "title": title, "date": s["date"], "messages": msgs,
            "count": len(msgs), "user_count": len(user_msgs), "duration_sec": duration,
            "tokens": sum(len(str(m.get("message", ""))) for m in msgs) // 4,
            "timestamp": msgs[0].get("timestamp")
        })
    print(f"  🎯 匹配会话: {len(processed)} (过滤了 {filtered_count} 个低质量会话)")
    return processed

def run_llm_prompt(prompt, timeout=120):
    """Utility: Run a prompt via gemini CLI and return parsed JSON or raw text."""
    try:
        cmd = ["gemini", "-p", prompt, "--raw-output", "--approval-mode", "yolo", "--accept-raw-output-risk"]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True, encoding='utf-8', errors='ignore', cwd=str(GEMINI_ROOT), timeout=timeout)
        if result.returncode == 0 and result.stdout.strip():
            try:
                return extract_json_from_text(result.stdout)
            except Exception:
                return result.stdout.strip()
    except Exception:
        pass
    return None

def extract_json_from_text(text):
    pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if match: return json.loads(match.group(1))
    pattern2 = re.compile(r"(\{.*\})", re.DOTALL)
    match = pattern2.search(text)
    if match: return json.loads(match.group(1))
    raise ValueError("JSON not found")

def analyze_session_fallback(s):
    """Rule-based fallback when gemini CLI is unavailable. Returns count-based schema."""
    text = " ".join([str(m.get('message', '')) for m in s["messages"][:20]]).lower()
    
    # Goal detection by keywords
    goal = "other"
    goal_keywords = {
        "debug_investigate": ["debug", "error", "traceback", "调试", "报错"],
        "implement_feature": ["implement", "add feature", "实现", "新增"],
        "fix_bug": ["fix", "bug", "修复"],
        "write_script_tool": ["script", "tool", "automate", "脚本"],
        "refactor_code": ["refactor", "重构", "优化"],
        "configure_system": ["config", "setup", "配置"],
        "analyze_data": ["analyze", "analysis", "分析"],
        "write_docs": ["doc", "readme", "文档"],
    }
    for cat, kws in goal_keywords.items():
        if any(kw in text for kw in kws):
            goal = cat
            break
    
    # Friction detection
    friction = "none"
    if any(w in text for w in ["error", "fail", "失败"]): friction = "buggy_code"
    elif any(w in text for w in ["wrong", "不对", "错误"]): friction = "misunderstood_request"
    
    # Satisfaction heuristic
    sat = "likely_satisfied"
    if any(w in text for w in ["✅", "完成", "done", "perfect", "great"]): sat = "happy"
    elif any(w in text for w in ["❌", "失败", "fail"]): sat = "frustrated"
    
    return s["id"], {
        "underlying_goal": "Rule-based: unable to determine",
        "goal_categories": {goal: 1},
        "outcome": "unclear",
        "user_satisfaction_counts": {sat: 1},
        "claude_helpfulness": "moderately_helpful",
        "session_type": "single_task",
        "friction_counts": {friction: 1} if friction != "none" else {},
        "friction_detail": "",
        "primary_success": "none",
        "emotional_tone": "neutral",
        "topic_tags": [],
        "brief_summary": "Rule-based fallback analysis"
    }

def analyze_session(s):
    """Worker: Stage 2+3 combined. Summarize long transcripts, then extract facets."""
    # Stage 2: Transcript summarization for long sessions
    transcript = summarize_long_transcript(s["messages"])
    prompt = FACET_PROMPT.format(transcript=transcript[:15000])  # Safety cap
    try:
        cmd = ["gemini", "-p", prompt, "--raw-output", "--approval-mode", "yolo", "--accept-raw-output-risk"]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True, encoding='utf-8', errors='ignore', cwd=str(GEMINI_ROOT), timeout=120)
        if result.returncode == 0:
            facets = extract_json_from_text(result.stdout)
            return s["id"], facets
    except subprocess.TimeoutExpired:
        print(f"    ⏱️ 会话 {s['id'][:8]} 超时，回退规则引擎")
    except Exception:
        pass
    return analyze_session_fallback(s)

def extract_facets_builtin(sessions):
    cache = {}
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f: cache = json.load(f)
        except Exception: pass
    
    sessions.sort(key=lambda x: x['date'], reverse=True)
    current_year = str(datetime.date.today().year)
    year_sessions = [s for s in sessions if s['date'].startswith(current_year)]
    new_sessions = [s for s in year_sessions if s["id"] not in cache]
    
    batch_size = 50
    max_workers = 10
    
    if new_sessions:
        to_process = new_sessions[:batch_size]
        print(f"  ✨ 启动并行分析: {len(to_process)} 个会话 (线程数: {max_workers})...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_sid = {executor.submit(analyze_session, s): s["id"] for s in to_process}
            for future in as_completed(future_to_sid):
                sid, facets = future.result()
                with cache_lock:
                    cache[sid] = facets
                print(f"    ✅ 已处理: {sid[:8]}...")
        
        # Batch flush cache after all analyses complete
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        print(f"  💾 缓存已批量写入 ({len(cache)} 条)")

    for s in sessions: s["facets"] = cache.get(s["id"], {"goal_category": "other"})
    return sessions

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
    # Build topic cloud and aggregate count-based facets
    topic_counter = Counter()
    goal_counter = Counter()
    sat_counter = Counter()
    fric_counter = Counter()
    helpfulness_counter = Counter()
    session_type_counter = Counter()
    outcome_counter = Counter()
    
    for s in filtered:
        f = s["facets"]
        tags = f.get("topic_tags", [])
        if isinstance(tags, list):
            topic_counter.update(tags)
        
        # Handle both count-based (v7) and single-label (v6 cache) facets
        gc = f.get("goal_categories")
        if isinstance(gc, dict):
            goal_counter.update(gc)
        else:
            goal_counter[f.get("goal_category", f.get("goal_categories", "other"))] += 1
        
        sc = f.get("user_satisfaction_counts")
        if isinstance(sc, dict):
            sat_counter.update(sc)
        else:
            sat_counter[f.get("satisfaction", f.get("user_satisfaction_counts", "likely_satisfied"))] += 1
        
        fc = f.get("friction_counts")
        if isinstance(fc, dict):
            fric_counter.update(fc)
        else:
            ft = f.get("friction_type", "none")
            if ft != "none":
                fric_counter[ft] += 1
        
        helpfulness_counter[f.get("claude_helpfulness", "moderately_helpful")] += 1
        session_type_counter[f.get("session_type", "single_task")] += 1
        outcome_counter[f.get("outcome", "unclear")] += 1
    
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
    
    # Collect summaries and friction details for Stage 4
    summaries = [s["facets"].get("brief_summary", s["facets"].get("summary", "")) for s in filtered[:50]]
    friction_details = [s["facets"].get("friction_detail", "") for s in filtered if s["facets"].get("friction_detail")]
    underlying_goals = [s["facets"].get("underlying_goal", "") for s in filtered if s["facets"].get("underlying_goal")]
    
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
        "goal_dist": goal_counter,
        "satisfaction_dist": sat_counter,
        "friction_dist": fric_counter,
        "helpfulness_dist": helpfulness_counter,
        "session_type_dist": session_type_counter,
        "outcome_dist": outcome_counter,
        "emotional_tone_dist": Counter(s["facets"].get("emotional_tone", "neutral") for s in filtered),
        "topic_cloud": dict(topic_counter.most_common(15)),
        "peak_hours": dict(hour_counter.most_common(5)),
        "daily_activity": Counter(s["date"] for s in filtered),
        "_summaries": summaries[:50],
        "_friction_details": friction_details[:20],
        "_underlying_goals": underlying_goals[:30],
    }

def run_specialized_analyses(stats):
    """Stage 4: Run 7 specialized analysis prompts against aggregated data."""
    # Build data payload (exclude internal fields starting with _)
    data_payload = json.dumps({k: v for k, v in stats.items() if not k.startswith('_') and not isinstance(v, Counter)}, ensure_ascii=False, default=str, indent=1)[:8000]
    # Add text summaries
    data_payload += "\n\nSESSION SUMMARIES:\n" + "\n".join(stats.get('_summaries', [])[:30])
    data_payload += "\n\nFRICTION DETAILS:\n" + "\n".join(stats.get('_friction_details', [])[:15])
    
    insights = {}
    prompts = {
        "project_areas": PROJECT_AREAS_PROMPT,
        "interaction_style": INTERACTION_STYLE_PROMPT,
        "what_works": WHAT_WORKS_PROMPT,
        "friction_analysis": FRICTION_ANALYSIS_PROMPT,
        "suggestions": SUGGESTIONS_PROMPT,
        "on_the_horizon": ON_THE_HORIZON_PROMPT,
        "fun_ending": FUN_ENDING_PROMPT,
    }
    
    for key, prompt_template in prompts.items():
        print(f"    🧠 Stage 4 [{key}]...")
        result = run_llm_prompt(prompt_template.format(data=data_payload), timeout=90)
        insights[key] = result or {}
    
    return insights

def generate_executive_summary(stats, insights):
    """Stage 5: At a Glance summary synthesizing all Stage 4 insights."""
    data_payload = json.dumps({k: v for k, v in stats.items() if not k.startswith('_') and not isinstance(v, Counter)}, ensure_ascii=False, default=str, indent=1)[:4000]
    insights_payload = json.dumps(insights, ensure_ascii=False, default=str, indent=1)[:6000]
    
    print("    🎯 Stage 5 [at_a_glance]...")
    result = run_llm_prompt(AT_A_GLANCE_PROMPT.format(data=data_payload, insights=insights_payload), timeout=90)
    return result or {"whats_working": "", "whats_hindering": "", "quick_wins": "", "ambitious_workflows": ""}

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
