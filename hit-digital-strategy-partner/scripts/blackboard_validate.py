import argparse
import json
import sys
from pathlib import Path

from blackboard import load_state, validate_state


def main():
    parser = argparse.ArgumentParser(description="Validate strategy blackboard readiness")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
