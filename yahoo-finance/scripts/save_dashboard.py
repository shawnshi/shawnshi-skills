import os
import sys
import json
import argparse
from datetime import datetime

def save_dashboard():
    parser = argparse.ArgumentParser(description="Save Stock Analysis Dashboard")
    parser.add_argument("--stock", required=True, help="Stock name (e.g. 腾讯)")
    parser.add_argument("--content", help="JSON content string. If not provided, reads from stdin.")
    
    args = parser.parse_args()
    
    content = args.content
    if not content:
        content = sys.stdin.read()
        
    try:
        # validate json
        parsed = json.loads(content)
        formatted_content = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON content: {e}")
        sys.exit(1)
        
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{args.stock}_{date_str}.md"
    
    base_dir = os.path.join(os.path.expanduser("~"), ".gemini", "MEMORY", "stocks")
    
    os.makedirs(base_dir, exist_ok=True)
    
    filepath = os.path.join(base_dir, filename)
    
    date_iso = datetime.now().strftime("%Y-%m-%d")
    md_content = f"""---
title: {args.stock} 深度研究报告
date: {date_iso}
status: archived
author: stock_analyzer
---

# 决策仪表盘: {args.stock}

> 本报告由 `stock_analyzer` 基于双引擎（Yahoo Finance 量化数据与网络检索）自动生成。

```json
{formatted_content}
```
"""
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"Successfully saved dashboard to {filepath}")

if __name__ == "__main__":
    save_dashboard()
