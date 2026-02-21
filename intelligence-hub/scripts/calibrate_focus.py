"""
<!-- Intelligence Hub: Dynamic Calibration V3.0 -->
@Input: root/pai/memory.md
@Output: references/strategic_focus.json
@Pos: Phase 0 (Focus Calibration)
@Maintenance Protocol: Weight table changes must sync SKILL.md.
"""
import json
import re
from pathlib import Path
from collections import Counter
from utils import PROJECT_ROOT, HUB_DIR

# Resolve paths dynamically
MEMORY_PATH = PROJECT_ROOT / "pai" / "memory.md"
FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"

# Base weights for strategic domains (minimum weight even if not in memory.md)
BASE_WEIGHTS = {
    "msl": 15, "ace": 15, "hitl": 15,
    "medical": 12, "agent": 12, "fhir": 12,
    "clinic": 8, "vbc": 8, "drg": 10, "dip": 10,
}

# Frequency bonus scaling: each occurrence adds this much weight (capped)
FREQ_BONUS_PER_HIT = 2
MAX_BONUS = 10


def calibrate():
    if not MEMORY_PATH.exists():
        print(f"⚠️ Warning: memory.md not found at {MEMORY_PATH}")
        print("  Skipping calibration. Using existing strategic_focus.json as-is.")
        return

    if not FOCUS_PATH.exists():
        print(f"⚠️ Warning: strategic_focus.json not found at {FOCUS_PATH}")
        return

    # 1. Read and tokenize memory.md
    content = MEMORY_PATH.read_text(encoding="utf-8").lower()
    words = re.findall(r'\b[a-z]{3,}\b', content)
    word_freq = Counter(words)

    # 2. Load existing focus config
    focus_data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
    existing_keywords = {
        entry["keyword"]: entry for entry in focus_data["strategic_keywords"]
    }

    # 3. Update weights based on frequency analysis
    updated_count = 0
    for keyword, base_weight in BASE_WEIGHTS.items():
        freq = word_freq.get(keyword, 0)
        # Dynamic weight = base + frequency bonus (capped)
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
            updated_count += 1
            print(f"  + {keyword}: {new_weight} (new, freq={freq})")

    # 4. Write back
    FOCUS_PATH.write_text(
        json.dumps(focus_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ Strategic Focus calibrated: {updated_count} keywords updated at {FOCUS_PATH}")


if __name__ == "__main__":
    calibrate()
