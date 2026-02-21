import os
import re
import json
import datetime
import subprocess
import time
from pathlib import Path
from collections import Counter, defaultdict

# --- Configuration ---
GEMINI_ROOT = Path(r"C:\Users\shich\.gemini")
SKILL_DIR = GEMINI_ROOT / "skills" / "monthly-personal-insights"
REPORTS_DIR = SKILL_DIR / "reports"
CACHE_FILE = SKILL_DIR / "facets_cache.json"

# --- Stage 1: Collection ---

def get_session_list():
    """Returns a list of sessions from `gemini --list-sessions`."""
    try:
        result = subprocess.run(["gemini", "--list-sessions"], capture_output=True, encoding='utf-8', shell=True)
        if result.returncode != 0:
            return []
        
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
            if not isinstance(data, list):
                print("⚠️ logs.json 格式异常: 期望列表，得到 " + type(data).__name__)
                return []
            return data
    except json.JSONDecodeError as e:
        print(f"⚠️ logs.json 解析失败: {e}")
        return []
    except Exception as e:
        print(f"⚠️ 读取日志异常: {e}")
        return []

# --- Stage 2 & 3: Filtering & Metadata ---

def process_sessions(raw_sessions, logs):
    session_messages = defaultdict(list)
    for msg in logs:
        session_messages[msg.get("sessionId")].append(msg)
    
    processed = []
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

# --- Stage 4: Facet Extraction (Built-in Gemini CLI) ---

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

def extract_facets_builtin(sessions):
    """Uses the `gemini` command to analyze sessions."""
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
            match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
            if match:
                cache[s["id"]] = json.loads(match.group())
            else:
                cache[s["id"]] = {"goal_category": "other", "error": "JSON not found"}
        except Exception as e:
            cache[s["id"]] = {"goal_category": "other", "error": str(e)}
            
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

    for s in sessions:
        s["facets"] = cache.get(s["id"], {"goal_category": "other", "status": "uncached"})
    return sessions

# --- Stage 5: Aggregation ---

def get_git_stats():
    try:
        cmd = ["git", "rev-list", "--count", "HEAD", "--since='30 days ago'"]
        commits = subprocess.check_output(cmd, encoding='utf-8', shell=True).strip()
        return int(commits)
    except Exception: return 0

def aggregate_data(sessions):
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

# --- Stage 6: Rendering HTML ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Gemini CLI 战略审计报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --primary: #2c3e50;
            --accent: #3498db;
            --success: #27ae60;
            --warning: #f1c40f;
            --danger: #e74c3c;
            --bg: #f8f9fa;
            --text-secondary: #7f8c8d;
        }}
        body {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--primary); margin: 0; padding: 40px 20px; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{ 
            background: linear-gradient(135deg, #1a2a3a 0%, #2c3e50 100%); 
            color: white; padding: 40px; border-radius: 16px; margin-bottom: 30px; 
            text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.1);
        }}
        header h1 {{ margin: 0; font-size: 32px; letter-spacing: 2px; }}
        
        .section-header {{ margin: 40px 0 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; display: flex; align-items: center; gap: 10px; }}
        .interpretation {{ margin-top: 15px; padding: 15px; background: #fcfcfc; border-radius: 8px; font-size: 14px; border-left: 4px solid var(--accent); color: #555; }}
        
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 20px; }}
        .card {{ 
            background: white; padding: 25px; border-radius: 16px; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center;
        }}
        .card h3 {{ margin: 0; font-size: 13px; color: var(--text-secondary); text-transform: uppercase; }}
        .card p {{ margin: 10px 0 0; font-size: 32px; font-weight: 800; color: var(--primary); }}

        .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 30px; }}
        .chart-box {{ 
            background: white; padding: 30px; border-radius: 16px; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.05); display: flex; flex-direction: column;
        }}
        .chart-container {{ flex-grow: 1; min-height: 300px; position: relative; }}

        .insights {{ 
            background: white; padding: 40px; border-radius: 16px; 
            box-shadow: 0 4px 15px rgba(0,0,0,0.05); 
        }}
        .insight-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }}
        .insight-item {{ padding: 20px; border-radius: 12px; background: #fdfdfd; border: 1px solid #eee; }}
        .insight-item h4 {{ margin: 0 0 10px; color: var(--accent); }}
        
        .footer {{ text-align: center; color: #bdc3c7; font-size: 13px; margin-top: 60px; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 个人数字化战略审计报告</h1>
            <p>周期: {period_start} 至 {period_end} | 状态: 已归档</p>
        </header>

        <h2 class="section-header">📊 核心产出指标</h2>
        <div class="grid">
            <div class="card"><h3>总会话数</h3><p>{total_sessions}</p></div>
            <div class="card"><h3>累计时长 (h)</h3><p>{total_hours:.1f}</p></div>
            <div class="card"><h3>Git 提交</h3><p>{git_commits}</p></div>
            <div class="card"><h3>活跃天数</h3><p>{active_days}/30</p></div>
        </div>
        <div class="interpretation">
            <strong>指标解读：</strong> {stats_interpretation}
        </div>

        <h2 class="section-header">📈 行为与意图扫描</h2>
        <div class="charts">
            <div class="chart-box">
                <h2>活动趋势 (心流稳定性)</h2>
                <div class="chart-container"><canvas id="dailyChart"></canvas></div>
                <div class="interpretation"><strong>走势分析：</strong> {daily_interpretation}</div>
            </div>
            <div class="chart-box">
                <h2>任务目标分布 (精力分配)</h2>
                <div class="chart-container"><canvas id="goalChart"></canvas></div>
                <div class="interpretation"><strong>意图拆解：</strong> {goal_interpretation}</div>
            </div>
            <div class="chart-box">
                <h2>交互满意度 (心流质量)</h2>
                <div class="chart-container"><canvas id="satChart"></canvas></div>
                <div class="interpretation"><strong>心流评价：</strong> {sat_interpretation}</div>
            </div>
            <div class="chart-box">
                <h2>流程摩擦点 (系统损耗)</h2>
                <div class="chart-container"><canvas id="fricChart"></canvas></div>
                <div class="interpretation"><strong>阻力诊断：</strong> {fric_interpretation}</div>
            </div>
        </div>

        <h2 class="section-header">💡 战略诊断与进化建议</h2>
        <div class="insights">
            <div class="insight-grid">
                <div class="insight-item">
                    <h4>🎯 核心生产力领域</h4>
                    <p>您的重心主要在 <strong>{top_goal}</strong>，占总会话的 <strong>{top_goal_pct:.1f}%</strong>。{insight_goal}</p>
                </div>
                <div class="insight-item">
                    <h4>🚧 流程自愈策略</h4>
                    <p>针对 <strong>{top_friction}</strong> 摩擦，建议在 <code>coding.md</code> 引入自动容错协议。{insight_fric}</p>
                </div>
                <div class="insight-item">
                    <h4>👤 交互风格画像</h4>
                    <p>当前风格定义为 <strong>{profile}</strong>。满意度常模为 <strong>{avg_satisfaction}</strong>。{insight_profile}</p>
                </div>
                <div class="insight-item">
                    <h4>🎁 彩蛋：不可磨灭的瞬间</h4>
                    <p>{easter_egg}</p>
                </div>
            </div>
        </div>

        <div class="footer">
            由 monthly-personal-insights v4.1 生成 | 架构师视角 | {timestamp}
        </div>
    </div>

    <script>
        const colors = ['#3498db', '#2ecc71', '#e74c3c', '#f1c40f', '#9b59b6', '#34495e', '#1abc9c', '#e67e22'];
        
        new Chart(document.getElementById('dailyChart'), {{
            type: 'line',
            data: {{
                labels: {daily_labels},
                datasets: [{{ label: '每日会话数', data: {daily_data}, borderColor: '#3498db', backgroundColor: 'rgba(52, 152, 219, 0.1)', fill: true, tension: 0.4 }}]
            }},
            options: {{ maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
        }});

        new Chart(document.getElementById('goalChart'), {{
            type: 'doughnut',
            data: {{
                labels: {goal_labels},
                datasets: [{{ data: {goal_data}, backgroundColor: colors }}]
            }},
            options: {{ maintainAspectRatio: false, cutout: '70%' }}
        }});

        new Chart(document.getElementById('satChart'), {{
            type: 'bar',
            data: {{
                labels: {sat_labels},
                datasets: [{{ label: '会话数', data: {sat_data}, backgroundColor: '#27ae60', borderRadius: 8 }}]
            }},
            options: {{ maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
        }});

        new Chart(document.getElementById('fricChart'), {{
            type: 'pie',
            data: {{
                labels: {fric_labels},
                datasets: [{{ data: {fric_data}, backgroundColor: ['#e74c3c', '#e67e22', '#f39c12', '#95a5a6'] }}]
            }},
            options: {{ maintainAspectRatio: false }}
        }});
    </script>
</body>
</html>
"""

def generate_report(stats, sessions):
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
    
    # 📊 Core Stats Interpretation
    if active > 20:
        stats_interp = f"呈现典型的‘数字原生’特征。交互密度极高（日均 {hours_per_active_day:.1f} 小时），表明 AI 已非辅助工具，而是您思维架构的实时延伸。当前系统熵值受控，但需警惕过度依赖导致的认知带宽收缩。"
    elif total > 40:
        stats_interp = f"高频碎片化协作模式。平均每会话消息数仅 {avg_msg_per_session:.1f} 条，暗示您倾向于将 AI 用于快速验证或微小任务。建议整合相关需求进入‘深度会话’，以利用大模型的长上下文推理优势。"
    else:
        stats_interp = "任务驱动型协作。交互主要集中在特定交付目标上，系统运行负载分布均衡，处于典型的‘杠杆利用’阶段。"

    # 📈 Daily Flow Interpretation
    volatility = max(daily_data) - min(daily_data) if daily_data else 0
    if volatility > 8:
        daily_interp = "典型的‘潮汐式’工作流。剧烈的波动反映出您正处于从‘战略规划’到‘高强度工程交付’的快速切换中。这种模式心流质量极高，但二阶效应是系统维护（如鉴权管理）可能在高峰期被忽视，导致后续摩擦。"
    else:
        daily_interp = "线性平稳走势。这是一种极度自律的‘架构师节奏’，表明项目边界清晰，需求涌现速度与处理速度完全匹配，系统熵增速度处于历史低位。"

    # 🎯 Goal Intent Decomposition
    raw_top_goal = list(stats["goal_dist"].keys())[goal_data.index(max(goal_data))] if goal_data else "other"
    top_goal = GOAL_MAP.get(raw_top_goal, raw_top_goal)
    top_goal_pct = (max(goal_data) / stats["total_sessions"] * 100) if stats["total_sessions"] else 0
    if raw_top_goal in ["fix_bug", "debug_investigate"]:
        goal_interp = f"呈现‘防御性堡垒’特征。重心在 {top_goal} 表明当前工具链或新引入的代码库存在明显的‘逻辑债务’。您正在通过高频的人工干预来维持系统稳定性，而非在边界上扩张。"
    elif raw_top_goal in ["implement_feature", "write_script_tool"]:
        goal_interp = f"纯粹的‘开拓者’模式。{top_goal} 的高占比意味着您正处于数字资产的爆发式增长期。当前最重要的不是修复，而是‘架构原型’的快速固化，确保新功能不成为未来的技术摩擦源。"
    elif raw_top_goal in ["refactor_code"]:
        goal_interp = "处于‘系统性熵减’阶段。您正在通过重构来消除过去累积的复杂性。这是高阶开发者的标志性行为，预示着下个月将迎来更高效率的交付窗口。"
    else:
        goal_interp = "多维意图混合。任务目标在研究、开发与运维间均匀分布，表明您正在管理一个复杂的全生命周期项目，当前的挑战在于‘上下文切换’的心理成本。"

    # 😊 Flow Quality Interpretation
    avg_sat_raw = list(stats["satisfaction_dist"].keys())[sat_data.index(max(sat_data))] if sat_data else "neutral"
    if avg_sat_raw in ["happy", "delighted"]:
        sat_interp = "‘人机合一’的巅峰心流。数据证明当前的交互协议（Prompt / memory.md）与模型能力的匹配度已达到局部最优解。建议固化当前的协作范式，作为后续技能开发的‘黄金模版’。"
    elif avg_sat_raw in ["frustrated", "annoyed"]:
        sat_interp = "严重的‘认知摩擦’。满意的低迷通常源于模型对复杂指令的‘漂移’或环境配置的频繁失效。这需要一次彻底的‘系统性审计’，而非碎片化的修复。"
    else:
        sat_interp = "‘稳态协作’体验。交互基本符合预期，但缺乏‘意外之喜’。这通常意味着您在使用 AI 的稳健功能，尚未充分探索其在边界案例中的‘非共识洞察’能力。"

    # ⚠️ Friction Diagnosis
    raw_top_fric = list(stats["friction_dist"].keys())[fric_data.index(max(fric_data))] if fric_data else "none"
    top_friction = FRIC_MAP.get(raw_top_fric, raw_top_fric)
    if raw_top_fric == "none":
        fric_interp = "无阻力运行。系统阻力几乎消失，这往往出现在开发者对工具链有绝对控制权的阶段。当前的重点应放在‘提升任务复杂度’，以测试系统的压力上限。"
    elif raw_top_fric == "misunderstood_request":
        fric_interp = "‘语义鸿沟’是第一阻力。模型频繁在指令理解上偏差，反映出交互协议中缺乏‘业务上下文’。建议在 `memory.md` 中增加更具象的‘行业术语定义’和‘角色行为约束’。"
    elif raw_top_fric == "buggy_code":
        fric_interp = "‘逻辑健壮性’缺失。代码产出虽然快，但二次纠错成本高。应在 `coding.md` 中强制执行‘先写测试，再写逻辑’的 TDD 协议，将摩擦力在生成阶段消除。"
    else:
        fric_interp = f"检测到由 {top_friction} 引起的系统损耗。这类摩擦属于‘低价值损耗’，建议通过自动化脚本或环境预检逻辑进行根治。"

    # 💡 Strategic Insight Deepening
    if "构建" in goal_interp or "开拓" in goal_interp:
        insight_goal = "这标志着您正处于一个关键的‘生产力跃迁’期。建议将本月产出的核心逻辑抽象为通用技能，避免在下个项目中重复造轮子。"
    else:
        insight_goal = "当前处于‘战略相持阶段’。大量时间消耗在存量系统的维护上。建议进行一次‘技术债清算’，集中解决高频报错点，释放交付带宽。"

    if raw_top_fric != "none":
        insight_fric = f"针对 {top_friction} 的高频出现，您的 `coding.md` 协议需要增加一个‘前置校验层’。例如：在执行复杂操作前，要求 Agent 先口头复述其理解的约束条件，强制对齐语义。"
    else:
        insight_fric = "当前的流畅度是极其宝贵的资产。建议开始探索更复杂的‘多 Agent 协作流’，利用目前的稳定环境进行更前沿的架构实验。"
    
    if raw_top_goal in ["debug_investigate", "fix_bug"]: profile_key = "Crisis Manager"
    elif raw_top_goal in ["implement_feature", "write_script_tool"]: profile_key = "Builder"
    elif raw_top_goal in ["research", "analyze_data"]: profile_key = "Explorer"
    else: profile_key = "Steady Operator"
    profile = PROFILE_MAP.get(profile_key, profile_key)
    
    if profile_key == "Builder":
        insight_profile = "您是‘结果导向型’架构师。建议在 `memory.md` 中强化‘项目交付标准’，让 Agent 能在生成代码时自动对照您的‘美学与稳健性’基准。"
    elif profile_key == "Explorer":
        insight_profile = "您是‘认知导向型’决策者。建议引入更多的研究类 Agent 技能，并优化搜索引擎插件的调用深度，以支撑您的深度洞察需求。"
    else:
        insight_profile = "您更倾向于‘精细化管控’模式。建议在 `coding.md` 中进一步细化‘文件修改协议’，减少 Agent 在文件编辑时的误伤率。"

    easter_egg = "本月暂无特定成功高光记录。"
    memorable = [s for s in sessions if s["facets"].get("success_type") not in ["none", None]]
    if memorable:
        success_title = memorable[0]['title']
        success_type = memorable[0]['facets'].get('success_type', '')
        easter_egg = f"在会话 <strong>'{success_title}'</strong> 中，您通过 <strong>'{success_type}'</strong> 实现了极高的交付效率，这种心流状态值得保持。"

    html = HTML_TEMPLATE.format(
        period_start=daily_labels[0] if daily_labels else "N/A",
        period_end=daily_labels[-1] if daily_labels else "N/A",
        total_sessions=stats["total_sessions"],
        total_hours=stats["total_duration_hours"],
        git_commits=stats["git_commits"],
        active_days=stats["active_days"],
        stats_interpretation=stats_interp,
        daily_labels=json.dumps(daily_labels),
        daily_data=json.dumps(daily_data),
        daily_interpretation=daily_interp,
        goal_labels=json.dumps(goal_labels),
        goal_data=json.dumps(goal_data),
        goal_interpretation=goal_interp,
        sat_labels=json.dumps(sat_labels),
        sat_data=json.dumps(sat_data),
        sat_interpretation=sat_interp,
        fric_labels=json.dumps(fric_labels),
        fric_data=json.dumps(fric_data),
        fric_interpretation=fric_interp,
        top_goal=top_goal,
        top_goal_pct=top_goal_pct,
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
