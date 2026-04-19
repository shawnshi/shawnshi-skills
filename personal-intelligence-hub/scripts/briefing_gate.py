from __future__ import annotations

import argparse
from pathlib import Path

from hub_utils import load_json


def validate_briefing_data(data: dict) -> list[str]:
    errors = []
    punchline = (data.get("punchline") or "").strip()
    if not punchline or "[WAITING/ERROR]" in punchline:
        errors.append("missing valid punchline")

    action_levers = data.get("action_levers", [])
    if len(action_levers) < 3:
        errors.append("expected at least 3 action levers")

    top_10 = data.get("top_10", [])
    if not top_10 or len(top_10) > 10:
        errors.append("top_10 must contain 1-10 items")

    urls = [item.get("url") for item in top_10]
    if len(urls) != len(set(urls)):
        errors.append("top_10 contains duplicate urls")

    has_l4 = False
    for item in top_10:
        if not item.get("summary"):
            errors.append(f"missing summary for item: {item.get('title', 'unknown')}")
        level = item.get("intelligence_level")
        if level == "L4":
            has_l4 = True

    if has_l4 and not data.get("adversarial_audit"):
        errors.append("L4 items require adversarial_audit")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate intelligence briefing data.")
    parser.add_argument("json_path", help="Path to forged briefing json snapshot")
    args = parser.parse_args()

    path = Path(args.json_path)
    data = load_json(path, {})
    if not data:
        print(f"[FAIL] no json data found at {path}")
        return 1

    errors = validate_briefing_data(data)
    if errors:
        print("[FAIL] briefing gate blocked delivery")
        for error in errors:
            print(f"- {error}")
        return 1

    print("[PASS] briefing gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
