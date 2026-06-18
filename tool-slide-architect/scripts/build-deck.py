import os
import re
import sys
import json
import argparse
import subprocess

VERSION = "11.2"

def run_validator(path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    validator_path = os.path.join(script_dir, "validator.py")
    result = subprocess.run([sys.executable, validator_path, path], capture_output=True, text=True)
    return result

def get_merged_content(path):
    if not os.path.exists(path):
        return None
    merged_content = ""
    if os.path.isdir(path):
        files = sorted([f for f in os.listdir(path) if f.endswith(".md")])
        for file in files:
            with open(os.path.join(path, file), "r", encoding="utf-8") as handle:
                merged_content += handle.read() + "\n\n"
    else:
        with open(path, "r", encoding="utf-8") as handle:
            merged_content = handle.read()
    return merged_content

def parse_style_block(content):
    match = re.search(r"<STYLE_INSTRUCTIONS>([\s\S]*?)</STYLE_INSTRUCTIONS>", content)
    return match.group(1).strip() if match else ""

def parse_slides(content):
    slides = []
    matches = re.finditer(r'^---\n(Type:.*?)\n---\n([\s\S]*?)(?=(^---\nType:|\Z))', content, re.MULTILINE)
    
    for index, match in enumerate(matches, 1):
        yaml_header = match.group(1)
        body = match.group(2)
        
        # 1. Parse YAML Meta
        meta = {}
        for line in yaml_header.strip().split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                meta[k.strip()] = v.strip()
                
        # 2. Extract Top-level Blocks
        def extract_block(start_marker, next_markers):
            lookahead = "|".join([rf"\n{re.escape(m)}" for m in next_markers]) + r"|\Z"
            pattern = rf"{re.escape(start_marker)}[^\n]*\n([\s\S]*?)(?={lookahead})"
            found = re.search(pattern, body)
            return found.group(1).strip() if found else ""
            
        goal_text = extract_block("// NARRATIVE GOAL", ["// KEY CONTENT", "// VISUAL DIRECTIVE", "// Script"])
        key_content_text = extract_block("// KEY CONTENT", ["// VISUAL DIRECTIVE", "// Script"])
        visual_text = extract_block("// VISUAL DIRECTIVE", ["// Script"])
        script_text = extract_block("// Script", ["---"])
        
        # 3. Extract Nested Fields (Robust Regex)
        def extract_subfield(text, marker_name):
            # Looks for [Marker Name] and stops at the next item which starts with number/bullet and optionally **[
            pattern = rf"\[{re.escape(marker_name)}\][^\n]*?:?\s*([\s\S]*?)(?=\n[0-9\-\*]\.?\s*\*?\*?\[|\Z)"
            found = re.search(pattern, text)
            return found.group(1).strip() if found else text.strip() if text else ""

        key_content_struct = {
            "action_title": extract_subfield(key_content_text, "Lead-in / Action Title"),
            "arc_logic": extract_subfield(key_content_text, "Arc & SCR Logic"),
            "sub_headline": extract_subfield(key_content_text, "Sub-headline"),
            "key_insight": extract_subfield(key_content_text, "Key Insight"),
            "data_matrix": extract_subfield(key_content_text, "Key Content / Data Matrix")
        }
        
        visual_struct = {
            "metadata_control": extract_subfield(visual_text, "元数据控制"),
            "layout": extract_subfield(visual_text, "LAYOUT 布局结构"),
            "visual_content": extract_subfield(visual_text, "VISUAL 视觉画面"),
            "chart_suggestion": extract_subfield(visual_text, "Chart Suggestion & Visual Restraint")
        }
        
        script_struct = {
            "transcript": extract_subfield(script_text, "演讲逐字稿"),
            "notes": extract_subfield(script_text, "演讲注意事项")
        }
        
        slides.append({
            "page": index,
            "meta": meta,
            "narrative_goal": goal_text,
            "key_content": key_content_struct,
            "visual_directive": visual_struct,
            "script": script_struct
        })
    return slides

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--output", "-o", default="blueprint_bundle.json")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        sys.exit(1)

    print("--- Step 1: Blueprint Audit ---")
    result = run_validator(args.path)
    if result.returncode != 0:
        print(result.stdout)
        sys.exit(1)
    print(result.stdout)
    
    content = get_merged_content(args.path)
    output_dir = args.path if os.path.isdir(args.path) else os.path.dirname(args.path)
    
    bundle = {
        "version": VERSION,
        "style_instructions": parse_style_block(content),
        "slides": parse_slides(content)
    }

    output_path = os.path.join(output_dir, args.output)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)

    print(f"\n[OK] BLUEPRINT PACKAGE READY: {output_path}")

if __name__ == "__main__":
    main()
