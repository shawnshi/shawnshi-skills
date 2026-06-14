import os
import re
import sys
import argparse

VERSION = "12.0"

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

def _extract_style_block(content):
    match = re.search(r"<STYLE_INSTRUCTIONS>([\s\S]*?)</STYLE_INSTRUCTIONS>", content)
    return match.group(1).strip() if match else ""

def _extract_slides(content):
    slides = []
    pattern = re.compile(r"Page\s+(\d+):\s*(.*?)\n([\s\S]*?)(?=\n---\s*(?:\n|$)|\Z)")
    for match in pattern.finditer(content):
        slides.append({
            "page": int(match.group(1)),
            "title": match.group(2).strip(),
            "body": match.group(3).strip(),
        })
    return slides

def audit_outline(content):
    errors = []

    style_block = _extract_style_block(content)
    if not style_block:
        errors.append("Global: Missing mandatory <STYLE_INSTRUCTIONS> block.")

    narrative_content = re.sub(r"<STYLE_INSTRUCTIONS>[\s\S]*?</STYLE_INSTRUCTIONS>", "", content)
    slides = _extract_slides(narrative_content)
    if not slides:
        errors.append("Global: No slides detected with 'Page X:' markers.")
        return errors

    expected_pages = list(range(1, len(slides) + 1))
    actual_pages = [slide["page"] for slide in slides]
    if actual_pages != expected_pages:
        errors.append(f"Global: Page numbering must be sequential from 1..N. Found {actual_pages}.")

    valid_arcs = {"Hook", "Context", "Core", "Shift", "Takeaway"}
    
    for index, slide in enumerate(slides, 1):
        body = slide["body"]
        
        # Check required sections
        sections = [
            ("Type:", "slide type"),
            ("Headline:", "headline"),
            ("Body/Data:", "body/data"),
            ("Trust_Anchor:", "trust anchor")
        ]
        for marker, name in sections:
            if marker not in body:
                errors.append(f"Page {index}: Missing mandatory {name} marker '{marker}'.")

        # Type validation
        type_match = re.search(r"Type:\s*(Cover|Content|SectionBreak|Closing)", body)
        slide_type = type_match.group(1) if type_match else None
        if index == 1 and slide_type != "Cover":
            errors.append("Page 1 must be Type: Cover.")
        elif index == len(slides) and slide_type != "Closing":
            errors.append("Final page must be Type: Closing.")

        # Arc validation
        arc_match = re.search(r"\[Arc:\s*(.*?)\]", body)
        if not arc_match:
            errors.append(f"Page {index}: Missing mandatory Narrative Arc tag [Arc: *].")
        else:
            arc_val = arc_match.group(1).strip()
            if arc_val not in valid_arcs:
                errors.append(f"Page {index}: Invalid Arc tag '{arc_val}'. Must be one of {valid_arcs}.")
            
            if index == 1 and arc_val != "Hook":
                errors.append(f"Page 1: First page Arc must be Hook. Found {arc_val}.")
            if index == len(slides) and arc_val != "Takeaway":
                errors.append(f"Page {len(slides)}: Final page Arc must be Takeaway. Found {arc_val}.")

        # Headline constraint
        headline_match = re.search(r"Headline:\s*(.*)", body)
        if headline_match:
            headline = headline_match.group(1).strip()
            if len(headline) < 5 or len(headline) > 80:
                errors.append(f"Page {index}: Headline length ({len(headline)}) is non-optimal.")

        if slide_type == "Closing":
            headline = headline_match.group(1).strip().lower() if headline_match else ""
            if headline in {"thank you", "thanks", "谢谢聆听", "谢谢"}:
                errors.append("Closing slide headline must be a CTA or thesis, not a generic thank-you.")

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

    print(f"--- Presentation Blueprint Audit (V{VERSION}): {os.path.basename(args.path)} ---")
    errors = audit_outline(merged_content)
    if errors:
        print("\n[!] BLUEPRINT_AUDIT_FAILED")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print("\n[OK] Blueprint verified: schema, style contract, and narrative arc rules passed.")
    sys.exit(0)

if __name__ == "__main__":
    main()
