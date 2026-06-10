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
        data = json.loads(cleaned)
        
        # Schema validation
        try:
            import jsonschema
            schema_path = current_dir.parent / "references" / "refined_schema.json"
            if schema_path.exists():
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                jsonschema.validate(instance=data, schema=schema)
                print("[OK] Schema validation passed.")
            else:
                print("[WARNING] Schema file not found, skipping strict validation.")
        except ImportError:
            print("[WARNING] jsonschema not installed, skipping strict validation.")
        except Exception as e:
            print(f"[ERROR] Schema validation failed: {e}")
            sys.exit(1)
        
        # Write back cleanly
        REFINED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Refined JSON is valid and cleaned at {REFINED_PATH}")
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in {REFINED_PATH}: {e}")
        print("Please manually fix the JSON or have the subagent regenerate it.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Unexpected error while validating {REFINED_PATH}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    validate()
