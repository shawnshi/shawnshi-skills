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
        r"1\.\s*学术河流与演化叙事",
        r"2\.\s*目标论文：核心拆解",
        r"3\.\s*核心概念拆解",
        r"4\.\s*启发与博导审稿"
    ]
    for section in required_sections:
        if not re.search(section, content, re.IGNORECASE):
            errors.append(f"Missing required section matching pattern: {section}")

    # 2. 检查 Traceback 深度
    if not re.search(r"溯源地图\s*\(Traceback Map\)", content, re.IGNORECASE) and not re.search(r"\[年份:\s*奠基\]", content):
        errors.append("Traceback Map is missing or doesn't match the new '[年份: 奠基] Paper' anchor format.")

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
