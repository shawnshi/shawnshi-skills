import sys; sys.path.append(r'C:\Users\shich\.gemini\scripts\lib');
"""
<!-- Intelligence Hub: AI Refinement Engine V5.1 (Gemini CLI Integration) -->
@Input: tmp/latest_scan.json, references/strategic_focus.json
@Output: MEMORY/news/intelligence_current_refined.json
@Pos: Phase 2 (Deep Refinement & Deduction)
@Maintenance Protocol: Prompt changes must sync quality_standard.md.
"""
import json
import re
import os
import subprocess
from pathlib import Path
from datetime import datetime
from hub_utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR, clean_json_output
from history_manager import is_redundant

# Resolve paths dynamically
SCAN_PATH = HUB_DIR / "tmp" / "latest_scan.json"
FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"
OUTPUT_PATH = NEWS_DIR / "intelligence_current_refined.json"

# --- System Prompt ---
PROMPT_PATH = HUB_DIR / "references" / "prompts" / "v1_refine_system.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

def score_and_rank(scan_data: dict, focus_data: dict) -> list:
    """Score items by strategic keyword relevance and return sorted list."""
    keywords = {
        kw["keyword"].lower(): kw["weight"]
        for kw in focus_data["strategic_keywords"]
    }
    
    scored = []
    skipped_count = 0
    for item in scan_data["items"]:
        text = (item.get("title", "") + " " + item.get("raw_desc", "")).lower()
        
        # [SEMANTIC DEDUPLICATION] Use text fingerprinting
        is_red = is_redundant(item['url'], item['title'], item['source'])
        if "tripwire" in item['url']:
            print(f"🔍 DEBUG: checking {item['url']}, redundant={is_red}")
            
        if is_red:
            skipped_count += 1
            continue
            
        score = sum(weight for kw, weight in keywords.items() if kw in text)
        scored.append((score, item))

    print(f"🔍 Filtering: {skipped_count} redundant items skipped.")
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def build_user_prompt(scored_items: list, focus_data: dict) -> str:
    """Build the refinement prompt from scored items."""
    kw_lines = ", ".join(
        f"{kw['keyword']}(w={kw['weight']})"
        for kw in sorted(focus_data["strategic_keywords"], key=lambda x: -x["weight"])[:15]
    )

    item_lines = []
    # Send up to top 50 non-redundant items to the LLM for wide translation coverage
    for i, (score, item) in enumerate(scored_items[:50]):
        desc = item.get("raw_desc", "").strip()[:300].replace("\n", " ")
        # Tag items: Top 15 get deep summary, others get simple translation
        tag = "[DEEP_REFINE]" if i < 15 else "[TRANSLATE_ONLY]"
        item_lines.append(
            f"{tag} Item {i+1} [Score={score}]:\n"
            f"Title: {item['title']}\n"
            f"URL: {item['url']}\n"
            f"Source: {item['source']}\n"
            f"Published: {item.get('time', 'Unknown')}\n"
            f"Desc: {desc}\n"
        )

    return f"## ?????????\n{kw_lines}\n\n## ??????\n" + "\n".join(item_lines)


def run_gemini_cli(prompt: str) -> str:
    """Invokes the gemini CLI."""
    try:
        # Run gemini ask
        # We pass the prompt via stdin to avoid command line length limits
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

def refine():
    """Main refinement workflow: score, build prompt, and call Gemini CLI for full JSON payload."""

    if not SCAN_PATH.exists():
        print(f"❌ Error: No scan data found at {SCAN_PATH}")
        print("  Run `python scripts/fetch_news.py` first (Phase 1).")
        return

    scan_data = json.loads(SCAN_PATH.read_text(encoding="utf-8"))
    focus_data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))

    if not scan_data.get("items"):
        print("⚠️ Warning: Scan data has no items. Nothing to refine.")
        return

    scored_items = score_and_rank(scan_data, focus_data)
    print(f"📊 Scored {len(scored_items)} items. Top score: {scored_items[0][0] if scored_items else 0}")

    user_prompt = build_user_prompt(scored_items, focus_data)
    
    full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt

    prompt_path = HUB_DIR / "tmp" / "refinement_prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(full_prompt, encoding="utf-8")

    print(f"🧠 Calling Gemini CLI (gemini ask) for refinement...")
    
    try:
        response_text = run_gemini_cli(full_prompt)
        ai_data = clean_json_output(response_text)

        # Merge with other metadata
        final_output = {
            "generated_at": datetime.now().isoformat(),
            "status": "COMPLETED",
            "model_used": "gemini-cli",
            **ai_data,
            "_scored_preview": [
                {"rank": i+1, "score": s, "title": item["title"][:80], "source": item["source"]}
                for i, (s, item) in enumerate(scored_items[:10])
            ]
        }
        
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(final_output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"✅ Refinement completed! Output saved to: {OUTPUT_PATH}")
        print(f"🔄 Next: Run adversarial audit (optional) or `python scripts/forge.py` (Phase 4).")
        
    except Exception as e:
        print(f"❌ Error during Gemini CLI calling: {str(e)}")
        # Fallback to skeleton if LLM fails
        skeleton = {
            "generated_at": datetime.now().isoformat(),
            "status": f"FAILED: {str(e)}",
            "top_10": [],
            "translations": {},
            "insights": "> 💡 [LLM ERROR]",
            "punchline": "> 💡 [LLM ERROR]",
            "digest": "> 💡 [LLM ERROR]",
            "market": "* [LLM ERROR]",
            "_prompt_path": str(prompt_path),
            "_raw_response": response_text if 'response_text' in locals() else None,
            "_scored_preview": [
                {"rank": i+1, "score": s, "title": item["title"][:80], "source": item["source"]}
                for i, (s, item) in enumerate(scored_items[:10])
            ],
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"📦 Error skeleton created at to: {OUTPUT_PATH}")


if __name__ == "__main__":
    refine()

