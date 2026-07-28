from __future__ import annotations

import argparse
import json
from pathlib import Path

from briefing_gate import validate_briefing_data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only validation of refined intelligence JSON."
    )
    parser.add_argument("input_json")
    args = parser.parse_args()
    path = Path(args.input_json)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] could not read JSON: {exc}")
        return 2
    errors, warnings = validate_briefing_data(data)
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        print("[FAIL] refined JSON does not match briefing_schema.json")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"[PASS] valid and unchanged: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
