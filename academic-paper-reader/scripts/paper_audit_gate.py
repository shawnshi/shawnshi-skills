import argparse
import os
import re
import sys
from pathlib import Path


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"), file=sys.stderr)


def validate_paper_draft(content: str) -> list[str]:
    errors = []

    # 1. 检查核心结构标题
    required_sections = [
        r"\*\s*1\.\s*核心隐喻",
        r"\*\s*2\.\s*演化地图",
        r"\*\s*3\.\s*核心解剖",
        r"\*\s*4\.\s*导师点评与启发"
    ]
    for section in required_sections:
        if not re.search(section, content, re.IGNORECASE):
            errors.append(f"Missing required section matching pattern: {section}")

    # 2. 检查 Traceback 深度 (至少有 G0 -> G1 这种两级结构)
    if not re.search(r"G\d+\s*->\s*G\d+", content) and not re.search(r"Generation\s*0", content, re.IGNORECASE):
        errors.append("Traceback Map is too shallow or missing explicit generation markers (e.g., G0 -> G1).")

    # 3. 防八股文扫描 (Aesthetic Defense)
    banned_phrases = [
        "值得注意的是",
        "近年来随着",
        "本文提出了一种框架",
        "填补了空白",
        "具有重要的理论意义和实际应用价值"
    ]
    for phrase in banned_phrases:
        if phrase in content:
            errors.append(f"Aesthetic Violation: Contains banned academic phrase '{phrase}'.")

    # 4. 检查 Denote 头部宏
    if not re.search(r"#\+title:", content):
        errors.append("Missing '#+title:' in frontmatter.")
    if not re.search(r"#\+identifier:\s*\d{8}T\d{6}", content):
        errors.append("Missing or invalid '#+identifier:' (requires YYYYMMDDTHHMMSS format).")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Audit Academic Paper Reader Markdown drafts.")
    parser.add_argument("file_path", help="Path to the markdown draft to audit.")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    if not file_path.exists():
        safe_print(f"Error: File not found at {file_path}")
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")
    
    errors = validate_paper_draft(content)
    
    if errors:
        safe_print("Paper Audit Failed! The following rules were violated:")
        for error in errors:
            safe_print(f"- {error}")
        sys.exit(1)
        
    print("Audit Passed. The draft meets the structural and aesthetic requirements.")
    sys.exit(0)


if __name__ == "__main__":
    main()
