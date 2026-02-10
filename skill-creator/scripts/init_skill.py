#!/usr/bin/env python3
"""
Skill Initializer (GEB-Flow Edition) - Creates a new skill from template

Usage:
    init_skill.py <skill-name> --path <path> [--resources scripts,references,assets] [--examples] [--interface key=value]
"""

import argparse
import re
import sys
import os
from pathlib import Path

# Try to import internal generators
try:
    from generate_openai_yaml import write_openai_yaml
except ImportError:
    # Fallback if not available in current execution context
    def write_openai_yaml(*args, **kwargs): return True

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_RESOURCES = {"scripts", "references", "assets"}

# --- Templates ---

DIR_META_TEMPLATE = """# _DIR_META.md

## Architecture Vision
[TODO: Max 3 lines describing the directory's purpose and its role in the ecosystem.]

## Member Index
- `SKILL.md`: [Manifest] Core instructions and triggers.
{resource_index}
- `agents/`: [UI] Identity and metadata configurations.

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
"""

SKILL_TEMPLATE = """---
name: {skill_name}
description: [TODO: Precise explanation of WHAT the skill does and WHEN to trigger it.]
---

# {skill_title}

## Overview
[TODO: Tactical overview of the skill's objective.]

## Core Workflow
1. **Analyze**: [TODO]
2. **Execute**: [TODO]
3. **Verify**: [TODO]

## Resources
[TODO: Reference scripts/ or references/ files here.]

!!! Maintenance Protocol: If logic or dependencies change, 
!!! update this file AND the Standard Headers in scripts/.
"""

GEMINI_YAML_TEMPLATE = """display_name: {skill_title}
short_description: [TODO: One-line UI description]
default_prompt: [TODO: Primary entry-point prompt]
interface:
  icon: extension
  brand_color: "#607d8b"
"""

EXAMPLE_SCRIPT = '''"""
<!-- Input: [TODO: Define inputs] -->
<!-- Output: [TODO: Define outputs] -->
<!-- Pos: scripts/{filename}. [TODO: Purpose] -->

!!! Maintenance Protocol: If logic changes, update this header and SKILL.md.
"""

def main():
    print("Executing {skill_name} logic...")

if __name__ == "__main__":
    main()
'''

# --- Implementation ---

def normalize_skill_name(skill_name):
    normalized = skill_name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")

def title_case_skill_name(skill_name):
    return " ".join(word.capitalize() for word in skill_name.split("-"))

def init_skill(skill_name, path, resources, include_examples, interface_overrides):
    skill_dir = Path(path).resolve() / skill_name
    if skill_dir.exists():
        print(f"[ERROR] Directory already exists: {skill_dir}")
        return False

    skill_dir.mkdir(parents=True)
    skill_title = title_case_skill_name(skill_name)

    # 1. Create SKILL.md
    (skill_dir / "SKILL.md").write_text(SKILL_TEMPLATE.format(skill_name=skill_name, skill_title=skill_title))
    
    # 2. Create _DIR_META.md
    res_idx = ""
    for r in resources:
        res_idx += f"- `{r}/`: [Resource] {r.capitalize()} for this skill.\\n"
    (skill_dir / "_DIR_META.md").write_text(DIR_META_TEMPLATE.format(resource_index=res_idx))

    # 3. Create agents/
    agents_dir = skill_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "gemini.yaml").write_text(GEMINI_YAML_TEMPLATE.format(skill_title=skill_title))
    
    # Trigger legacy generator for compatibility
    write_openai_yaml(skill_dir, skill_name, interface_overrides)

    # 4. Create Resources
    for res in resources:
        res_path = skill_dir / res
        res_path.mkdir(exist_ok=True)
        if res == "scripts" and include_examples:
            (res_path / "main.py").write_text(EXAMPLE_SCRIPT.format(filename="main.py", skill_name=skill_name))
            print("[OK] Created scripts/main.py with GEB-Flow Header")

    print(f"\\n[SUCCESS] Skill '{skill_name}' initialized at {skill_dir}")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_name")
    parser.add_argument("--path", required=True)
    parser.add_argument("--resources", default="")
    parser.add_argument("--examples", action="store_true")
    parser.add_argument("--interface", action="append", default=[])
    args = parser.parse_args()

    skill_name = normalize_skill_name(args.skill_name)
    resources = [r.strip() for r in args.resources.split(",") if r.strip()]
    
    init_skill(skill_name, args.path, resources, args.examples, args.interface)

if __name__ == "__main__":
    main()
