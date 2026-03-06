"""
<!-- Standard Header -->
@Input: outline.md (Narrative Blueprint)
@Output: Validation Result
@Phase: Phase 4 - Pre-flight Narrative Audit (叙事逻辑审计)
@Maintenance Protocol: Rules must sync SKILL.md V9.0.
"""
import os
import re
import sys
import argparse

def audit_narrative_blueprint(content):
    errors = []
    
    # 1. STYLE_INSTRUCTIONS Check
    if '<STYLE_INSTRUCTIONS>' not in content or '</STYLE_INSTRUCTIONS>' not in content:
        errors.append("Global: Missing mandatory <STYLE_INSTRUCTIONS> block.")

    # 2. Slide Splitting
    slides = re.split(r'Page \d+:', content)
    if slides and not slides[0].strip():
        slides = slides[1:]
        
    for i, slide in enumerate(slides, 1):
        # Mandatory Sections Check
        sections = [
            ('// NARRATIVE GOAL', '叙事目标'),
            ('// KEY CONTENT', '关键内容'),
            ('// VISUAL', '视觉画面'),
            ('// LAYOUT', '布局结构'),
            ('// Script', '演讲脚本')
        ]
        
        for marker, name in sections:
            if marker not in slide:
                errors.append(f"Page {i}: Missing mandatory section '{name}' ({marker}).")

        # Specific SNR Checks
        # Headline check
        headline_match = re.search(r'Headline:\s*(.*)', slide)
        if headline_match:
            headline = headline_match.group(1).strip()
            if len(headline) < 5 or len(headline) > 60:
                errors.append(f"Page {i}: Headline length ({len(headline)}) is non-optimal.")
        
        # Bullet point limit in Body/Data
        body_part = re.search(r'Body/Data:([\s\S]*?)// VISUAL', slide)
        if body_part:
            body = body_part.group(1).strip()
            bullet_count = len(re.findall(r'^[\s\t]*[\*\-]\s', body, re.MULTILINE))
            if bullet_count > 5: # Slightly relaxed for narrative data density
                errors.append(f"Page {i}: Body/Data has {bullet_count} bullets, exceeding narrative SNR limit (5).")

    return errors

def main():
    parser = argparse.ArgumentParser(description="Mentat Narrative Auditor")
    parser.add_argument("file", help="Path to blueprint file")
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        sys.exit(1)
        
    with open(args.file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    print(f"--- Mentat Narrative Audit: {os.path.basename(args.file)} ---")
    errors = audit_narrative_blueprint(content)
    
    if errors:
        print("\n[!] NARRATIVE_AUDIT_FAILED")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\n[OK] Narrative Blueprint Verified: Strategic Alignment Confirmed.")
        sys.exit(0)

if __name__ == "__main__":
    main()
