"""
Standard Header
Pos: @SKILL/scripts/project_init.py
Description: 初始化项目文件夹与模板。
"""

import os
import sys
import json
from utils import normalize_path, write_json_response, safe_json_load

def init_project(project_name, base_path):
    safe_name = "".join([c for c in project_name if c.isalnum() or c in (" ", "-", "_")]).strip().replace(" ", "_")
    base_path = normalize_path(base_path)
    project_dir = os.path.join(base_path, "projects", safe_name)
    
    stages = [
        "01_diagnosis.md",
        "02_strategy.md",
        "03_tactics.md",
        "04_metrics.md",
        "05_roi_analysis.json"
    ]
    
    try:
        if not os.path.exists(project_dir):
            os.makedirs(project_dir)
            
        created_files = []
        for stage in stages:
            file_path = os.path.join(project_dir, stage)
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"# Project: {project_name}\n# Stage: {stage}\n\n")
                created_files.append(stage)
                
        return {
            "project_dir": project_dir,
            "status": "initialized",
            "files": created_files
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    if not sys.stdin.isatty():
        input_content = sys.stdin.read()
    elif len(sys.argv) > 1:
        input_content = sys.argv[1]
    else:
        input_content = "{}"
        
    input_data = safe_json_load(input_content)
    if "error" in input_data:
        write_json_response(input_data)
    else:
        result = init_project(
            input_data.get("project_name", "unnamed_project"),
            input_data.get("base_path", "@SKILL")
        )
        write_json_response(result)
