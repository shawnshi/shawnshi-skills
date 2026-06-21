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
        "降本增效", # Often overused without metrics
        "全栈式",
        "赋能临床",
        "打破信息孤岛",
        "顶层设计",
        "智慧大脑"
    ]
    for phrase in banned_phrases:
        if phrase in content:
            errors.append(f"Aesthetic Violation: Contains banned marketing buzzword '{phrase}'. Use concrete metrics instead.")

    # 2. Global: Metadata Placeholder Audit
    placeholders = [r"\[URL\]", r"\[Link\]", r"\[DOI\]", r"https?://example\.com"]
    for p in placeholders:
        if re.search(p, content, re.IGNORECASE):
            errors.append(f"Metadata Violation: Unresolved placeholder {p} found. Real data required.")

    # 2.5 Global: Language Enforcement (Must contain Chinese characters)
    if not re.search(r"[\u4e00-\u9fff]", content):
        errors.append("Language Violation: Content appears to be entirely non-Chinese. You MUST output in Chinese (zh-CN).")

    # 2.6 Global: Anti-AI Fluff (BLUF Contract)
    ai_fluffs = [
        r"为您整理完毕",
        r"希望本期的",
        r"欢迎随时",
        r"希望这.*对您有.*帮助",
        r"如果您.*进一步",
        r"很高兴为您"
    ]
    for fluff in ai_fluffs:
        if re.search(fluff, content, re.IGNORECASE):
            errors.append(f"BLUF Violation: Contains AI customer service fluff matching '{fluff}'. Remove all pleasantries.")

    # 3. Mode Specific Rules
    if mode == "radar":
        # Check for system dynamics and structural separation requirements
        required_radar = [r"客观事实", r"战略与行业背景解读", r"Causal Implications", r"推论"]
        for r_sec in required_radar:
            if not re.search(r_sec, content, re.IGNORECASE):
                errors.append(f"Radar Mode Violation: Missing required structural section/keyword '{r_sec}'. You must perform System Dynamics Analysis.")
        
        # Enforce that Fact lines must contain digits (e.g., money, version, date)
        fact_lines = re.findall(r"客观事实.*?(Fact.*?)[:：](.*)", content, re.IGNORECASE)
        for idx, (_, fact_content) in enumerate(fact_lines, 1):
            if not re.search(r"\d+", fact_content):
                errors.append(f"Radar Fact Violation: Fact line #{idx} lacks concrete metrics (no numbers found): '{fact_content[:30]}...'")
                
    elif mode == "scout":
        required_scout = [r"MECE 归类", r"卫宁战略映射", r"核心变量与评估指标", r"学术发现"]
        for s_sec in required_scout:
            if not re.search(s_sec, content, re.IGNORECASE):
                errors.append(f"Scout Mode Violation: Missing required strategic alignment section/keyword '{s_sec}'.")

    elif mode == "brief":
        required_brief = [r"非共识", r"Contrarian", r"跨界", r"Serendipity"]
        # Split into two mandatory logic gates: Must have a contrarian view AND must have a serendipity view
        has_contrarian = any(re.search(word, content, re.IGNORECASE) for word in [r"非共识", r"Contrarian"])
        has_serendipity = any(re.search(word, content, re.IGNORECASE) for word in [r"跨界", r"Serendipity"])
        
        if not has_contrarian:
            errors.append("Brief Mode Violation: Missing Contrarian (非共识) view. You must challenge the consensus.")
        if not has_serendipity:
            errors.append("Brief Mode Violation: Missing Cross-domain / Serendipity (跨界) insight. You must include insights from outside healthcare.")
            
        has_policy = any(re.search(word, content, re.IGNORECASE) for word in [r"政策", r"合规", r"Policy", r"Compliance"])
        if not has_policy:
            errors.append("Brief Mode Violation: Missing Policy (公卫与合规政策) pipeline. You must include all 4 pipelines.")

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
