import os
import re
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Generate prompt files from outline.md")
    parser.add_argument("dir", help="Slide deck directory containing outline.md")
    args = parser.parse_args()

    deck_dir = args.dir
    outline_path = os.path.join(deck_dir, "outline.md")
    prompts_dir = os.path.join(deck_dir, "prompts")

    # Determine script directory to find base-prompt.md
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    SKILL_DIR = os.path.dirname(SCRIPT_DIR)
    BASE_PROMPT_PATH = os.path.join(SKILL_DIR, "references", "base-prompt.md")

    if not os.path.exists(outline_path):
        print(f"Error: outline.md not found in {deck_dir}")
        return
    
    if not os.path.exists(BASE_PROMPT_PATH):
        print(f"Error: Base prompt not found at {BASE_PROMPT_PATH}")
        return

    if not os.path.exists(prompts_dir):
        os.makedirs(prompts_dir)
        print(f"Created directory: {prompts_dir}")

    # Read Base Prompt
    with open(BASE_PROMPT_PATH, 'r', encoding='utf-8') as f:
        base_prompt_template = f.read()

    # Read Outline
    with open(outline_path, 'r', encoding='utf-8') as f:
        outline_content = f.read()

    # Extract Style Instructions
    style_match = re.search(r'(<STYLE_INSTRUCTIONS>.*?</STYLE_INSTRUCTIONS>)', outline_content, re.DOTALL)
    if not style_match:
        print("Error: STYLE_INSTRUCTIONS block not found in outline.md.")
        return
    style_instructions = style_match.group(1)

    # Split slides
    # Robust split looking for "## Slide " at start of line
    slides = re.split(r'\n## Slide ', outline_content)
    
    # Skip the first part (metadata before the first slide)
    if len(slides) < 2:
        print("Error: No slides found in outline.md (expected '## Slide ' markers).")
        return
        
    metadata_part = slides[0]
    slide_parts = slides[1:]

    print(f"Found {len(slide_parts)} slides.")

    for i, slide_content in enumerate(slide_parts):
        full_slide_content = "## Slide " + slide_content.strip()
        
        # Extract filename from "**Filename**: 01-slide-cover.png"
        filename_match = re.search(r'\*\*Filename\*\*: (.*?)\.png', full_slide_content)
        if filename_match:
            filename_base = filename_match.group(1)
            filename = f"{filename_base}.md"
            
            # Construct Prompt
            
            # Find the footer instruction (last part of base prompt)
            footer_match = re.search(r'---\s+Please use nano banana pro.*', base_prompt_template, re.DOTALL | re.IGNORECASE)
            footer = footer_match.group(0) if footer_match else "\n\nPlease use nano banana pro (`gemini-3-pro-image-preview`) to generate the slide image based on the content provided above."
            
            # Header part
            header_parts = base_prompt_template.split("## STYLE_INSTRUCTIONS")
            if len(header_parts) > 0:
                header = header_parts[0].strip()
            else:
                header = "# Presentation Slide Generation"

            prompt = f"""{header}

## STYLE_INSTRUCTIONS

{style_instructions}

---

## SLIDE CONTENT

{full_slide_content}

{footer}
"""
            
            output_path = os.path.join(prompts_dir, filename)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"Generated {filename}")
        else:
            print(f"Warning: Could not extract filename from Slide {i+1}")

if __name__ == "__main__":
    main()