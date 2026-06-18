from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Ensure the scripts directory is in path if executed directly
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from hub_utils import REFINED_PATH

def heuristic_fix_json(content: str) -> str:
    """Attempt basic fixes for common LLM JSON truncation/formatting issues."""
    content = content.strip()
    
    # 1. Close unclosed string at the end
    if content.count('"') % 2 != 0:
        content += '"'
        
    # 2. Add missing closing brackets for lists/objects based on truncation
    open_braces = content.count('{')
    close_braces = content.count('}')
    open_brackets = content.count('[')
    close_brackets = content.count(']')
    
    if open_brackets > close_brackets:
        content += "]" * (open_brackets - close_brackets)
    if open_braces > close_braces:
        content += "}" * (open_braces - close_braces)
        
    # 3. Remove trailing commas before closing braces/brackets
    content = re.sub(r',\s*\}', '}', content)
    content = re.sub(r',\s*\]', ']', content)
    
    return content

def validate() -> None:
    if not REFINED_PATH.exists():
        print(f"[ERROR] Refined data file not found at {REFINED_PATH}")
        sys.exit(1)

    try:
        content = REFINED_PATH.read_text(encoding="utf-8").strip()
        
        # Clean markdown wrappers if they exist
        cleaned = re.sub(r"^```(?:json)?", "", content, flags=re.MULTILINE).strip()
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
        
        # Parse JSON to ensure validity
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            print("[WARN] JSON decode failed, attempting heuristic repair...")
            repaired = heuristic_fix_json(cleaned)
            try:
                data = json.loads(repaired)
                print("[WARN] Heuristic repair successful.")
            except json.JSONDecodeError as e2:
                print(f"[ERROR] Invalid JSON in {REFINED_PATH} even after repair: {e2}")
                print("Please manually fix the JSON or have the subagent regenerate it.")
                sys.exit(1)
        
        # Write back cleanly
        REFINED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Refined JSON is valid and cleaned at {REFINED_PATH}")
    except Exception as e:
        print(f"[ERROR] Unexpected error while validating {REFINED_PATH}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    validate()
