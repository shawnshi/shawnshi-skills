"""
<!-- Input: Topic, Mode (Summary/Deep), Role, Style, Template -->
<!-- Output: Full Prompt Context for Strategic Writing -->
<!-- Pos: scripts/assistant.py. Context builder for the writing engine. -->

!!! Maintenance Protocol: Update file paths if directory structure changes.
!!! Ensure references/ directory contains all required MD files.
"""

import argparse
import sys
import os
from pathlib import Path

# --- Configuration ---
# Adjusted for new directory structure: this script is in /scripts, references are in /references
SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent
REFERENCES_DIR = ROOT_DIR / "references"

GUIDELINES_PATH = REFERENCES_DIR / "GUIDELINES.md"
EXAMPLES_PATH = REFERENCES_DIR / "EXAMPLES.md"
CHECKLIST_PATH = REFERENCES_DIR / "CHECKLIST.md"
ANTI_PATTERNS_PATH = REFERENCES_DIR / "ANTI_PATTERNS.md"
TEMPLATES_DIR = ROOT_DIR / "templates" # Assuming templates are still in root or moved?
# The analysis said templates/ exists. Let's assume it stayed in root or needs to be found.
# Actually I should have moved templates/ to references/templates/ or kept it. 
# The mv command `mv *.md references/` only moved files in root. Subdirs `templates/` etc stayed in root.
# Let's keep templates in root for now or references/templates would be cleaner?
# Standardizing: let's point to ROOT_DIR/templates for now.
TEMPLATES_DIR = ROOT_DIR / "templates"
STYLES_DIR = ROOT_DIR / "styles"

def load_file(file_path):
    """Load a file with proper error handling."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"[File not found: {file_path}]"
    except Exception as e:
        return f"[Error reading file: {str(e)}]"

def generate_prompt(topic, mode, role, style="default", template=None):
    guidelines = load_file(GUIDELINES_PATH)
    examples = load_file(EXAMPLES_PATH)
    checklist = load_file(CHECKLIST_PATH)

    # Load template if specified
    template_content = ""
    if template:
        template_path = TEMPLATES_DIR / f"{template}.md"
        template_content = load_file(template_path)

    # Load style if specified
    style_content = ""
    if style != "default":
        style_path = STYLES_DIR / f"{style}.md"
        style_content = load_file(style_path)

    final_prompt = f"""
*** ACTIVATE SKILL: PERSONAL WRITING ASSISTANT ***

**Role**: {role}
**Topic**: {topic}
**Mode**: {mode}
**Style**: {style}
{f"**Template**: {template}" if template else ""}

**Reference Guidelines**:
{guidelines}

{f"**Template Structure**:{chr(10)}{template_content}" if template_content else ""}

{f"**Style Guide**:{chr(10)}{style_content}" if style_content else ""}

**Reference Examples**:
{examples}

**Quality Checklist**:
{checklist}

**Task**:
Generate a deep, insightful article on "{topic}".

**Three-Phase Process**:
1. **Deep Logic Construction**: Find the hidden dynamics and inconvenient truths
2. **Soul Synthesis**: Draft with conversational tone, verb-driven style
3. **Verification**: Self-check against the checklist and append Analyst's Note

**Constraints**:
- Do NOT use clichés like "赋能" (empower), "闭环" (closed loop), or "抓手" (grip)
- Speak like a human expert having a late-night coffee with a peer
- Run through the full checklist before finalizing
"""
    return final_prompt

def main():
    parser = argparse.ArgumentParser(description="Personal Writing Assistant - Generate insightful articles")
    parser.add_argument("--topic", required=True, help="The core subject matter")
    parser.add_argument("--mode", default="Standard", choices=["Summary", "Standard", "Deep"],
                        help="Writing depth (default: Standard)")
    parser.add_argument("--role", default="Strategic Consultant",
                        help="The persona to adopt (default: Strategic Consultant)")
    parser.add_argument("--style", default="default",
                        choices=["default", "narrative", "academic", "provocative", "balanced"],
                        help="Writing style variant")
    parser.add_argument("--template",
                        choices=["industry-analysis", "product-review", "thought-leadership", "case-study"],
                        help="Use a specific article template")
    args = parser.parse_args()

    # Generate and print the prompt for the LLM to process
    print(generate_prompt(args.topic, args.mode, args.role, args.style, args.template))

if __name__ == "__main__":
    main()
