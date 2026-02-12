"""
Standard Header
Pos: @SKILL/scripts/utils.py
Description: 核心工具库 V2 - 引入字段校验与动态 LTV 支持。
"""

import os
import json
import sys

def normalize_path(path):
    base_skill_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if path.startswith("@SKILL"):
        path = path.replace("@SKILL", base_skill_path)
    return os.path.abspath(path.replace('\\', '/'))

def validate_fields(data, required_fields):
    """字段存在性与类型基础校验"""
    missing = [f for f in required_fields if f not in data]
    if missing:
        return {"error": f"Missing required fields: {', '.join(missing)}"}
    return None

def safe_json_load(json_str):
    try:
        return json.loads(json_str)
    except Exception as e:
        return {"error": f"JSON Parse Error: {str(e)}"}

def write_json_response(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

def log_event(message, level="INFO"):
    sys.stderr.write(f"[{level}] {message}\n")
