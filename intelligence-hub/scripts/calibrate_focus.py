"""
<!-- Intelligence Hub: Dynamic Calibration V4.0 -->
@Input: root/pai/memory.md
@Output: references/strategic_focus.json
@Pos: Phase 0 (Focus Calibration)
@Maintenance Protocol: Weight table changes must sync SKILL.md.
"""
import json
import re
from pathlib import Path
from collections import Counter

import jieba
import jieba.analyse
from utils import PROJECT_ROOT, HUB_DIR

# Resolve paths dynamically
MEMORY_PATH = PROJECT_ROOT / "pai" / "memory.md"
FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"

# Base weights for strategic domains (minimum weight even if not in memory.md)
BASE_WEIGHTS = {
    "msl": 15, "ace": 15, "hitl": 15,
    "medical": 12, "agent": 12, "fhir": 12,
    "clinic": 8, "vbc": 8, "drg": 10, "dip": 10,
    "信创": 10, "互联互通": 10, "hospital": 8, "ehr": 8
}

# Frequency bonus scaling: each occurrence adds this much weight (capped)
FREQ_BONUS_PER_HIT = 2
MAX_BONUS = 15

def calibrate():
    if not MEMORY_PATH.exists():
        print(f"⚠️ Warning: memory.md not found at {MEMORY_PATH}")
        print("  Skipping calibration. Using existing strategic_focus.json as-is.")
        return

    if not FOCUS_PATH.exists():
        print(f"⚠️ Warning: strategic_focus.json not found at {FOCUS_PATH}")
        return

    content = MEMORY_PATH.read_text(encoding="utf-8").lower()

    # 1. Load existing focus config
    focus_data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
    existing_keywords = {
        entry["keyword"]: entry for entry in focus_data["strategic_keywords"]
    }
    all_known_keywords = set(BASE_WEIGHTS.keys()).union(existing_keywords.keys())

    # 2. Count frequencies precisely (word boundaries for English, substring for Chinese)
    word_freq = {}
    for kw in all_known_keywords:
        kw_lower = kw.lower()
        if re.match(r'^[a-z0-9]+$', kw_lower):
            matches = re.findall(rf'\b{re.escape(kw_lower)}\b', content)
            word_freq[kw_lower] = len(matches)
        else:
            word_freq[kw_lower] = content.count(kw_lower)

    # 3. Extract new strategic keywords using TF-IDF
    # We allow Nouns (n), proper nouns (nz), verbs (v), vn
    new_extracted = jieba.analyse.extract_tags(content, topK=5, allowPOS=('n', 'nz', 'vn', 'v'))

    # 4. Update weights based on frequency analysis
    updated_count = 0
    
    # Process base weights and existing known keywords
    for keyword in all_known_keywords:
        kw_lower = keyword.lower()
        base_weight = BASE_WEIGHTS.get(keyword, 5) # Default base weight is 5
        
        freq = word_freq.get(kw_lower, 0)
        bonus = min(freq * FREQ_BONUS_PER_HIT, MAX_BONUS)
        new_weight = base_weight + bonus

        if keyword in existing_keywords:
            old_weight = existing_keywords[keyword]["weight"]
            existing_keywords[keyword]["weight"] = new_weight
            if old_weight != new_weight:
                updated_count += 1
                print(f"  ↻ {keyword}: {old_weight} → {new_weight} (freq={freq})")
        else:
            focus_data["strategic_keywords"].append({
                "keyword": keyword, "weight": new_weight
            })
            existing_keywords[keyword] = focus_data["strategic_keywords"][-1]
            updated_count += 1
            print(f"  + {keyword}: {new_weight} (new base, freq={freq})")

    # Dynamically add TF-IDF extracted keywords if they don't exist
    for new_kw in new_extracted:
        # Ignore single characters
        if len(new_kw) <= 1:
            continue
            
        new_kw_lower = new_kw.lower()
        existing_lower = [k.lower() for k in existing_keywords.keys()]
        
        if new_kw_lower not in existing_lower:
            # Assign a dynamic base weight of 5 + frequency bonus
            freq = content.count(new_kw_lower)
            bonus = min(freq * FREQ_BONUS_PER_HIT, MAX_BONUS)
            dynamic_weight = 5 + bonus
            
            focus_data["strategic_keywords"].append({
                "keyword": new_kw, "weight": dynamic_weight
            })
            updated_count += 1
            print(f"  ✨ {new_kw}: {dynamic_weight} (Auto-extracted via TF-IDF, freq={freq})")

    # 5. Write back
    FOCUS_PATH.write_text(
        json.dumps(focus_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ Strategic Focus calibrated: {updated_count} keywords updated at {FOCUS_PATH}")

if __name__ == "__main__":
    calibrate()
