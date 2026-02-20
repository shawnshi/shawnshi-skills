"""
<!-- Intelligence Hub: Dynamic Calibration V2.1 -->
@Input: root/pai/memory.md
@Output: references/strategic_focus.json
@Pos: Phase 0 (Focus Calibration)
"""
import json
import os
import re
from pathlib import Path
from collections import Counter

def calibrate():
    # 1. Resolve Paths Safely
    current_dir = Path(__file__).parent
    root_dir = current_dir.parents[2] # .../skills/intelligence-hub/scripts -> .../.gemini
    
    memory_path = root_dir / "pai" / "memory.md"
    focus_path = current_dir.parent / "references" / "strategic_focus.json"
    
    if not memory_path.exists():
        print(f"Error: memory.md not found at {memory_path}")
        return

    # 2. Extract Strategic Keywords
    with open(memory_path, 'r', encoding='utf-8') as f:
        content = f.read().lower()
    
    # Heuristic: Focus on MSL, ACE, HITL and Medical domains
    words = re.findall(r'\b[a-z]{3,}\b', content)
    weights = {
        "msl": 20, "ace": 20, "hitl": 20, "medical": 15, 
        "agent": 15, "fhir": 15, "clinic": 10, "vbc": 10
    }
    
    # 3. Update focus.json (Skeleton)
    with open(focus_path, 'r', encoding='utf-8') as f:
        focus_data = json.load(f)
    
    # Sync weights based on occurrence frequency in memory.md
    for kw, weight in weights.items():
        if kw in content:
            # Upsert into strategic_keywords
            exists = False
            for entry in focus_data['strategic_keywords']:
                if entry['keyword'] == kw:
                    entry['weight'] = weight
                    exists = True
            if not exists:
                focus_data['strategic_keywords'].append({"keyword": kw, "weight": weight})

    with open(focus_path, 'w', encoding='utf-8') as f:
        json.dump(focus_data, f, ensure_ascii=False, indent=2)
    
    print(f"Strategic Focus calibrated successfully at: {focus_path}")

if __name__ == "__main__":
    calibrate()
