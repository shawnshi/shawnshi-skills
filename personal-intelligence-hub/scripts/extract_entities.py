import json
import re
from pathlib import Path

refined_path = Path(r"C:\Users\shich\.gemini\MEMORY\raw\news\intelligence_current_refined.json")
data = json.loads(refined_path.read_text(encoding="utf-8"))

entities = set()
for item in data.get("top_10", []):
    for k in ["fact", "connection", "deduction", "actionability"]:
        text = item.get(k, "")
        found = re.findall(r"\[\[(.*?)\]\]", text)
        entities.update(found)

wiki_dir = Path(r"C:\Users\shich\.gemini\MEMORY\wiki")
wiki_dir.mkdir(parents=True, exist_ok=True)

for entity in entities:
    safe_name = re.sub(r'[\\/*?:"<>|]', "", entity)
    entity_path = wiki_dir / f"Entity_{safe_name}.md"
    if not entity_path.exists():
        entity_path.write_text(f"# {entity}\n\nGenerated from Intelligence Hub.\n", encoding="utf-8")
        print(f"Created {entity_path}")
