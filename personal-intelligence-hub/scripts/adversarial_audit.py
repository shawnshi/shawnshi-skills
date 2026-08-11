from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_contract import RunContractError, validate_review_receipt


def validate_red_team_receipt(
    manifest_path: str | Path,
    refined_path: str | Path,
    receipt_path: str | Path,
) -> dict:
    path = Path(receipt_path)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunContractError(f"cannot read red-team receipt: {exc}") from exc
    if not isinstance(receipt, dict):
        raise RunContractError("red-team receipt must be a JSON object")
    validate_review_receipt(
        receipt,
        manifest_path,
        refined_path,
        expected_kind="red_team",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only validation of a bound red-team receipt."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--refined", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = validate_red_team_receipt(args.manifest, args.refined, args.receipt)
    except RunContractError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] red-team receipt is valid and unchanged: {args.receipt}")
    print(f"[INFO] status={receipt['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
