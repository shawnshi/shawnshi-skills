"""
<!-- Intelligence Hub: Adversarial Audit Engine V5.1 (Gemini CLI) -->
@Input: MEMORY/news/intelligence_current_refined.json
@Output: MEMORY/news/intelligence_current_refined.json (appends audit)
@Pos: Phase 3 (Optional Adversarial Audit)
"""
import json
import os
import subprocess
from pathlib import Path
from datetime import datetime
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

REFINED_PATH = NEWS_DIR / "intelligence_current_refined.json"

SYSTEM_PROMPT = """你是一位无情的「红队」战略审计专家 (Devil's Advocate)。你的任务是挑战并寻找提供的情报推演中的漏洞。

## 任务
阅读以下的【核心判词 (Punchline)】和【战略洞察 (Insights)】。
请尽一切可能使用第一性原理、历史经验或逆向思维，来反驳这些洞察。
寻找其中的「自动化偏见」、「确认偏误」或「盲目乐观」。严禁重复原有的观点。

## 约束
- 保持冷酷、客观、专业的基调
- 不要认同原文的任何观点，你的唯一目的是「进攻」和「压力测试」

## 输出格式 (强制遵守)
必须输出且仅输出一个合法的 JSON 对象。不要输出 Markdown 代码块，不要包含 ```json 的包裹，只输出裸 JSON 数据：

{
  "devil_advocate": "一段300字的红队无情批判",
  "blind_spots": "2-3个关于现有观点的潜在认知盲区，不要使用markdown列表格式，直接输出纯文本",
  "confidence_score": 50 // 1-100的整数，表示原洞察经受住你挑战的置信度
}
"""

def run_gemini_cli(prompt: str) -> str:
    """Invokes the gemini CLI."""
    try:
        process = subprocess.Popen(
            "gemini ask -", 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
            encoding='utf-8',
            errors='ignore'
        )
        stdout, stderr = process.communicate(input=prompt)
        
        if process.returncode != 0:
            raise RuntimeError(f"gemini cli failed: {stderr}")
            
        return stdout.strip()
    except Exception as e:
        raise RuntimeError(f"Failed to execute gemini cli: {e}")

def audit():
    if not REFINED_PATH.exists():
        print(f"❌ Error: Refined data not found at {REFINED_PATH}")
        return

    data = json.loads(REFINED_PATH.read_text(encoding="utf-8"))
    
    insights = data.get("insights", "")
    punchline = data.get("punchline", "")
    
    if not insights or not punchline or "[WAITING]" in insights or "[LLM ERROR]" in insights:
        print("⚠️ Warning: Refined insights are not valid for audit. Skipping.")
        return

    user_prompt = f"## 核心判词 (Punchline)\n{punchline}\n\n## 战略洞察 (Insights)\n{insights}"
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt

    print(f"🛡️ Running Adversarial Audit (Red Teaming via Gemini CLI)...")
    
    try:
        response_text = run_gemini_cli(full_prompt)
        
        # Strip potential markdown formatting
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        response_text = response_text.strip()
        audit_data = json.loads(response_text)
        
        # Append to the original json
        data["adversarial_audit"] = audit_data
        
        REFINED_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Adversarial Audit completed! Critique appended to {REFINED_PATH}")
        
    except Exception as e:
        print(f"❌ Error during Adversarial Audit: {str(e)}")

if __name__ == "__main__":
    audit()
