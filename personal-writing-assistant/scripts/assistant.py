# ---
# Title: Personal Writing Assistant - Context Builder
# Date: 2026-02-21
# Status: Active
# Author: Strategy Architect
# Description: CLI tool to assemble full prompt context for the writing engine.
# ---

"""
Context builder for the Personal Writing Assistant.
Assembles guidelines, templates, styles, anti-patterns, and checklist
into a single prompt for the LLM to process.

Usage:
    python assistant.py --topic "医院数字化转型" --mode Deep --role "资深顾问" --style narrative --template thought-leadership
"""

import argparse
import sys
import os
from pathlib import Path

# --- Configuration ---
SCRIPT_DIR = Path(__file__).parent.absolute()
ROOT_DIR = SCRIPT_DIR.parent
REFERENCES_DIR = ROOT_DIR / "references"

GUIDELINES_PATH = REFERENCES_DIR / "GUIDELINES.md"
EXAMPLES_PATH = REFERENCES_DIR / "EXAMPLES.md"
CHECKLIST_PATH = REFERENCES_DIR / "CHECKLIST.md"
ANTI_PATTERNS_PATH = REFERENCES_DIR / "ANTI_PATTERNS.md"
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
    """Assemble the full prompt context from all reference materials."""
    guidelines = load_file(GUIDELINES_PATH)
    examples = load_file(EXAMPLES_PATH)
    checklist = load_file(CHECKLIST_PATH)
    anti_patterns = load_file(ANTI_PATTERNS_PATH)

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

**Anti-Pattern Alerts**:
{anti_patterns}

**Task**:
Generate a deep, insightful article on "{topic}".

**Five-Phase Process**:
1. **Phase 0 - Empathy & Reconnaissance**: Align intent and anchor facts
2. **Phase 1 - Deep Logic Construction**: Find the hidden dynamics and inconvenient truths
3. **Phase 2 - SCQA Architecture**: Generate the skeletal outline
4. **Phase 3 - Surgical Drafting**: Draft with verb-driven style and evidence weaving
5. **Phase 4 - Surgeon's Audit**: Self-check against checklist, anti-patterns, and append Analyst's Note

**Constraints**:
- Do NOT use clichés like "赋能" (empower), "闭环" (closed loop), or "抓手" (grip)
- Speak like a human expert having a late-night coffee with a peer
- Run through the full checklist and anti-pattern scan before finalizing
"""
    return final_prompt


def main():
    parser = argparse.ArgumentParser(
        description="Personal Writing Assistant - Generate insightful articles"
    )
    parser.add_argument("--topic", required=True, help="The core subject matter")
    parser.add_argument(
        "--mode", default="Standard",
        choices=["Summary", "Standard", "Deep"],
        help="Writing depth (default: Standard)"
    )
    parser.add_argument(
        "--role", default="Strategic Consultant",
        help="The persona to adopt (default: Strategic Consultant)"
    )
    parser.add_argument(
        "--style", default="default",
        choices=["default", "narrative", "academic", "provocative", "balanced"],
        help="Writing style variant"
    )
    parser.add_argument(
        "--template",
        choices=["industry-analysis", "product-review", "thought-leadership", "case-study"],
        help="Use a specific article template"
    )
    args = parser.parse_args()

    # Generate and print the prompt for the LLM to process
    print(generate_prompt(args.topic, args.mode, args.role, args.style, args.template))


if __name__ == "__main__":
    main()
