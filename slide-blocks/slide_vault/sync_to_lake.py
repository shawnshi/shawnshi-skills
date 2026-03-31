# -*- coding: utf-8 -*-
"""
sync_to_lake.py - 将 SlideBlocks 本地资产推送到 Mentat 逻辑湖 (Vector Lake)
执行命令: python slide_vault/sync_to_lake.py
"""
import os
import sys
import sqlite3
import json
import subprocess
from pathlib import Path

# 导入配置
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from slide_vault.config import get_db_path

def sync_to_mentat_lake():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 获取已经打好标签的幻灯片
    rows = conn.execute("""
        SELECT s.id, s.file_path, s.slide_index, s.title, t.summary, t.keywords, t.layout_type
        FROM slides s
        JOIN tags t ON s.id = t.slide_id
    """).fetchall()
    conn.close()

    if not rows:
        print("[VectorLake Sync] 没有可同步的资产。")
        return

    print(f"[VectorLake Sync] 准备将 {len(rows)} 条幻灯片资产注入全局逻辑湖...")

    # 由于 vector-lake/cli.py 目前主要处理文件目录的 sync，
    # 我们可以通过在 MEMORY 下创建一个中间文件，让其自动纳入扫描，
    # 或直接将结构化数据写入一个 .md 文件，供 vector-lake 摄取。

    mentat_memory_dir = Path(r"C:\Users\shich\.gemini\MEMORY\slide_blocks_exports")
    mentat_memory_dir.mkdir(parents=True, exist_ok=True)

    export_file = mentat_memory_dir / "slide_assets_catalog.md"

    with open(export_file, "w", encoding="utf-8") as f:
        f.write("# SlideBlocks 视觉与逻辑资产库清单\n\n")
        f.write("> 自动同步自 slide_vault.db。用于跨维度的逻辑与视觉资产匹配。\n\n")

        for row in rows:
            title = row["title"] or "无标题"
            keywords = row["keywords"] or "[]"
            f.write(f"## Slide ID: {row['id']} - {title}\n")
            f.write(f"- **物理路径**: `{row['file_path']}` (第 {row['slide_index']} 页)\n")
            f.write(f"- **版式结构**: {row['layout_type']}\n")
            f.write(f"- **语义标签**: {keywords}\n")
            f.write(f"- **核心摘要**: {row['summary']}\n\n")

    print(f"[VectorLake Sync] 资产目录已导出至: {export_file}")
    print("[VectorLake Sync] 正在呼叫 Mentat Vector Lake 进行全局增量同步...")

    # 调用全局 Vector Lake 的 sync 命令
    lake_cli = r"C:\Users\shich\.gemini\extensions\vector-lake\cli.py"
    if Path(lake_cli).exists():
        try:
            subprocess.run(["python", lake_cli, "sync"], check=True)
            print("[VectorLake Sync] 全局逻辑湖合并完成！")
        except Exception as e:
            print(f"[!] Vector Lake 同步失败: {e}")
    else:
        print("[!] 未找到 Vector Lake CLI 接口，资产停留在中间态。")

if __name__ == "__main__":
    sync_to_mentat_lake()
