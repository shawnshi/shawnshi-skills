"""Parent-side seal helper that cannot lose the supplement finalization clock.

Sealing a gap starts the packet's ``finalization.grace_seconds`` clock. The parent
must run the guarded ``finalize --parent`` inside that window; interleaving another
gap's broker work between the two steps is what loses it. This helper performs the
seal and, when the worker's dynamic draft is already on disk, the guarded parent
finalization immediately after it. When no draft exists yet it prints the exact
deadline instead of leaving the parent to recompute it later.

Usage::

  python -X utf8 scripts/supplement_seal.py --request <supplement_request.json> --gap-id <gap_id>
  python -X utf8 scripts/supplement_seal.py --request <supplement_request.json> --gap-id <gap_id> --report-only

Exit codes: 0 = seal succeeded (and finalization succeeded or was not yet possible),
2 = seal succeeded but the parent finalization failed, 1 = the seal itself failed.
The helper never rolls the ledger back and never authorizes a retry of a sealed gap.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from run_contract import RunContractError, file_sha256

SEALED = "sealed"


def _aware(value: str, label: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RunContractError(f"{label} is not timezone aware")
    return parsed.astimezone(timezone.utc)


def _seal_state(request_path: Path, gap_id: str) -> dict:
    from article_broker import evidence

    payload = evidence(request_path, gap_id)
    next_action = payload.get("next_action") or {}
    return {
        "sealed": next_action.get("action") == SEALED and bool(payload.get("completed_at")),
        "stop_eligible": bool(next_action.get("stop_eligible")),
        "stop_reason": next_action.get("stop_reason"),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "broker_evidence_sha256": payload.get("broker_evidence_sha256"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parent-only seal + immediate guarded parent finalization for one supplement gap."
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--gap-id", required=True)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Report the current seal state and remaining grace without mutating the ledger",
    )
    args = parser.parse_args(argv)

    from supplement_agent import _load_bound_packet, finalize_parent_draft

    request_path = args.request.resolve()
    _request_file, _request, packet, _gap, _lane_slice, _manifest = _load_bound_packet(
        request_path, args.gap_id
    )
    grace = int(packet["finalization"]["grace_seconds"])
    draft_path = Path(packet["output_paths"]["draft"])

    state = _seal_state(request_path, args.gap_id)
    result: dict = {"gap_id": args.gap_id, "grace_seconds": grace, "draft_path": str(draft_path)}

    if args.report_only:
        result["seal"] = state
        result["draft_present"] = draft_path.is_file()
        if state["sealed"] and state["completed_at"]:
            deadline = _aware(state["completed_at"], "completed_at") + timedelta(seconds=grace)
            result["grace_deadline"] = deadline.isoformat()
            result["remaining_seconds"] = round(
                (deadline - datetime.now(timezone.utc)).total_seconds(), 3
            )
        result["status"] = "reported"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if state["sealed"]:
        result["seal"] = state
    else:
        from article_broker import operate

        result["seal"] = operate(request_path, args.gap_id, "seal")
    sealed_state = _seal_state(request_path, args.gap_id)
    result["sealed_state"] = sealed_state
    completed_at = sealed_state.get("completed_at")
    if completed_at:
        deadline = _aware(completed_at, "completed_at") + timedelta(seconds=grace)
        result["grace_deadline"] = deadline.isoformat()
        result["remaining_seconds"] = round(
            (deadline - datetime.now(timezone.utc)).total_seconds(), 3
        )

    if not draft_path.is_file():
        result["status"] = "sealed_awaiting_draft"
        result["next_step"] = (
            "The worker must persist the dynamic draft at draft_path, then run "
            "finalize --parent before grace_deadline; do not start another gap's broker operation first."
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    try:
        output_path, assembly = finalize_parent_draft(request_path, args.gap_id)
    except (OSError, TypeError, ValueError, RunContractError) as exc:
        result["status"] = "sealed_finalization_failed"
        result["error"] = str(exc)
        result["next_step"] = (
            "Retry finalize --parent for this gap immediately (the deadline in grace_deadline still applies); "
            "if the deadline has passed, close the gap with review_progress_gate.py "
            "(--agent-status timed_out --review-kind supplement) and register the aggregate with "
            "run_daily.py reconcile-supplement --progress-state <state path>."
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result["status"] = "sealed_and_finalized"
    result["assembly"] = assembly
    result["draft_path"] = str(output_path)
    result["draft_sha256"] = file_sha256(output_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
