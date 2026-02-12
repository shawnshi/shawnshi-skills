"""
Standard Header
Pos: @SKILL/scripts/consolidate_report.py
Description: 智能报告合成引擎 V3.1 (MBB Edition)。修正了 f-string 语法错误。
"""

import os
import sys
import re
import json
from utils import normalize_path, write_json_response, log_event, safe_json_load

def check_visuals(content):
    charts = re.findall(r'```mermaid', content)
    if not charts:
        return "Warning: NO VISUALS FOUND. MBB standard requires Mermaid charts."
    return f"Visual check passed: {len(charts)} charts found."

def consolidate(project_dir, output_filename="final_report.md"):
    project_dir = normalize_path(project_dir)
    final_path = os.path.join(project_dir, output_filename)
    
    stages = [
        ("01_diagnosis.md", "## 1. Contextual Diagnosis (With Expert Panel)"),
        ("02_strategy_branches.md", "## 2. Strategic Decision Matrix"),
        ("03_tactics.md", "## 3. Tactics & Pre-Mortem Analysis"),
        ("04_metrics.md", "## 4. Financials & ROI")
    ]
    
    all_content = []
    try:
        for filename, title in stages:
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    all_content.append(f"\n---\n{title}\n\n{f.read()}")

        full_body = "\n".join(all_content)
        visual_status = check_visuals(full_body)
        
        mode_text = 'DRAFT' if 'draft' in output_filename.lower() else 'FINAL'
        header = f"# Strategic Master Plan ({mode_text})\n\n> **System Audit**: {visual_status}\n\n## Executive Summary (SCQA Framework)\n*   **Situation**: [To be refined]\n*   **Complication**: [To be refined]\n*   **Question**: [To be refined]\n*   **Answer**: [To be refined]\n\n---\n"
        
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(full_body)
            
        return {"output_path": final_path, "visual_status": visual_status}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    input_data = {}
    if len(sys.argv) > 1:
        for i in range(len(sys.argv)):
            if sys.argv[i] == "--output" and i + 1 < len(sys.argv): input_data["output_filename"] = sys.argv[i+1]
            if sys.argv[i] == "--dir" and i + 1 < len(sys.argv): input_data["project_dir"] = sys.argv[i+1]
    
    project_dir = input_data.get("project_dir", ".")
    output_filename = input_data.get("output_filename", "final_report.md")
    result = consolidate(project_dir, output_filename)
    write_json_response(result)
