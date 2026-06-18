import os
import re
import sys
import argparse

VERSION = "11.2"

def fix_encoding(file_path):
    try:
        with open(file_path, "rb") as handle:
            raw = handle.read()
        if raw.startswith(b"\xef\xbb\xbf"):
            content = raw[3:].decode("utf-8")
        else:
            content = raw.decode("utf-8")
        with open(file_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        return content
    except Exception as exc:
        print(f"Error fixing encoding for {file_path}: {exc}")
        return None

def audit_outline(content):
    errors = []
    
    if "<STYLE_INSTRUCTIONS>" not in content:
        errors.append("Global: Missing mandatory <STYLE_INSTRUCTIONS> block.")
        
    matches = list(re.finditer(r'^---\n(Type:.*?)\n---\n([\s\S]*?)(?=(^---\nType:|\Z))', content, re.MULTILINE))
    
    if not matches:
        errors.append("Global: No slides detected. Ensure slide YAML headers exist.")
        return errors
        
    for index, match in enumerate(matches, 1):
        yaml_header = match.group(1)
        body = match.group(2)
        
        if "Type:" not in yaml_header:
             errors.append(f"Slide {index}: Missing 'Type:' in YAML header.")
             
        # 1. Check Primary Blocks
        required_blocks = [
            "// NARRATIVE GOAL",
            "// KEY CONTENT",
            "// VISUAL DIRECTIVE",
            "// Script"
        ]
        for block in required_blocks:
            if block not in body:
                errors.append(f"Slide {index}: Missing mandatory block '{block}'.")
                
        # 2. Deep Validator for Subfields inside KEY CONTENT
        key_content_match = re.search(r"// KEY CONTENT([\s\S]*?)(?=// VISUAL DIRECTIVE|// Script|\Z)", body)
        if key_content_match:
            text = key_content_match.group(1)
            required_subfields = [
                "[Lead-in / Action Title]",
                "[Arc & SCR Logic]",
                "[Sub-headline]",
                "[Key Insight]",
                "[Key Content / Data Matrix]"
            ]
            for sf in required_subfields:
                if sf not in text:
                    errors.append(f"Slide {index}: Missing nested field '{sf}' inside KEY CONTENT.")
                    
    return errors

def main():
    parser = argparse.ArgumentParser(description=f"Presentation blueprint validator V{VERSION}")
    parser.add_argument("path", help="Path to outline.md file or directory of chunk_*.md files")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Path does not exist: {args.path}")
        sys.exit(1)

    merged_content = ""
    if os.path.isdir(args.path):
        files = sorted([f for f in os.listdir(args.path) if f.endswith(".md")])
        if not files:
            print(f"No markdown files found in directory {args.path}")
            sys.exit(1)
        for file in files:
            file_path = os.path.join(args.path, file)
            content = fix_encoding(file_path)
            if content:
                merged_content += content + "\n\n"
    else:
        merged_content = fix_encoding(args.path)

    if not merged_content:
        sys.exit(1)

    errors = audit_outline(merged_content)
    if errors:
        print("\n[!] BLUEPRINT_AUDIT_FAILED")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print("\n[OK] Blueprint verified: V11 Hybrid blocks and nested structures passed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
