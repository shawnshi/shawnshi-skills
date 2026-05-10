import os
import re
import sys
import argparse

VERSION = "11.0"


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
        print(f"Error fixing encoding: {exc}")
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
    else:
        required_style_sections = [
            "Design Aesthetic:",
            "Background:",
            "Typography:",
            "Color Palette:",
            "Visual Elements:",
            "Density Guidelines:",
            "Style Rules:",
        ]
        for marker in required_style_sections:
            if marker not in style_block:
                errors.append(f"Global: STYLE_INSTRUCTIONS missing section '{marker}'.")

    narrative_content = re.sub(r"<STYLE_INSTRUCTIONS>[\s\S]*?</STYLE_INSTRUCTIONS>", "", content)
    slides = _extract_slides(narrative_content)
    if not slides:
        errors.append("Global: No slides detected with 'Page X:' markers.")
        return errors

    expected_pages = list(range(1, len(slides) + 1))
    actual_pages = [slide["page"] for slide in slides]
    if actual_pages != expected_pages:
        errors.append(f"Global: Page numbering must be sequential from 1..N. Found {actual_pages}.")

    for index, slide in enumerate(slides, 1):
        body = slide["body"]
        sections = [
            ("Type:", "slide type"),
            ("// NARRATIVE GOAL", "narrative goal"),
            ("// KEY CONTENT", "key content"),
            ("Headline:", "headline"),
            ("Sub-headline:", "sub-headline"),
            ("Body/Data:", "body/data"),
            ("Trust_Anchor:", "trust anchor"),
            ("// VISUAL", "visual"),
            ("// LAYOUT", "layout"),
            ("// Script:", "script"),
        ]
        for marker, name in sections:
            if marker not in body:
                errors.append(f"Page {index}: Missing mandatory {name} marker '{marker}'.")

        type_match = re.search(r"Type:\s*(Cover|Content|Closing)", body)
        slide_type = type_match.group(1) if type_match else None
        if index == 1 and slide_type != "Cover":
            errors.append("Page 1 must be Type: Cover.")
        elif index == len(slides) and slide_type != "Closing":
            errors.append("Final page must be Type: Closing.")
        elif index not in (1, len(slides)) and slide_type != "Content":
            errors.append(f"Page {index}: middle slides must be Type: Content.")

        headline_match = re.search(r"Headline:\s*(.*)", body)
        if headline_match:
            headline = headline_match.group(1).strip()
            if len(headline) < 5 or len(headline) > 80:
                errors.append(f"Page {index}: Headline length ({len(headline)}) is non-optimal.")

        body_match = re.search(r"Body/Data:\s*([\s\S]*?)Trust_Anchor:", body)
        if body_match:
            body_part = body_match.group(1)
            bullet_count = len(re.findall(r"^[\s\t]*[\*\-]\s", body_part, re.MULTILINE))
            if bullet_count > 6:
                errors.append(f"Page {index}: Body/Data has {bullet_count} bullets, exceeding blueprint limit (6).")
            if "电子病例" in body_part:
                errors.append(f"Page {index}: Compliance error - use '电子病历', not '电子病例'.")

        if slide_type == "Cover":
            if re.search(r"^[\s\t]*[\*\-]\s", body, re.MULTILINE):
                errors.append("Page 1: Cover slide should not contain dense bullet content.")

        if slide_type == "Closing":
            headline = headline_match.group(1).strip().lower() if headline_match else ""
            if headline in {"thank you", "thanks", "谢谢聆听", "谢谢"}:
                errors.append("Closing slide headline must be a CTA or thesis, not a generic thank-you.")

    return errors


def main():
    parser = argparse.ArgumentParser(description=f"Presentation blueprint validator V{VERSION}")
    parser.add_argument("file", help="Path to outline.md")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        sys.exit(1)

    content = fix_encoding(args.file)
    if content is None:
        sys.exit(1)

    print(f"--- Presentation Blueprint Audit (V{VERSION}): {os.path.basename(args.file)} ---")
    errors = audit_outline(content)
    if errors:
        print("\n[!] BLUEPRINT_AUDIT_FAILED")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print("\n[OK] Blueprint verified: schema, style contract, and special-slide rules passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
