"""
<!-- Intelligence Hub: The Forge V5.2 (Localization & Detail Enhanced) -->
@Input: tmp/latest_scan.json, tmp/ai_refined.json, references/strategic_focus.json
@Output: root/MEMORY/news/intelligence_[DATE]_briefing.md
@Pos: Phase 4 (Briefing Assembly)
"""
import json
import os
from pathlib import Path
from datetime import datetime
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

def forge_briefing():
    # 1. Path Resolution
    scan_path = HUB_DIR / "tmp" / "latest_scan.json"
    refined_path = NEWS_DIR / "intelligence_current_refined.json"
    focus_path = HUB_DIR / "references" / "strategic_focus.json"
    template_path = HUB_DIR / "references" / "briefing_template.md"
    
    # 2. Data Loading
    if not scan_path.exists(): return
    with open(scan_path, 'r', encoding='utf-8') as f: scan_data = json.load(f)
    with open(focus_path, 'r', encoding='utf-8') as f: focus_data = json.load(f)
    ai_data = {}
    if refined_path.exists():
        with open(refined_path, 'r', encoding='utf-8') as f:
            ai_data = json.load(f)

    with open(template_path, 'r', encoding='utf-8') as f: tpl = f.read()

    # 3. Scoring & Sorting
    keywords = {kw['keyword'].lower(): kw['weight'] for kw in focus_data['strategic_keywords']}
    scored_items = []
    for item in scan_data['items']:
        score = 0
        text = (item['title'] + " " + item.get('raw_desc', '')).lower()
        for kw, weight in keywords.items():
            if kw in text: score += weight
        scored_items.append((score, item))
    scored_items.sort(key=lambda x: x[0], reverse=True)
    
    # 4. Rendering Top 10 (Prioritizing AI Refined Summaries)
    top_10_md = []
    ai_top_10 = ai_data.get("top_10", [])
    
    for i in range(10):
        if i >= len(scored_items): break
        score, item = scored_items[i]
        
        # Check if we have an AI-refined version of this entry
        refined_entry = next((x for x in ai_top_10 if x['url'] == item['url']), None)
        
        title = refined_entry['title_zh'] if refined_entry else item['title']
        summary = refined_entry['summary_zh'] if refined_entry else "[AI 翻译中...] " + item.get('raw_desc', '')[:150]
        reason = refined_entry.get('reason', '') if refined_entry else ""

        top_10_md.append(f"### {i+1}. [{title}]({item['url']})")
        top_10_md.append(f"- **来源**: {item['source']} | **战略权重**: {score}")
        top_10_md.append(f"- **中文摘要**: {summary}...")
        if reason: top_10_md.append(f"- **推荐理由**: {reason}")
        top_10_md.append("")
    
    # 5. Categorization & Grouped List
    categories = focus_data.get('categories', {})
    grouped = {cat: [] for cat in categories.keys()}
    grouped['其他综合资讯清单'] = []
    
    for score, item in scored_items[10:]:
        text = (item['title'] + " " + item.get('raw_desc', '')).lower()
        assigned = False
        for cat_name, cat_keywords in categories.items():
            if any(kw.lower() in text for kw in cat_keywords):
                grouped[cat_name].append(item)
                assigned = True
                break
        if not assigned: grouped['其他综合资讯清单'].append(item)

    full_list_md = []
    ai_translations = ai_data.get("translations", {})
    
    for cat_name, items in grouped.items():
        if not items: continue
        full_list_md.append(f"### {cat_name}")
        for item in items[:12]:
            # Use AI translation if available, otherwise fallback to raw desc
            trans = ai_translations.get(item['url'], {})
            title = trans.get('title_zh', item['title'])
            desc = trans.get('desc_zh', item.get('raw_desc', '').strip()[:100].replace('\n', ' '))
            
            full_list_md.append(f"- **[{title}]({item['url']})**")
            if desc: full_list_md.append(f"  > *简介*: {desc}...")
        full_list_md.append("")

    # 6. Final Assembly
    placeholders = {
        "{{DATE}}": datetime.now().strftime('%Y-%m-%d'),
        "{{TIMESTAMP}}": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "{{INSIGHTS}}": ai_data.get("insights", "> 💡 [WAITING]"),
        "{{PUNCHLINE}}": ai_data.get("punchline", "> 💡 [WAITING]"),
        "{{DIGEST}}": ai_data.get("digest", "> 💡 [WAITING]"),
        "{{MARKET}}": ai_data.get("market", "* 数据未同步"),
        "{{TOP_10_LIST}}": "\n".join(top_10_md),
        "{{GROUPED_FULL_LIST}}": "\n".join(full_list_md),
        "{{SAVE_PATH}}": str(PROJECT_ROOT / "MEMORY" / "news" / f"intelligence_{datetime.now().strftime('%Y%m%d')}_briefing.md")
    }

    final_md = tpl
    for key, val in placeholders.items():
        final_md = final_md.replace(key, val)

    # Table Rendering
    table_rows = ["| 数据源 | 状态 | 抓取数量 |", "| :--- | :--- | :--- |"]
    for src, status in scan_data['metadata']['sources'].items():
        count = sum(1 for item in scan_data['items'] if item['source'] == src)
        table_rows.append(f"| {src} | {status} | {count} |")
    final_md = final_md.replace("{{DATA_TABLE}}", "\n".join(table_rows))

    save_path = Path(placeholders["{{SAVE_PATH}}"])
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(final_md)
    print(f"Briefing forged with localization at: {save_path}")

if __name__ == "__main__":
    forge_briefing()
