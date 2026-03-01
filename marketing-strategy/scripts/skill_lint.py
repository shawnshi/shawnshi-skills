"""
Standard Header
Pos: @SKILL/scripts/skill_lint.py
Description: 技能合规性巡检工具 (GEB-Flow Linter)。
"""

import os
import sys

def lint_skill(root_path):
    root_path = os.path.abspath(root_path)
    issues = []
    
    # 1. 检查根元数据
    if not os.path.exists(os.path.join(root_path, "_DIR_META.md")):
        issues.append("Missing root _DIR_META.md")
        
    # 2. 检查脚本 Header 与路径脱敏
    scripts_dir = os.path.join(root_path, "scripts")
    if os.path.exists(scripts_dir):
        for f in os.listdir(scripts_dir):
            if f.endswith(".py"):
                path = os.path.join(scripts_dir, f)
                with open(path, "r", encoding="utf-8") as file:
                    content = file.read()
                    if '"""\nStandard Header' not in content:
                        issues.append(f"Script {f} missing Standard Header")
                    if ("Pos: C:\\" in content or "Pos: /" in content) and "Pos: @SKILL" not in content:
                        issues.append(f"Script {f} contains absolute path in Pos (use @SKILL)")

    return {
        "skill": os.path.basename(root_path),
        "issues": issues,
        "status": "PASS" if not issues else "FAIL"
    }

if __name__ == "__main__":
    skill_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    result = lint_skill(skill_root)
    import json
    print(json.dumps(result, indent=2))

