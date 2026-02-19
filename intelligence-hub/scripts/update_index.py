"""
<!-- Intelligence Hub Indexer V4.1 -->
"""
import os
import re
from datetime import datetime

INDEX_PATH = "C:\\Users\\shich\\.gemini\\MEMORY\\news\\_INDEX.md"
NEWS_DIR = "C:\\Users\\shich\\.gemini\\MEMORY\\news\\"

def update():
    files = [f for f in os.listdir(NEWS_DIR) if f.startswith("intelligence_") and f.endswith(".md") and f != "_INDEX.md"]
    files.sort(reverse=True)
    
    lines = ["# 🛡️ Intelligence Hub: 情报总目", "", "此文件由系统自动维护，记录所有已归档的战略简报。", ""]
    lines.append("| 日期 | 文件名 | 状态 | 备注 |")
    lines.append("| :--- | :--- | :--- | :--- |")
    
    for f in files:
        match = re.search(r'intelligence_(\d{8})_', f)
        date_str = match.group(1) if match else "Unknown"
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        lines.append(f"| {fmt_date} | [{f}](./{f}) | ✅ 已归档 | V4.1 自动生成 |")
    
    lines.append(f"\n*Index Rebuilt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    with open(INDEX_PATH, "w", encoding="utf-8") as f_idx:
        f_idx.write("\n".join(lines))
    print(f"Index updated: {INDEX_PATH}")

if __name__ == "__main__":
    update()

