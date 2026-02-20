"""
<!-- Standard Header -->
@Input: C:\Users\shich\.gemini\pai\memory.md
@Output: references/strategic_focus.json
@Pos: Phase 0 (Calibration Phase)
@Maintenance Protocol: Logic Refinement rules must sync SKILL.md.
"""
import os
import json
import re
from collections import Counter

MEMORY_PATH = r"C:\Users\shich\.gemini\pai\memory.md"
FOCUS_PATH = os.path.join(os.path.dirname(__file__), "..", "references", "strategic_focus.json")

def calibrate():
    if not os.path.exists(MEMORY_PATH):
        print(f"Error: {MEMORY_PATH} not found.")
        return

    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract sections: Strategic North Star, Task Radar, Strategic Axioms
    # Basic keyword extraction using simple regex (can be improved)
    # Target: 2-4 letter medical/tech terms (MSL, ACE, HITL, VBC, AI, RAG, etc.)
    keywords = re.findall(r'\b[A-Z]{2,}\b', content)
    
    # Also pick up some specific lowercase keywords related to current campaigns
    lower_targets = ["medical", "agent", "hospital", "clinic", "fhir", "drg", "vibe"]
    for word in lower_targets:
        if word in content.lower():
            keywords.extend([word.upper()] * 5) # Weight them more

    counts = Counter(keywords)
    top_keywords = counts.most_common(20)

    # Standard weights (10-15 for high priority, 5-8 for low)
    strategic_keywords = []
    for kw, count in top_keywords:
        weight = 10 if count > 5 else 8
        strategic_keywords.append({"keyword": kw.lower(), "weight": weight})

    # Ensure our "Battles of the Year" are always included if they appear at all
    essential = ["msl", "ace", "hitl", "vbc"]
    for e in essential:
        if any(e == sk['keyword'] for sk in strategic_keywords):
            # Boost weight
            for sk in strategic_keywords:
                if sk['keyword'] == e:
                    sk['weight'] = 15
        elif e in content.lower():
            strategic_keywords.append({"keyword": e, "weight": 12})

    # Re-structure categories loosely
    new_focus = {
        "strategic_keywords": strategic_keywords,
        "categories": {
            "AI/ML & Agentic Mesh": ["agent", "ace", "ai", "vector", "rag", "llm", "vibe"],
            "医疗数字化/MSL": ["medical", "msl", "fhir", "drg", "hospital", "clinic", "healthit", "himss", "ajmc", "hit180"],
            "工程与底层架构": ["github", "architecture", "rust", "go", "performance", "dns", "tailscale", "browser"]
        }
    }

    with open(FOCUS_PATH, "w", encoding="utf-8") as f_focus:
        json.dump(new_focus, f_focus, ensure_ascii=False, indent=2)
    
    print(f"Strategic Focus calibrated: {FOCUS_PATH}")
    print(f"Top keywords: {', '.join([k[0] for k in top_keywords[:10]])}")

if __name__ == "__main__":
    calibrate()
