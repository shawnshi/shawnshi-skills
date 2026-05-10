import os
import re
import sys
import json
import argparse
import subprocess

VERSION = "11.0"


def run_validator(outline_file):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    validator_path = os.path.join(script_dir, "validator.py")
    result = subprocess.run([sys.executable, validator_path, outline_file], capture_output=True, text=True)
    return result


def parse_style_block(content):
    match = re.search(r"<STYLE_INSTRUCTIONS>([\s\S]*?)</STYLE_INSTRUCTIONS>", content)
    raw = match.group(1).strip() if match else ""
    sections = {
        "raw": raw,
        "design_aesthetic": "",
        "background": "",
        "typography": "",
        "color_palette": "",
        "visual_elements": "",
        "density_guidelines": "",
        "style_rules": "",
    }
    if not raw:
        return sections

    markers = [
        ("Design Aesthetic:", "design_aesthetic"),
        ("Background:", "background"),
        ("Typography:", "typography"),
        ("Color Palette:", "color_palette"),
        ("Visual Elements:", "visual_elements"),
        ("Density Guidelines:", "density_guidelines"),
        ("Style Rules:", "style_rules"),
    ]

    for index, (marker, key) in enumerate(markers):
        start = raw.find(marker)
        if start == -1:
            continue
        start += len(marker)
        end = len(raw)
        for next_marker, _ in markers[index + 1:]:
            candidate = raw.find(next_marker, start)
            if candidate != -1:
                end = candidate
                break
        sections[key] = raw[start:end].strip()
    return sections


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
        script = extract(r"// Script:\s*([\s\S]*)$")
        slide_type = extract(r"Type:\s*(Cover|Content|Closing)")

        slides.append({
            "page": page_no,
            "title": title,
            "type": slide_type,
            "narrative_goal": extract(r"// NARRATIVE GOAL\s*([\s\S]*?)// KEY CONTENT"),
            "headline": extract(r"Headline:\s*(.*)"),
            "sub_headline": extract(r"Sub-headline:\s*(.*)"),
            "body_data": body_data,
            "trust_anchor": extract(r"Trust_Anchor:\s*(.*)"),
            "visual": extract(r"// VISUAL\s*([\s\S]*?)// LAYOUT"),
            "layout": extract(r"// LAYOUT\s*([\s\S]*?)// Script:"),
            "script": script,
        })
    return slides


def parse_header(content):
    header = {}
    for key in ["Topic", "Audience", "Objective", "Language", "Style", "Slide Count", "Generated"]:
        match = re.search(rf"\*\*{re.escape(key)}\*\*:\s*(.*)", content)
        header[key.lower().replace(" ", "_")] = match.group(1).strip() if match else ""
    return header


def main():
    parser = argparse.ArgumentParser(description=f"Presentation blueprint packager V{VERSION}")
    parser.add_argument("dir", help="Directory containing outline.md")
    parser.add_argument("--output", "-o", default="blueprint_bundle.json", help="Output JSON filename")
    args = parser.parse_args()

    deck_dir = args.dir
    outline_file = os.path.join(deck_dir, "outline.md")
    if not os.path.exists(outline_file):
        print("❌ ABORTING: outline.md not found.")
        sys.exit(1)

    print("--- Step 1: Blueprint Audit ---")
    result = run_validator(outline_file)
    if result.returncode != 0:
        print(result.stdout)
        print("\n❌ ABORTING: Blueprint audit failed.")
        sys.exit(1)
    print("[OK] Blueprint Audit Passed.")

    with open(outline_file, "r", encoding="utf-8") as handle:
        content = handle.read()

    bundle = {
        "version": VERSION,
        "header": parse_header(content),
        "style": parse_style_block(content),
        "slides": parse_slides(content),
    }

    output_path = os.path.join(deck_dir, args.output)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)

    print(f"\n[OK] BLUEPRINT PACKAGE READY: {output_path}")


if __name__ == "__main__":
    main()

