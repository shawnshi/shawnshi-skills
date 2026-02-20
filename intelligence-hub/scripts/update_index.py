"""
<!-- Intelligence Hub Indexer V4.1 -->
"""
import os
import re
import json
from datetime import datetime

INDEX_MD_PATH = "C:\\Users\\shich\\.gemini\\MEMORY\\news\\_INDEX.md"
INDEX_JSON_PATH = "C:\\Users\\shich\\.gemini\\MEMORY\\news\\_INDEX.json"
NEWS_DIR = "C:\\Users\\shich\\.gemini\\MEMORY\\news\\"

def update():
    files = [f for f in os.listdir(NEWS_DIR) if f.startswith("intelligence_") and f.endswith(".md") and f != "_INDEX.md"]
    files.sort(reverse=True)
    
    md_lines = ["# 🛡️ Intelligence Hub: 情报总目", "", "此文件由系统自动维护，记录所有已归档的战略简报。", ""]
    md_lines.append("| 日期 | 文件名 | 状态 | 备注 |")
    md_lines.append("| :--- | :--- | :--- | :--- |")
    
    json_data = {"last_updated": datetime.now().isoformat(), "files": []}
    
    for f in files:
        full_path = os.path.join(NEWS_DIR, f)
        match = re.search(r'intelligence_(\d{8})_', f)
        date_str = match.group(1) if match else "Unknown"
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        
        # Simple extraction of Top 3 topics from file (if possible)
        topics = []
        try:
            with open(full_path, "r", encoding="utf-8") as f_content:
                content = f_content.read()
                # Find the '今日核心洞察' section
                insight_match = re.search(r'## 📝 今日核心洞察\n([\s\S]*?)\n##', content)
                if insight_match:
                    topics = re.findall(r'\d\.\s\*\*(.*?)\*\*', insight_match.group(1))
        except: pass

        md_lines.append(f"| {fmt_date} | [{f}](./{f}) | ✅ 已归档 | {', '.join(topics[:3]) if topics else 'V4.2 自动生成'} |")
        
        json_data["files"].append({
            "date": fmt_date,
            "filename": f,
            "topics": topics[:5],
            "path": full_path
        })
    
    md_lines.append(f"\n*Index Rebuilt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    # Save MD
    with open(INDEX_MD_PATH, "w", encoding="utf-8") as f_idx:
        f_idx.write("\n".join(md_lines))
    
    # Save JSON
    with open(INDEX_JSON_PATH, "w", encoding="utf-8") as f_json:
        json.dump(json_data, f_json, ensure_ascii=False, indent=2)
        
    print(f"Index updated: {INDEX_MD_PATH}")
    print(f"JSON search index updated: {INDEX_JSON_PATH}")

if __name__ == "__main__":
    update()

if __name__ == "__main__":
    update()

