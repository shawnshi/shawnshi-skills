#!/usr/bin/env python3
"""Roll one daily run into a single actionable-readiness verdict.

Read-only by construction: the roll-up consumes artifacts a run already produced
(or did not produce) and never re-fetches, re-judges or re-writes them.  The point
is that "the run finished" and "the run established that acting is defensible" are
two different claims, and the second one has to be *derived* from artifacts and
its gaps named.

Two kinds of prerequisite are kept apart:

* machine prerequisites -- decidable from the run's own artifacts (run status,
  quote coverage, provider outcomes, Thesis evaluation, market session, gate
  verdict);
* human gates -- depend on account rules and a cost model that live outside the
  run, so no artifact can close them.  They are always listed as pending.

A ``ready_for_human_review`` verdict therefore means "every machine-checkable
prerequisite holds and the remaining gates are named"; it is never an order, and
the payload says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pia_report  # noqa: E402

VERSION = "pia_readiness_rollup_v1"
STATUS_READY = "ready_for_human_review"
STATUS_NOT_READY = "not_ready"
STATUS_FAILED = "failed"


def load_run_artifacts(
    run_dir: Path,
) -> tuple[dict[str, dict[str, Any] | None], dict[str, Any] | None]:
    """Read the artifacts a roll-up judges, from the run directory alone.

    Shared by the standalone route and the orchestrator so both judge exactly the
    same bytes: a composition that loaded artifacts differently could disagree
    with ``pia.py readiness`` on the same run.
    """
    artifacts = {key: pia_report.load_json(run_dir / relative)
                 for key, relative in pia_report.ARTIFACTS}
    assessment = pia_report.load_json(run_dir / pia_report.READINESS_ARTIFACT)
    return artifacts, assessment


def build_rollup(run_dir: Path, artifacts: dict[str, dict[str, Any] | None],
                 assessment: dict[str, Any] | None) -> dict[str, Any]:
    summary = artifacts.get("daily_run_summary") or {}
    declared = pia_report.declared_scopes(artifacts)
    conflicts = pia_report.scope_conflict(declared)
    scope, scope_source = pia_report.resolve_scope(declared)
    readiness = pia_report.readiness_summary(artifacts, assessment, scope)
    residual = summary.get("residual_unknowns")
    residual_declared = isinstance(residual, list)
    consistency = summary.get("status_consistency")

    machine_rows = [row for row in readiness["prerequisites"]
                    if row["prerequisite"] not in pia_report.HUMAN_GATE_PREREQUISITES]
    human_gates = [row["prerequisite"] for row in readiness["prerequisites"]
                   if row["prerequisite"] in pia_report.HUMAN_GATE_PREREQUISITES]

    blockers: list[str] = []
    if scope == pia_report.SCOPE_UNKNOWN:
        blockers.append("run artifacts declare no decision scope")
    blockers.extend(conflicts)
    if summary.get("status") != "complete":
        blockers.append(f"run status is {summary.get('status')!r}, not 'complete'")
    if isinstance(consistency, dict) and consistency.get("consistent") is False:
        blockers.append("run status is inconsistent with its stage statuses")
    if not residual_declared:
        blockers.append("residual unknowns were not declared by the run")
    blockers.extend(f"unmet machine prerequisite: {row['prerequisite']} "
                    f"[{row['evidence']}]"
                    for row in machine_rows if row["verified"] is not True)

    status = STATUS_READY if not blockers else STATUS_NOT_READY
    return {
        "schema_version": VERSION,
        "status": status,
        "detail_status": ("machine_prerequisites_verified_human_gates_pending"
                          if status == STATUS_READY else "actionable_prerequisites_unmet"),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "decision_scope": scope,
        "decision_scope_source": scope_source,
        "declared_scopes": declared,
        "scope_conflicts": conflicts,
        "run_status": summary.get("status"),
        "run_detail_status": summary.get("detail_status"),
        "status_consistency": consistency,
        "run_inventory": summary.get("run_inventory"),
        "residual_unknowns": residual if residual_declared else None,
        "residual_unknowns_declared": residual_declared,
        "machine_prerequisites": machine_rows,
        "human_gates": human_gates,
        "blockers": blockers,
        "actionable_readiness": readiness,
        "gate_artifact": pia_report.READINESS_ARTIFACT,
        "gate_artifact_present": isinstance(assessment, dict),
        "non_executable": True,
        "statement": (
            "这一结论说明本轮已建立的机器可核验前置条件；它不构成下单授权，"
            "执行仍为 human_review_required_no_order"
        ),
    }


def invalid(run_dir: Path, detail: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": VERSION,
        "status": STATUS_FAILED,
        "detail_status": detail,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "errors": [message],
        "non_executable": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive a single actionable-readiness verdict from an existing run")
    parser.add_argument("--run-dir", required=True,
                        help="task directory whose out/ artifacts are rolled up")
    parser.add_argument("--out", default=None,
                        help="optional path for the JSON roll-up; the run is not modified")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        payload = invalid(run_dir, "run_dir_missing", f"not a directory: {run_dir}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3

    summary_path = run_dir / "out" / "daily_run_summary.json"
    if not summary_path.is_file():
        payload = invalid(run_dir, "run_summary_missing",
                          f"no run summary at {summary_path}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3

    artifacts, assessment = load_run_artifacts(run_dir)
    payload = build_rollup(run_dir, artifacts, assessment)
    if payload["scope_conflicts"]:
        payload = {**payload, "status": STATUS_FAILED,
                   "detail_status": "decision_scope_conflict"}

    if args.out:
        target = Path(args.out).expanduser().resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        except OSError as exc:
            failure = invalid(run_dir, "rollup_write_failed", str(exc))
            print(json.dumps(failure, ensure_ascii=False, indent=2))
            return 3
        payload = {**payload, "rollup_file": str(target)}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] == STATUS_READY:
        return 0
    if payload["status"] == STATUS_NOT_READY:
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
