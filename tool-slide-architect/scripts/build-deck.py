import os
import re
import sys
import json
import argparse
import subprocess

VERSION = "12.0"

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
        if not files:
            return None
        for file in files:
            file_path = os.path.join(path, file)
            with open(file_path, "r", encoding="utf-8") as handle:
                merged_content += handle.read() + "\n\n"
    else:
        with open(path, "r", encoding="utf-8") as handle:
            merged_content = handle.read()
            
    return merged_content

def parse_style_block(content):
    match = re.search(r"<STYLE_INSTRUCTIONS>([\s\S]*?)</STYLE_INSTRUCTIONS>", content)
    raw = match.group(1).strip() if match else ""
    return raw

def parse_slides(content):
    slides = []
    pattern = re.compile(r"Page\s+(\d+):\s*(.*?)\n([\s\S]*?)(?=\n---\s*(?:\n|$)|\Z)")
    for match in pattern.finditer(content):
        page_no = int(match.group(1))
        title = match.group(2).strip()
        body = match.group(3).strip()

        def extract(pattern_text):
            found = re.search(pattern_text, body)
            return found.group(1).strip() if found else ""

        body_data = extract(r"Body/Data:\s*([\s\S]*?)Trust_Anchor:")
        slide_type = extract(r"Type:\s*(Cover|Content|SectionBreak|Closing)")
        arc = extract(r"\[Arc:\s*(.*?)\]")
        bg_style = extract(r"\[Bg:\s*(.*?)\]")

        slides.append({
            "page": page_no,
            "title": title,
            "type": slide_type,
            "arc": arc,
            "bg_style": bg_style,
            "headline": extract(r"Headline:\s*(.*)"),
            "body_data": body_data,
        })
    return slides

def parse_header(content):
    header = {}
    for key in ["Topic", "Audience", "Objective", "Language", "Style", "Slide Count", "Generated"]:
        match = re.search(rf"\*\*{re.escape(key)}\*\*:\s*(.*)", content)
        if match:
            header[key.lower().replace(" ", "_")] = match.group(1).strip()
    return header

def main():
    parser = argparse.ArgumentParser(description=f"Presentation blueprint packager V{VERSION}")
    parser.add_argument("path", help="Directory containing chunk_*.md files or path to outline.md")
    parser.add_argument("--output", "-o", default="blueprint_bundle.json", help="Output JSON filename")
    args = parser.parse_args()

    deck_path = args.path
    if not os.path.exists(deck_path):
        print(f"❌ ABORTING: path not found: {deck_path}")
        sys.exit(1)

    print("--- Step 1: Blueprint Audit ---")
    result = run_validator(deck_path)
    if result.returncode != 0:
        print(result.stdout)
        print("\n❌ ABORTING: Blueprint audit failed.")
        sys.exit(1)
    print(result.stdout)
    print("[OK] Blueprint Audit Passed.")

    content = get_merged_content(deck_path)
    if not content:
        print("❌ ABORTING: Could not extract content from markdown files.")
        sys.exit(1)

    # Save merged outline if directory
    if os.path.isdir(deck_path):
        merged_outline_path = os.path.join(deck_path, "outline_merged.md")
        with open(merged_outline_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f"[OK] Merged outline saved to {merged_outline_path}")
        output_dir = deck_path
    else:
        output_dir = os.path.dirname(deck_path)

    bundle = {
        "version": VERSION,
        "style_instructions": parse_style_block(content),
        "header": parse_header(content),
        "slides": parse_slides(content),
    }

    output_path = os.path.join(output_dir, args.output)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)

    print(f"\n[OK] BLUEPRINT PACKAGE READY: {output_path}")

if __name__ == "__main__":
    main()
