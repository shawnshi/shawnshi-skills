"""
<!-- Intelligence Hub: Adversarial Audit Engine V5.1 (Gemini CLI) -->
@Input: MEMORY/news/intelligence_current_refined.json
@Output: MEMORY/news/intelligence_current_refined.json (appends audit)
@Pos: Phase 3 (Optional Adversarial Audit)
"""
import json
import re
import os
import subprocess
from pathlib import Path
from datetime import datetime
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

REFINED_PATH = NEWS_DIR / "intelligence_current_refined.json"

PROMPT_PATH = HUB_DIR / "references" / "prompts" / "v1_audit_system.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

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

    # L4 Gateway Guard
    top_10 = data.get("top_10", [])
    has_l4 = any(item.get("intel_grade") == "L4" for item in top_10)
    if not has_l4:
        print("💤 未发现 L4 Alpha 级别情报，跳过昂贵的博弈审计过程。")
        return

    user_prompt = f"## 核心判词 (Punchline)\n{punchline}\n\n## 战略洞察 (Insights)\n{insights}"
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt

    print(f"🛡️ Running Adversarial Audit (Red Teaming via Gemini CLI)...")
    
    try:
        response_text = run_gemini_cli(full_prompt)
        
        # Regex parsing armor for JSON extraction
        match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', response_text)
        if match:
            audit_data = json.loads(match.group(1))
        else:
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
