from __future__ import annotations

import json

from blackboard import mark_adversarial_audit, update_phase
from hub_utils import REFINED_PATH, clean_json_output, dump_json, has_llm_runner, load_json, run_llm

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


def audit() -> None:
    data = load_json(REFINED_PATH, {})
    if not data:
        print(f"[FAIL] refined data not found at {REFINED_PATH}")
        return

    has_l4 = any(item.get("intelligence_level") == "L4" for item in data.get("top_10", []))
    if not has_l4:
        print("[OK] no L4 items detected; adversarial audit skipped")
        return

    update_phase("audit", "running")
    if not has_llm_runner():
        audit_data = fallback_audit(data)
        data["adversarial_audit"] = audit_data
        dump_json(REFINED_PATH, data)
        mark_adversarial_audit(audit_data)
        update_phase("audit", "completed")
        print("[OK] fallback adversarial audit applied")
        return

    prompt = (
        "请以红队视角审查以下情报 JSON，返回 JSON，字段为 devil_advocate 和 blind_spots。\n"
        + json.dumps(data.get("top_10", []), ensure_ascii=False, indent=2)
    )
    try:
        raw_output = run_llm(prompt)
        try:
            audit_data = clean_json_output(raw_output)
        except Exception as e:
            print(f"[WARN] LLM JSON parsing failed in audit: {e}. Raw output:\n{raw_output[:500]}...")
            audit_data = fallback_audit(data)
    except Exception:
        audit_data = fallback_audit(data)

    data["adversarial_audit"] = audit_data
    dump_json(REFINED_PATH, data)
    mark_adversarial_audit(audit_data)
    update_phase("audit", "completed")
    print("[OK] adversarial audit written")


if __name__ == "__main__":
    audit()
