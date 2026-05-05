import argparse
import os
import re
import sys
from pathlib import Path


def safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"), file=sys.stderr)


def validate_hit_draft(content: str, mode: str) -> list[str]:
    errors = []

    # 1. Global: Marketing Buzzwords Defense
    banned_phrases = [
        "赋能",
        "数字化转型",
        "协同发展",
        "全面升级",
        "重大突破",
        "生态矩阵",
        "降本增效" # Often overused without metrics
    ]
    for phrase in banned_phrases:
        if phrase in content:
            errors.append(f"Aesthetic Violation: Contains banned marketing buzzword '{phrase}'. Use concrete metrics instead.")

    # 2. Global: Metadata Placeholder Audit
    placeholders = [r"\[URL\]", r"\[Link\]", r"\[DOI\]", r"https?://example\.com"]
    for p in placeholders:
        if re.search(p, content, re.IGNORECASE):
            errors.append(f"Metadata Violation: Unresolved placeholder {p} found. Real data required.")

    # 3. Mode Specific Rules
    if mode == "radar":
        required_radar = [r"紧急预警", r"织者洞察", r"下钻建议"]
        for r_sec in required_radar:
            if not re.search(r_sec, content):
                errors.append(f"Radar Mode Violation: Missing required section/keyword '{r_sec}'.")
                
    elif mode == "scout":
        required_scout = [r"真实世界证据", r"研发预研任务", r"销售防御话术"]
        for s_sec in required_scout:
            if not re.search(s_sec, content):
                errors.append(f"Scout Mode Violation: Missing required section/keyword '{s_sec}'.")

    elif mode == "brief":
        required_brief = [r"非共识", r"Contrarian", r"跨界"]
        found_brief = any(re.search(b_sec, content, re.IGNORECASE) for b_sec in required_brief)
        if not found_brief:
            errors.append("Brief Mode Violation: Missing Contrarian view or Cross-domain (Serendipity) insight.")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Audit HIT (Healthcare IT) Markdown drafts.")
    parser.add_argument("file_path", help="Path to the markdown draft to audit.")
    parser.add_argument("--mode", choices=["radar", "scout", "brief"], required=True, help="The specific HIT skill mode.")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    if not file_path.exists():
        safe_print(f"Error: File not found at {file_path}")
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")
    
    errors = validate_hit_draft(content, args.mode)
    
    if errors:
        safe_print(f"[{args.mode.upper()}] HIT Audit Failed! The following rules were violated:")
        for error in errors:
            safe_print(f"- {error}")
        sys.exit(1)
        
    print(f"[{args.mode.upper()}] Audit Passed. The draft meets the structural and aesthetic requirements.")
    sys.exit(0)


if __name__ == "__main__":
    main()
