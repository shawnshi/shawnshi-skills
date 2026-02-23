"""
<!-- Intelligence Hub Indexer V5.0 -->
@Input: MEMORY/news/ directory
@Output: MEMORY/news/_INDEX.md, MEMORY/news/_INDEX.json
@Pos: Phase 5 (Archiving & Indexing)
@Maintenance Protocol: Path changes must sync SKILL.md.
"""
import os
import re
import json
from datetime import datetime
from pathlib import Path
from utils import PROJECT_ROOT, HUB_DIR, NEWS_DIR

# Resolve paths dynamically from script location
INDEX_MD_PATH = NEWS_DIR / "_INDEX.md"
INDEX_JSON_PATH = NEWS_DIR / "_INDEX.json"

def update():
    if not NEWS_DIR.exists():
        print(f"Warning: News directory not found at {NEWS_DIR}, creating it.")
        NEWS_DIR.mkdir(parents=True, exist_ok=True)
        return

    files = [f for f in os.listdir(NEWS_DIR) if f.startswith("intelligence_") and f.endswith(".md") and f != "_INDEX.md"]
    files.sort(reverse=True)
    
    md_lines = ["# 🛡️ Intelligence Hub: 情报总目", "", "此文件由系统自动维护，记录所有已归档的战略简报。", ""]
    md_lines.append("| 日期 | 文件名 | 状态 | 核心洞察提取 |")
    md_lines.append("| :--- | :--- | :--- | :--- |")
    
    json_data = {"last_updated": datetime.now().isoformat(), "files": []}
    
    for f in files:
        full_path = NEWS_DIR / f
        match = re.search(r'intelligence_(\d{8})_', f)
        date_str = match.group(1) if match else "Unknown"
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        
        topics = []
        
        # Look for the JSON snapshot first
        snapshot_path = full_path.with_suffix('.json')
        if snapshot_path.exists():
            try:
                snap_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                insights_text = snap_data.get("insights", "")
                if insights_text:
                    # Try to extract leading sentences or titles
                    matches = re.findall(r'\d+\.\s+\*\*(.*?)\*\*', insights_text)
                    if not matches:
                        # Fallback try to just get numbered lines
                        matches = re.findall(r'\d+\.\s+(.*)', insights_text)
                    topics = matches
            except Exception:
                pass
        
        # Fallback to regex on Markdown for legacy files
        if not topics:
            try:
                content = full_path.read_text(encoding="utf-8")
                insight_match = re.search(r'## 📝 今日核心洞察\n([\s\S]*?)\n##', content)
                if insight_match:
                    topics = re.findall(r'\d\.\s\*\*(.*?)\*\*', insight_match.group(1))
            except Exception:
                pass

        topics_preview = ", ".join(topics[:3]) if topics else 'V5.0 自动生成'
        if len(topics_preview) > 50:
            topics_preview = topics_preview[:47] + "..."

        md_lines.append(f"| {fmt_date} | [{f}](./{f}) | ✅ 已归档 | {topics_preview} |")
        
        json_data["files"].append({
            "date": fmt_date,
            "filename": f,
            "topics": topics[:5],
            "path": str(full_path)
        })
    
    md_lines.append(f"\n*Index Rebuilt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    # Save MD
    INDEX_MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
    
    # Save JSON
    with open(INDEX_JSON_PATH, "w", encoding="utf-8") as f_json:
        json.dump(json_data, f_json, ensure_ascii=False, indent=2)
        
    print(f"✅ Index updated: {INDEX_MD_PATH}")
    print(f"✅ JSON search index updated: {INDEX_JSON_PATH}")

if __name__ == "__main__":
    update()
