import json
import re
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from hub_utils import REFINED_PATH

def extract() -> None:
    if not REFINED_PATH.exists():
        print(f"No file at {REFINED_PATH}")
        sys.exit(0)
    
    content = REFINED_PATH.read_text(encoding="utf-8")
    # Extract ALL entities from the entire JSON structure
    entities = set(re.findall(r"\[\[(.*?)\]\]", content))
    
    # Path relative to REFINED_PATH: C:\Users\shich\.gemini\MEMORY\wiki
    wiki_dir = REFINED_PATH.parent.parent.parent / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    
    for entity in entities:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", entity).strip()
        if not safe_name:
            continue
        entity_path = wiki_dir / f"Entity_{safe_name}.md"
        if not entity_path.exists():
            entity_path.write_text(f"# {entity}\n\nGenerated from Intelligence Hub.\n", encoding="utf-8")
            print(f"Created {entity_path}")

if __name__ == "__main__":
    extract()
