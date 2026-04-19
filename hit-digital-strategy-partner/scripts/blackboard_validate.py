import argparse
import json
import sys
from pathlib import Path

from blackboard import DEFAULT_WORKSPACE_ROOT, blackboard_path, load_state, validate_state


def main():
    parser = argparse.ArgumentParser(description="Validate strategy blackboard readiness")
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    path, state = load_state(args.workspace_root)
    report = validate_state(state)
    report["path"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and not report["ready"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
