"""
<!-- Intelligence Hub: The Forge V4.1 -->
<!-- Responsibility: Load JSON -> Score -> Render Markdown -->
"""
import json, os, sys
from datetime import datetime

# --- Loaders ---
def load_json(path):
    with open(path, 'r', encoding='utf-8') as f: return json.load(f)

def load_text(path):
    with open(path, 'r', encoding='utf-8') as f: return f.read()

# --- Logic ---
def forge_briefing():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. Load Assets
    data_path = os.path.join(base_dir, "tmp", "latest_scan.json")
    config_path = os.path.join(base_dir, "references", "strategic_focus.json")
    tpl_path = os.path.join(base_dir, "references", "briefing_template.md")
    
    if not os.path.exists(data_path):
        print(f"Error: Data file not found at {data_path}. Run fetch_news.py first.")
        return

    data = load_json(data_path)
    config = load_json(config_path)
    tpl = load_text(tpl_path)
    
    # 2. Score Items
    keywords = config.get("strategic_keywords", [])
    items = data.get("items", [])
    
    for item in items:
        score = 0
        text = (item.get('title', '') + item.get('raw_desc', '')).lower()
        for kw_obj in keywords:
            if kw_obj['keyword'] in text:
                score += kw_obj.get('weight', 10)
        item['score'] = score
        
    # 3. Sort
    sorted_items = sorted(items, key=lambda x: x['score'], reverse=True)
    top_10 = sorted_items[:10]
    
    # 4. Render Data Table
    tbl_lines = ["| 数据源 | 状态 | 抓取数量 |", "| :--- | :--- | :--- |"]
    for src, status in data['metadata']['sources'].items():
        count = len([i for i in items if i['source'].lower().replace(" ","").replace(".","") == src.lower().replace(" ","").replace(".","")])
        tbl_lines.append(f"| {src} | {status} | {count} |")
    
    # 5. Render Top 10
    top_lines = []
    for idx, item in enumerate(top_10, 1):
        # Clean abstract
        raw_d = item.get('raw_desc', '') or ""
        clean_d = " ".join(raw_d.split())
        abstract = (clean_d[:300] + "...") if len(clean_d) > 300 else (clean_d or "No abstract.")
        
        # Identify Keywords
        matched_kws = []
        for kw_obj in keywords:
            if kw_obj['keyword'] in (item['title'] + raw_d).lower():
                matched_kws.append(kw_obj['keyword'])
        kw_str = ", ".join(matched_kws) if matched_kws else "General"

        top_lines.append(f"### {idx}. {item['title']}")
        top_lines.append(f"- **URL**: {item['url']}")
        top_lines.append(f"- **中文摘要**: {abstract} [REFINEMENT: 必须补全至 100 字]")
        top_lines.append(f"- **推荐理由**: [WAITING]")
        top_lines.append(f"- **关键词**: {kw_str}")
        top_lines.append("")

    # 6. Render Full Grouped List
    grouped_lines = []
    assigned_urls = set()
    
    # Categorized Items
    for cat_name, cat_kws in config.get("categories", {}).items():
        cat_items = [i for i in items if i['url'] not in assigned_urls and any(k in (i['title']+i.get('raw_desc','')).lower() for k in cat_kws)]
        if cat_items:
            grouped_lines.append(f"### {cat_name}")
            for item in cat_items:
                raw_d = item.get('raw_desc', '') or ""
                clean_d = " ".join(raw_d.split())
                abstract = (clean_d[:300] + "...") if len(clean_d) > 300 else (clean_d or "No abstract.")
                
                matched = [k for k in cat_kws if k in (item['title']+raw_d).lower()]
                reason = f"命中关键词: {', '.join(matched)}" if matched else cat_name
                
                grouped_lines.append(f"- **{item['title']}** ({item['url']})")
                grouped_lines.append(f"  - *中文摘要*: {abstract} [补全至 100 字]")
                grouped_lines.append(f"  - *推荐理由*: [WAITING] {reason}。")
                assigned_urls.add(item['url'])
            grouped_lines.append("")
            
    # Remaining Items
    rem_items = [i for i in items if i['url'] not in assigned_urls]
    if rem_items:
        grouped_lines.append("### 其他综合资讯清单")
        for item in rem_items:
            raw_d = item.get('raw_desc', '') or ""
            clean_d = " ".join(raw_d.split())
            abstract = (clean_d[:120] + "...") if len(clean_d) > 120 else clean_d
            grouped_lines.append(f"- **{item['title']}** ({item['url']})")
            grouped_lines.append(f"  - *中文摘要*: {abstract} [补全至 100 字]")
            grouped_lines.append(f"  - *推荐理由*: [WAITING] 通用扫描。 ")

    # 7. Final Injection
    today_str = datetime.now().strftime('%Y-%m-%d')
    file_name = f"intelligence_{datetime.now().strftime('%Y%m%d')}_briefing.md"
    save_path = os.path.join(base_dir, "..", "MEMORY", "news", file_name)
    
    final_md = tpl.replace("{{DATE}}", today_str)
    final_md = final_md.replace("{{DATA_TABLE}}", "\n".join(tbl_lines))
    final_md = final_md.replace("{{TOP_10_LIST}}", "\n".join(top_lines))
    final_md = final_md.replace("{{GROUPED_FULL_LIST}}", "\n".join(grouped_lines))
    final_md = final_md.replace("{{SAVE_PATH}}", save_path)
    
    # Ensure dir exists
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(final_md)
        
    print(f"Briefing forged at: {save_path}")

if __name__ == "__main__":
    forge_briefing()
