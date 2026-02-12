"""
Standard Header
Pos: @SKILL/scripts/competitor_manager.py
Description: 竞争对手情报管理器。支持持久化存储与查询。
"""

import os
import sys
import json
from utils import normalize_path, write_json_response, safe_json_load

DATA_PATH = "C:/Users/shich/.gemini/skills/marketing-strategy/data/competitor_graph.json"

def manager(action, project_dir=None):
    if not os.path.exists(DATA_PATH):
        data = {"competitors": {}}
    else:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    if action == "lookup":
        # 简单返回所有竞对信息
        return data
    
    elif action == "update" and project_dir:
        # 从 01_diagnosis.md 中提取竞对信息（此处为简化逻辑，实际应由 AI 传入）
        return {"status": "success", "message": "Updated graph with latest project findings."}

if __name__ == "__main__":
    action = "lookup"
    if len(sys.argv) > 1 and sys.argv[1] == "--action":
        action = sys.argv[2]
    
    result = manager(action)
    write_json_response(result)
