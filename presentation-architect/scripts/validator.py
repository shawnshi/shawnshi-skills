"""
<!-- Standard Header -->
@Input: outline.md (Narrative Blueprint)
@Output: Validation Result
@Phase: Phase 4 - Pre-flight Narrative Audit (叙事逻辑审计)
@Maintenance Protocol: Rules must sync SKILL.md V9.1.
"""
import os
import re
import sys
import argparse

def fix_encoding(file_path):
    """Win32 Encoding Guard: Force UTF-8 No BOM."""
    try:
        with open(file_path, 'rb') as f:
            raw = f.read()
        
        # Check for BOM
        if raw.startswith(b'\xef\xbb\xbf'):
            content = raw[3:].decode('utf-8')
        else:
            content = raw.decode('utf-8')
            
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        return content
    except Exception as e:
        print(f"Error fixing encoding: {e}")
        return None

def audit_narrative_blueprint(content):
    errors = []
    
    # 1. STYLE_INSTRUCTIONS Check
    if '<STYLE_INSTRUCTIONS>' not in content or '</STYLE_INSTRUCTIONS>' not in content:
        errors.append("Global: Missing mandatory <STYLE_INSTRUCTIONS> block.")

    # 2. Slide Splitting
    narrative_content = re.sub(r'<STYLE_INSTRUCTIONS>[\s\S]*?</STYLE_INSTRUCTIONS>', '', content)
    slides = re.split(r'Page \d+:', narrative_content)
    slides = [s for s in slides if s.strip()]
        
    for i, slide in enumerate(slides, 1):
        # Mandatory Sections Check (V9.1 Standards)
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

        # Headline check
        headline_match = re.search(r'Headline:\s*(.*)', slide)
        if headline_match:
            headline = headline_match.group(1).strip()
            if len(headline) < 5 or len(headline) > 80:
                errors.append(f"Page {i}: Headline length ({len(headline)}) is non-optimal.")
        
        # Body/Data SNR Check
        if "Body/Data:" in slide:
            body_part = slide.split("Body/Data:")[1].split("//")[0]
            bullet_count = len(re.findall(r'^[\s\t]*[\*\-]\s', body_part, re.MULTILINE))
            if bullet_count > 6: 
                errors.append(f"Page {i}: Body/Data has {bullet_count} bullets, exceeding narrative SNR limit (6).")

            if "电子病例" in body_part:
                errors.append(f"Page {i}: Compliance Error - Term '电子病例' detected. Use '电子病历' instead.")

    return errors

def main():
    parser = argparse.ArgumentParser(description="Mentat Narrative Auditor V9.1")
    parser.add_argument("file", help="Path to blueprint file")
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        sys.exit(1)
        
    # Phase 0: Encoding Guard
    content = fix_encoding(args.file)
    if content is None:
        sys.exit(1)
        
    print(f"--- Mentat Narrative Audit (V9.1): {os.path.basename(args.file)} ---")
    errors = audit_narrative_blueprint(content)
    
    if errors:
        print("\n[!] NARRATIVE_AUDIT_FAILED")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\n[OK] Narrative Blueprint Verified: Encoding Fixed & Strategic Alignment Confirmed.")
        sys.exit(0)

if __name__ == "__main__":
    main()
