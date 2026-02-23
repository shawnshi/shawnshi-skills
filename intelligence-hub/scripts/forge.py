"""
<!-- Intelligence Hub: The Forge V5.0 (Jinja2 Templating) -->
@Input: tmp/latest_scan.json, MEMORY/news/intelligence_current_refined.json, references/strategic_focus.json
@Output: MEMORY/news/intelligence_[DATE]_briefing.md
@Pos: Phase 4 (Briefing Assembly)
"""
import json
import os
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

def forge_briefing():
    # 1. Path Resolution
    scan_path = HUB_DIR / "tmp" / "latest_scan.json"
    refined_path = NEWS_DIR / "intelligence_current_refined.json"
    focus_path = HUB_DIR / "references" / "strategic_focus.json"
    
    # 2. Data Loading
    if not scan_path.exists(): 
        print(f"❌ Error: {scan_path} not found.")
        return
        
    with open(scan_path, 'r', encoding='utf-8') as f: scan_data = json.load(f)
    with open(focus_path, 'r', encoding='utf-8') as f: focus_data = json.load(f)
    
    ai_data = {}
    if refined_path.exists():
        with open(refined_path, 'r', encoding='utf-8') as f:
            ai_data = json.load(f)

    # 3. Scoring & Sorting for fallback
    keywords = {kw['keyword'].lower(): kw['weight'] for kw in focus_data['strategic_keywords']}
    scored_items = []
    for item in scan_data['items']:
        score = 0
        text = (item['title'] + " " + item.get('raw_desc', '')).lower()
        for kw, weight in keywords.items():
            if kw in text: score += weight
        scored_items.append((score, item))
    scored_items.sort(key=lambda x: x[0], reverse=True)
    
    # 4. Prepare data for Jinja2
    template_data = {
        "date": datetime.now().strftime('%Y-%m-%d'),
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "insights": ai_data.get("insights", "> 💡 [WAITING/ERROR]"),
        "punchline": ai_data.get("punchline", "> 💡 [WAITING/ERROR]"),
        "digest": ai_data.get("digest", "> 💡 [WAITING/ERROR]"),
        "market": ai_data.get("market", "* 数据未同步"),
        "adversarial_audit": ai_data.get("adversarial_audit", None),
        "save_path": str(NEWS_DIR / f"intelligence_{datetime.now().strftime('%Y%m%d')}_briefing.md")
    }

    # Data Table Rows
    data_table_rows = []
    for src, status in scan_data['metadata']['sources'].items():
        count = sum(1 for item in scan_data['items'] if item['source'] == src)
        data_table_rows.append({"source": src, "status": status, "count": count})
    template_data["data_table_rows"] = data_table_rows

    # Top 10
    top_10 = []
    ai_top_10 = ai_data.get("top_10", [])
    
    for i in range(10):
        if i >= len(scored_items): break
        score, item = scored_items[i]
        
        refined_entry = next((x for x in ai_top_10 if x['url'] == item['url']), None)
        title = refined_entry['title_zh'] if refined_entry else item['title']
        summary = refined_entry['summary_zh'] if refined_entry else "[AI 翻译中...] " + item.get('raw_desc', '')[:150]
        reason = refined_entry.get('reason', '') if refined_entry else ""
        
        top_10.append({
            "title": title,
            "url": item['url'],
            "source": item['source'],
            "score": score,
            "summary": summary,
            "reason": reason
        })
    template_data["top_10"] = top_10

    # Categorization & Grouped List
    categories = focus_data.get('categories', {})
    grouped_list = {cat: [] for cat in categories.keys()}
    grouped_list['其他综合资讯清单'] = []
    
    for score, item in scored_items[10:]:
        text = (item['title'] + " " + item.get('raw_desc', '')).lower()
        assigned = False
        for cat_name, cat_keywords in categories.items():
            if any(kw.lower() in text for kw in cat_keywords):
                grouped_list[cat_name].append(item)
                assigned = True
                break
        if not assigned: grouped_list['其他综合资讯清单'].append(item)

    ai_translations = ai_data.get("translations", {})
    
    formatted_grouped_list = {}
    for cat_name, items in grouped_list.items():
        if not items: continue
        
        formatted_items = []
        for item in items[:12]:
            trans = ai_translations.get(item['url'], {})
            if not isinstance(trans, dict): trans = {}
            title = trans.get('title_zh', item['title'])
            desc = trans.get('desc_zh', item.get('raw_desc', '').strip()[:100].replace('\n', ' '))
            
            formatted_items.append({
                "title": title,
                "url": item['url'],
                "desc": desc
            })
        formatted_grouped_list[cat_name] = formatted_items
        
    template_data["grouped_list"] = formatted_grouped_list

    # 5. Render with Jinja2
    env = FileSystemLoader(str(HUB_DIR / "references"))
    jinja_env = Environment(loader=env, trim_blocks=True, lstrip_blocks=True)
    template = jinja_env.get_template("briefing_template.md")
    
    final_md = template.render(**template_data)

    save_path = Path(template_data["save_path"])
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(final_md)
        
    # Save a JSON snapshot for the indexer
    snapshot_path = save_path.with_suffix('.json')
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(template_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Briefing forged with Jinja2 at: {save_path}")

if __name__ == "__main__":
    forge_briefing()
