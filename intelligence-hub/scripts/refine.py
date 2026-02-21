"""
<!-- Intelligence Hub: AI Refinement Engine V1.0 -->
@Input: tmp/latest_scan.json, references/strategic_focus.json
@Output: MEMORY/news/intelligence_current_refined.json
@Pos: Phase 2 (Deep Refinement & Deduction)
@Maintenance Protocol: Prompt changes must sync quality_standard.md.
"""
import json
import os
from pathlib import Path
from datetime import datetime
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

# Resolve paths dynamically
SCAN_PATH = HUB_DIR / "tmp" / "latest_scan.json"
FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"
OUTPUT_PATH = NEWS_DIR / "intelligence_current_refined.json"

# --- Prompt Template for AI Refinement ---
REFINEMENT_PROMPT = """你是一位战略情报分析师。请对以下新闻条目进行「二阶推演」精炼：

## 任务
1. 从以下 {count} 条原始情报中，**筛选出 Top 10** 最具战略价值的条目
2. 为每条 Top 10 提供：中文标题、约100字的中文深度摘要、推荐理由
3. 为剩余的条目提供简单的**中文标题与简介翻译**
4. 生成以下四个战略模块：
   - **insights**: 3-5 条今日核心洞察（编号列表）
   - **punchline**: 一句话核心判词
   - **digest**: 200 字二阶推演摘要
   - **market**: 市场动态要点（3-5 条）

## 质量标准
- 禁止使用形容词修饰（如"重大进展"、"革命性"）
- 每条摘要必须包含：事实 → 联结 → 推演 三段论
- 优先筛选反直觉或非共识情报

## 当前战略关键词权重
{keywords}

## 原始情报清单
{items}

## 输出格式
严格输出以下 JSON（不要包含 markdown 代码块标记）：
{{
  "top_10": [
    {{
      "url": "原始 URL",
      "title_zh": "中文标题",
      "summary_zh": "中文深度摘要（约100字）",
      "reason": "推荐理由"
    }}
  ],
  "translations": {{
    "URL": {{"title_zh": "中文标题", "desc_zh": "中文简介（约50字）"}}
  }},
  "insights": "1. **洞察标题**: 洞察内容\\n2. ...",
  "punchline": "一句话核心判词",
  "digest": "200字二阶推演摘要",
  "market": "* 要点1\\n* 要点2\\n* 要点3"
}}
"""


def score_and_rank(scan_data: dict, focus_data: dict) -> list:
    """Score items by strategic keyword relevance and return sorted list."""
    keywords = {
        kw["keyword"].lower(): kw["weight"]
        for kw in focus_data["strategic_keywords"]
    }

    scored = []
    for item in scan_data["items"]:
        text = (item.get("title", "") + " " + item.get("raw_desc", "")).lower()
        score = sum(weight for kw, weight in keywords.items() if kw in text)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def build_prompt(scored_items: list, focus_data: dict) -> str:
    """Build the refinement prompt from scored items."""
    # Format keywords for context
    kw_lines = ", ".join(
        f"{kw['keyword']}(w={kw['weight']})"
        for kw in sorted(focus_data["strategic_keywords"], key=lambda x: -x["weight"])[:15]
    )

    # Format top items (send top 30 for AI to select top 10 from)
    item_lines = []
    for i, (score, item) in enumerate(scored_items[:30]):
        desc = item.get("raw_desc", "").strip()[:200].replace("\n", " ")
        item_lines.append(
            f"{i+1}. [{item['source']}] {item['title']} | Score={score}\n"
            f"   URL: {item['url']}\n"
            f"   Desc: {desc}"
        )

    return REFINEMENT_PROMPT.format(
        count=len(scored_items[:30]),
        keywords=kw_lines,
        items="\n".join(item_lines),
    )


def refine():
    """Main refinement workflow: score, build prompt, and output for AI processing."""

    # 1. Load data
    if not SCAN_PATH.exists():
        print(f"❌ Error: No scan data found at {SCAN_PATH}")
        print("  Run `python scripts/fetch_news.py` first (Phase 1).")
        return

    scan_data = json.loads(SCAN_PATH.read_text(encoding="utf-8"))
    focus_data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))

    if not scan_data.get("items"):
        print("⚠️ Warning: Scan data has no items. Nothing to refine.")
        return

    # 2. Score and rank
    scored_items = score_and_rank(scan_data, focus_data)
    print(f"📊 Scored {len(scored_items)} items. Top score: {scored_items[0][0] if scored_items else 0}")

    # 3. Build prompt
    prompt = build_prompt(scored_items, focus_data)

    # 4. Output prompt for AI consumption
    prompt_path = HUB_DIR / "tmp" / "refinement_prompt.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    print(f"📝 Refinement prompt saved to: {prompt_path}")
    print(f"   Prompt length: {len(prompt)} chars")

    # 5. Prepare skeleton output (AI will fill this)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    skeleton = {
        "generated_at": datetime.now().isoformat(),
        "status": "AWAITING_AI_REFINEMENT",
        "top_10": [],
        "insights": "> 💡 [WAITING]",
        "punchline": "> 💡 [WAITING]",
        "digest": "> 💡 [WAITING]",
        "market": "* 数据未同步",
        "_prompt_path": str(prompt_path),
        "_scored_preview": [
            {"rank": i+1, "score": s, "title": item["title"][:80], "source": item["source"]}
            for i, (s, item) in enumerate(scored_items[:10])
        ],
    }
    OUTPUT_PATH.write_text(
        json.dumps(skeleton, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"📦 Skeleton output saved to: {OUTPUT_PATH}")
    print(f"\n🔄 Next: AI agent should read the prompt, generate refined JSON,")
    print(f"   and update {OUTPUT_PATH} with the results.")
    print(f"   Then run `python scripts/forge.py` (Phase 4) to assemble the briefing.")


if __name__ == "__main__":
    refine()
