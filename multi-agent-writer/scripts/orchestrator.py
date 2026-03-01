"""
<!-- Input: Topic -->
<!-- Output: Automated execution of the Multi-Agent Writer Pipeline (V9.0) -->
<!-- Pos: scripts/orchestrator.py. The V9.0 Automated Engine. -->
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime
import tempfile
import time

STATE_FILE = "project_state.json"
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUMANIZER_BIN = os.path.join(os.path.dirname(SKILL_ROOT), "humanizer-zh-pro", "scripts", "humanize_engine.py")

VALID_PHASES = [
    "0_initiation", "1_roundtable", "2_ghost_deck",
    "3_drafting", "4_audit_humanize", "5_delivery"
]

def read_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ""

def write_file(filepath, content):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def get_project_dir(topic):
    safe_topic = "".join([c for c in topic if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
    if not safe_topic:
        safe_topic = "untitled_project"
    return os.path.join(SKILL_ROOT, "writing_projects", f"{safe_topic}_{datetime.now().strftime('%Y%m%d_%H%M')}")

def run_gemini(prompt):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
        f.write(prompt)
        temp_path = f.name
    try:
        cmd = f"gemini -p (Get-Content -Raw -Path '{temp_path}')"
        process = subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print("[!] Gemini CLI failed:")
            print(stderr)
            return None
        return stdout.strip()
    finally:
        os.remove(temp_path)

def run_humanizer(draft_path):
    try:
        if not os.path.exists(HUMANIZER_BIN):
            print(f"[!] Humanizer engine not found at {HUMANIZER_BIN}")
            return None
        cmd = f"python \"{HUMANIZER_BIN}\" \"{draft_path}\""
        process = subprocess.Popen(["powershell", "-NoProfile", "-Command", cmd],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print("[!] Humanizer engine failed:")
            print(stderr)
            return None
        # Extract the humanized text (ignoring logs/loading info)
        # Assuming the final output is after the "🔪 【Humanizer-zh-pro 文本重铸完毕】 🔪" banner
        if "【Humanizer-zh-pro 文本重铸完毕】" in stdout:
            parts = stdout.split("【Humanizer-zh-pro 文本重铸完毕】 🔪")
            last_part = parts[-1].split("="*60)[-1].strip()
            return last_part if last_part else stdout.strip()
        return stdout.strip()
    except Exception as e:
        print(f"[!] Target humanizer run exception: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Writer V9.0 Orchestrator")
    parser.add_argument("--topic", required=True, help="Topic/Premise of the article")
    parser.add_argument("--audience", default="董事会 / 高级管理层", help="Target Audience")
    parser.add_argument("--goal", default="打破常规认知，提供战略杠杆", help="Non-Consensus Goal")
    args = parser.parse_args()

    topic = args.topic
    audience = args.audience
    goal = args.goal

    project_dir = get_project_dir(topic)
    os.makedirs(project_dir, exist_ok=True)
    
    print(f"\n🚀 [Phase 0] Init. Topic: '{topic}'")
    print(f"Directory created: {project_dir}")

    agents_md = read_file(os.path.join(SKILL_ROOT, "references", "agents.md"))
    templates_md = read_file(os.path.join(SKILL_ROOT, "references", "templates.md"))

    # Phase 1: Roundtable
    print("\n[Phase 1] 🎭 Roundtable: Debate & Conflict...")
    p1_prompt = f"""
你是一名资深的战略主编。请根据以下指导进行"红队圆桌会议"：
主题: {topic}
受众: {audience}
目标: {goal}

【参考资料：角色与模板】
{agents_md}
{templates_md}

请立即扮演 [Subject Expert], [Devil's Advocate], 和 [Managing Partner] 三个角色，进行一轮模拟博弈。
输出格式要求：请严格按照 `templates.md` 中的 [T2: Research Context & Roundtable Consensus] 模板输出会议共识结果，必须包含 3-5 个经得起残酷推敲的核心支柱论点和面临的挑战。
"""
    p1_out = run_gemini(p1_prompt)
    if not p1_out: sys.exit(1)
    write_file(os.path.join(project_dir, "1_roundtable.md"), p1_out)
    print("✅ Phase 1 Complete.")

    # Phase 2: Ghost Deck
    print("\n[Phase 2] 📐 Ghost Deck Architect...")
    p2_prompt = f"""
你是 Ghost Deck 骨架设计师。
这是上一轮的红队博弈共识结果：
{p1_out}

【参考资料：角色与模板】
{agents_md}
{templates_md}

任务：
请严格根据 [T3: Ghost Deck / Article Outline] 模板，输出文章骨架。
由于是 V9.0，针对每个章节的核心视觉逻辑，请你务必直接生成对应的 Mermaid.js 代码块（例如使用 quadrantChart, flowchart, gantt 等绘制 2x2 矩阵、流程图等）。标题必须是包含了判断的"Action Title"（行动标题/判词标题）。不要讲废话，直接输出结果。
"""
    p2_out = run_gemini(p2_prompt)
    if not p2_out: sys.exit(1)
    write_file(os.path.join(project_dir, "2_ghost_deck.md"), p2_out)
    print("✅ Phase 2 Complete.")

    # Phase 3: Drafting
    print("\n[Phase 3] ✍️ Battle-Hardened Drafting...")
    p3_prompt = f"""
你是战地写手 (Battle-Hardened Writer)。
你的主要任务是根据以下批准的【Ghost Deck 骨架】起草具有极致信噪比的战略散文。

【大纲骨架与Mermaid代码】
{p2_out}

【参考指南】
{agents_md}

任务约束：
1. 严格使用金字塔原理，第一段直接抛出核心结论 (Answer-First)。
2. 将骨架中的 Mermaid.js 图表嵌入到正文的适当位置，并围绕解释该图表来叙事。
3. 杜绝毫无意义的过度排版（全篇粗体不超过3处）。
4. 交替使用长短句，塑造心跳节奏感。
5. 请输出最终的文章草稿全文。
"""
    p3_out = run_gemini(p3_prompt)
    if not p3_out: sys.exit(1)
    p3_path = os.path.join(project_dir, "3_drafting.md")
    write_file(p3_path, p3_out)
    print("✅ Phase 3 Complete.")

    # Phase 4: Humanizer
    print("\n[Phase 4] 🧠 Logic Audit & Humanizer Pro Clensing...")
    print(f"Calling Humanizer engine at: {HUMANIZER_BIN}")
    p4_out = run_humanizer(p3_path)
    if not p4_out:
        print("[!] Humanizer failed, falling back to Phase 3 draft.")
        p4_out = p3_out
    write_file(os.path.join(project_dir, "4_humanized.md"), p4_out)
    print("✅ Phase 4 Complete.")

    # Phase 5: Delivery
    print("\n[Phase 5] 📬 Final Forging & Delivery...")
    p5_prompt = f"""
你正在进行最后一步的"交付与残余风险披露" (Phase 5 Delivery)。
以下是经过【重塑与清洗】后的全人类、高管级终稿文本：
{p4_out}

以下是之前第一阶段由于存在激烈分歧而遗留的红队报告要素（参考）：
{p1_out}

请你完成最后加工：
1. 在文章的最前面，添加总计约 150 字的无废话的【执行摘要 (Executive Summary)】。
2. 保持原有文本内容不变（这是经过专业修改器清洗过的，不能再乱动），但在文末附加一个引用块 `> ⚠️ **Residual Risks (残留局限披露)**:`，利用 Phase 1 的红队报告事实，深刻且坦诚地指出本文论证中没被完全消灭的局限性或待验证的假设（以此彰显客观与自信）。
3. 最终输出完整格式的 Markdown 文档。
"""
    p5_out = run_gemini(p5_prompt)
    if not p5_out: sys.exit(1)
    final_path = os.path.join(project_dir, "5_final_delivery.md")
    write_file(final_path, p5_out)
    print(f"✅ Phase 5 Complete.\n🎉 All phases finished! Your final document is at:\n => {final_path}")

if __name__ == "__main__":
    start_time = time.time()
    main()
    print(f"[Done in {round(time.time() - start_time, 2)}s]")
