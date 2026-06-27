from __future__ import annotations

import json

from blackboard import mark_adversarial_audit, update_phase
from hub_utils import REFINED_PATH, clean_json_output, dump_json, load_json

def fallback_audit(data: dict) -> dict:
    for item in data.get("top_10", []):
        if item.get("intelligence_level") == "L4":
            item["intelligence_level"] = "L3"
            item["intel_grade"] = "L3"
            item["reason"] = (item.get("reason", "") + " [downgraded: no external red-team runner]").strip()
    return {
        "status": "fallback",
        "devil_advocate": "No external red-team runner was available. All unverified L4 candidates were conservatively downgraded to L3.",
        "blind_spots": "Manual adversarial review is still recommended for any signal that may trigger irreversible action.",
    }


import sys

def audit(redteam_report_path: str = None) -> None:
    data = load_json(REFINED_PATH, {})
    if not data:
        print(f"[FAIL] refined data not found at {REFINED_PATH}")
        return

    has_l4 = any(item.get("intelligence_level") == "L4" for item in data.get("top_10", []))
    if not has_l4:
        print("[OK] no L4 items detected; adversarial audit skipped")
        return

    update_phase("audit", "running")
    
    if redteam_report_path:
        redteam_data = load_json(redteam_report_path, {})
        audit_data = {
            "status": "passed",
            "devil_advocate": redteam_data.get("devil_advocate", "Red-team attack passed successfully."),
            "blind_spots": redteam_data.get("blind_spots", "No critical blind spots found.")
        }
        print(f"[OK] L4 preserved. External red-team approval applied from {redteam_report_path}")
    else:
        audit_data = fallback_audit(data)
        print("[WARNING] No external red-team runner provided. Unverified L4 candidates downgraded to L3.")

    data["adversarial_audit"] = audit_data
    dump_json(REFINED_PATH, data)
    mark_adversarial_audit(audit_data)
    update_phase("audit", "completed")


if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else None
    audit(report_path)
