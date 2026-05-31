import os
import json
import glob
from collections import defaultdict
from datetime import datetime

import os; ROOT_DIR = os.path.expanduser(r"~/.gemini")
TELEMETRY_DIR = os.path.join(ROOT_DIR, "MEMORY", "skill_audit", "telemetry")
SKILLS_DIR = os.path.join(ROOT_DIR, "skills")
REPORT_PATH = os.path.join(ROOT_DIR, "MEMORY", "skill_audit", "System_Entropy_Report.md")

def count_gotchas(skill_name):
    """读取 SKILL.md 物理文件，计算 Gotchas (补丁) 的数量"""
    skill_path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
    if not os.path.exists(skill_path):
        return 0
    
    gotchas_count = 0
    in_gotchas_section = False
    try:
        with open(skill_path, 'r', encoding='utf-8') as f:
            for line in f:
                if "Gotchas" in line or "历史失效先验" in line:
                    in_gotchas_section = True
                    continue
                if in_gotchas_section:
                    if line.startswith("#"): # 进入下一个大段落，退出
                        break
                    # 只匹配真正的无序列表项 (避免匹配到如 *SYS_CHECK:*)
                    if line.strip().startswith("- ") or line.strip().startswith("* "):
                        if "[此处预留" not in line: # 排除默认占位符
                            gotchas_count += 1
    except Exception as e:
        pass
    return gotchas_count

def analyze_telemetry():
    """解析所有遥测 JSON，聚合效用数据"""
    if not os.path.exists(TELEMETRY_DIR):
        os.makedirs(TELEMETRY_DIR, exist_ok=True)
        
    log_files = glob.glob(os.path.join(TELEMETRY_DIR, "*.json"))
    
    # 数据结构: { skill_name: {"total": 0, "success": 0, "fail": 0, "durations": []} }
    stats = defaultdict(lambda: {"total": 0, "success": 0, "fail": 0, "durations": []})
    
    for file in log_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                s_name = data.get("skill_name", "unknown")
                status = data.get("status", "unknown").lower()
                dur = data.get("duration_sec", 0)
                
                stats[s_name]["total"] += 1
                if status == "success":
                    stats[s_name]["success"] += 1
                else:
                    stats[s_name]["fail"] += 1
                    
                if isinstance(dur, (int, float)):
                    stats[s_name]["durations"].append(dur)
        except Exception:
            continue
            
    return stats

def generate_report(stats):
    """生成系统熵增预警报告"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    lines = [
        f"# 系统熵增预警与效用审计报告 (System Entropy Report)",
        f"> **生成时间**: {current_time}",
        f"> **分析引擎**: Utility & Entropy Dashboard (Memento-Skills Protocol)\n",
        "## 1. 技能健康度拓扑 (Skill Health Matrix)\n",
        "| 技能标识 (Skill) | 调用总数 | 胜率 ($U_t$) | 补丁数量 (Gotchas) | 状态预警 (Status) | 建议动作 (Action) |",
        "| :--- | :---: | :---: | :---: | :--- | :--- |"
    ]
    
    for skill, data in sorted(stats.items(), key=lambda x: x[1]['total'], reverse=True):
        if skill == "unknown": continue
        
        total = data["total"]
        success_rate = (data["success"] / total) * 100 if total > 0 else 0
        gotchas = count_gotchas(skill)
        
        # 核心决策逻辑：阈值硬锁
        status = "🟢 鲁棒 (Healthy)"
        action = "维持现状"
        
        if success_rate < 60.0 or gotchas > 4:
            status = "🔴 熵增警报 (CRITICAL)"
            action = "**强制执行细胞分裂 (DiscoverSkill/Fission)**"
        elif success_rate < 85.0 or gotchas >= 2:
            status = "🟡 认知摩擦 (WARNING)"
            action = "执行靶向修补 (.amendify)"
            
        lines.append(f"| `{skill}` | {total} | {success_rate:.1f}% | {gotchas} | {status} | {action} |")
        
    lines.extend([
        "\n## 2. 核心干预指导 (Intervention Mandate)",
        "- **对于 [🔴 CRITICAL] 级技能**：其内部逻辑已发生严重纠缠，大模型覆盖半径过大。严禁继续添加 Gotchas，必须激活 `skill-creator` 将其拆分为两个职责单一的子技能。",
        "- **对于 [🟡 WARNING] 级技能**：存在偶发失败或逻辑断层。可通过 `skill-creator` 的 Unit-Test Gate 执行安全重写。",
        "\n*SYS_CHECK: Dashboard Generated Successfully.*"
    ])
    
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
        
    return REPORT_PATH

if __name__ == "__main__":
    print("[SYSTEM] 正在扫描本地逻辑工厂遥测数据...")
    stats = analyze_telemetry()
    if not stats:
        print("[WARNING] 未发现有效遥测数据，生成基线报告。")
    report_file = generate_report(stats)
    print(f"[SUCCESS] 系统熵增预警报告已落盘: {report_file}")
