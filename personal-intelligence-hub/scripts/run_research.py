"""Read-only research feedback and explicit-manifest catalog. No learning writes."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import run_contract as rc
from run_progress import _verify_registered

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CATALOG_INPUTS = 128


def _json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise rc.RunContractError("research/catalog input exceeds 2 MiB")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise rc.RunContractError("research/catalog input must be an object")
    return value


def _count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise rc.RunContractError(f"invalid research counter: {label}")
    return value


def evaluate_run(path: str | Path) -> dict[str, Any]:
    manifest = rc.load_manifest(path)
    _verify_registered(manifest)
    artifacts, stages = manifest["artifacts"], manifest["stages"]
    request_record = artifacts.get("supplement_request")
    request = _json(Path(request_record["artifact_path"])) if request_record else {}
    stage = stages["supplemental"]
    aggregate = _json(Path(stage["artifact_path"])) if stage.get("artifact_path") else {}
    if aggregate and (aggregate.get("run_id") != manifest["run_id"] or aggregate.get("request_sha256") != (request_record or {}).get("artifact_sha256")):
        raise rc.RunContractError("research aggregate request/run binding mismatch")
    results = aggregate.get("results", [])
    if not isinstance(results, list):
        raise rc.RunContractError("research results must be a list")
    by_gap = {}
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("gap_id"), str):
            raise rc.RunContractError("research result identity is invalid")
        if result["gap_id"] in by_gap:
            raise rc.RunContractError("duplicate registered research gap")
        by_gap[result["gap_id"]] = result
    selected = set()
    semantic = stages["semantic_review"]
    if semantic.get("artifact_path"):
        receipt = _json(Path(semantic["artifact_path"]))
        if receipt.get("run_id") != manifest["run_id"] or receipt.get("review_kind") != "semantic":
            raise rc.RunContractError("research semantic receipt binding mismatch")
        for binding in receipt.get("lineage_bindings", []):
            for item in binding.get("inputs", []):
                selected.add((item["candidate_ref"], item["candidate_object_sha256"]))
    rows, feedback, distinct = [], [], set()
    declared = request.get("gaps", [])
    if not isinstance(declared, list):
        raise rc.RunContractError("research declared gaps must be a list")
    if set(by_gap) - {gap["gap_id"] for gap in declared}:
        raise rc.RunContractError("research result has undeclared gap")
    for gap in declared:
        result = by_gap.get(gap["gap_id"])
        if result is None:
            rows.append({"gap_id": gap["gap_id"], "lane": gap["lane"], "state": "unregistered", "candidates_returned": None, "selected_candidates": None, "verified_accesses": None})
            feedback.append({"gap_id": gap["gap_id"], "kind": "delivery_or_reconciliation_required", "note": "Unknown delivery is not a research negative; use original clocks and native evidence."})
            continue
        candidates = result.get("candidates", [])
        accesses = result.get("access_log", [])
        queries = result.get("executed_queries", [])
        decisions = result.get("bound_candidate_decisions", [])
        if any(not isinstance(value, list) for value in (candidates, accesses, queries, decisions)):
            raise rc.RunContractError("research funnel collection is invalid")
        versions = set()
        for candidate in candidates:
            ref, digest = candidate["candidate_id"], candidate["candidate_object_sha256"]
            if ref != rc.candidate_ref(candidate["url"]) or digest != rc.candidate_object_hash(candidate):
                raise rc.RunContractError("research candidate identity/object hash mismatch")
            versions.add((ref, digest))
        refs = {ref for ref, _ in versions}
        distinct.update(refs)
        coverage = result.get("coverage", {})
        counts = {name: _count(coverage[name], name) if name in coverage else None for name in ("attempted", "succeeded", "failed")}
        verified = sum(access.get("status") == "verified" for access in accesses)
        picked = len({ref for ref, _ in versions & selected}) if semantic.get("status") == "completed" else None
        rows.append({"gap_id": gap["gap_id"], "lane": gap["lane"], "state": result["status"],
            "recorded_queries": len(queries), "bound_candidate_decisions": len(decisions),
            "access_receipts": len(accesses), "verified_accesses": verified, "transport_counters": counts,
            "candidates_returned": len(refs), "selected_candidates": picked,
            "selection_rate": picked / len(refs) if picked is not None and refs else None})
        if result["status"] in {"degraded", "degraded_timeout", "blocked", "failed"} or (counts["failed"] or 0) > 0:
            feedback.append({"gap_id": gap["gap_id"], "kind": "verification_or_infrastructure_gap", "note": "Separate access/transport failures from lack of relevant events; no budget extension implied."})
        elif result["status"] == "no_increment":
            feedback.append({"gap_id": gap["gap_id"], "kind": "registered_no_increment", "note": "A bounded registered negative is not proof that the topic has no news."})
        elif refs and picked == 0:
            feedback.append({"gap_id": gap["gap_id"], "kind": "selection_review", "note": "Returned candidates were not selected; inspect relevance and duplication, do not auto-adjust weights."})
    from collection_quality import source_diagnostics, reading_diagnostics
    baseline_record = stages["baseline"]
    baseline = _json(Path(baseline_record["artifact_path"])) if baseline_record.get("artifact_path") else {}
    core_path = Path(manifest["run_dir"]) / "refined_core.json"
    core = {}
    if semantic.get("status") == "completed" and core_path.is_file():
        if rc.file_sha256(core_path) != receipt.get("output_sha256"):
            raise rc.RunContractError("research refined core bytes changed")
        core = _json(core_path)
    telemetry = manifest.get("telemetry", {})
    measured = telemetry.get("executions", {})
    usage_status = "partial_registered_usage" if measured else "unmeasured"
    return {"contract_version": "research-evaluation/1.0", "mode": "read_only", "run_id": manifest["run_id"],
        "strategic_coverage": source_diagnostics(baseline), "reading_coverage": reading_diagnostics(core),
        "usage": {"measurement_status": usage_status, "registered_invocations": len(measured),
                  "registered_summary": telemetry.get("summary"), "complete_task_cost": None},
        "baseline_coverage": stages["baseline"].get("metadata", {}).get("coverage"),
        "supplement_evaluation_state": stage["status"], "aggregate_registered": bool(aggregate),
        "gaps": rows, "distinct_returned_candidates": len(distinct) if aggregate else None, "feedback": feedback,
        "quality_scope": "Registered transport/byte bindings and selection counts only; novelty, correctness and semantic entailment are not scored.",
        "automatic_policy_changes": False, "source_clock_extension": False}


def catalog(paths: list[str | Path]) -> dict[str, Any]:
    """Metadata index only. Explicit paths; no directory/session/history scan."""
    if not paths or len(paths) > MAX_CATALOG_INPUTS:
        raise rc.RunContractError("catalog requires 1..128 explicit manifests")
    rows, errors, seen = [], [], set()
    for raw in paths:
        path = Path(raw).resolve()
        if path in seen:
            errors.append({"manifest_path": str(path), "error": "duplicate input path"})
            continue
        seen.add(path)
        try:
            value = _json(path)
            if value.get("contract_version") != "1.0" or not isinstance(value.get("run_id"), str) or not value["run_id"]:
                raise rc.RunContractError("unsupported catalog manifest identity/format")
            created = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
            if created.utcoffset() is None:
                raise rc.RunContractError("catalog creation time requires timezone")
            stages = value["stages"]
            statuses = {stage: stages[stage]["status"] for stage in rc.STAGE_ORDER}
            if any(status not in rc.STAGE_FINAL | {"pending", "running"} for status in statuses.values()):
                raise rc.RunContractError("unknown catalog stage status")
            rows.append({"manifest_path": str(path), "run_id": value["run_id"], "report_date": value["report_date"],
                "created_at": created.isoformat(), "recorded_stage_statuses": statuses,
                "linked_from_run_id": value.get("linked_from_run_id"), "bundle_sha256": value.get("skill_bundle_sha256"),
                "validation": "metadata_only", "completion_verified": False, "launch_permission": False,
                "usage_measurement": "partial_registered_usage" if value.get("telemetry", {}).get("executions") else "unmeasured"})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append({"manifest_path": str(path), "error": str(exc)})
    rows.sort(key=lambda row: datetime.fromisoformat(row["created_at"]), reverse=True)
    successors = {}
    for row in rows:
        if row["linked_from_run_id"]:
            successors.setdefault(row["linked_from_run_id"], []).append(row["run_id"])
    for row in rows:
        row["superseded_by"] = successors.get(row["run_id"], [])
        archived = row["recorded_stage_statuses"].get("archive") == "completed"
        row["lifecycle_observation"] = ("archive_recorded" if archived else "linked_successor_recorded" if row["superseded_by"] else "unfinished_requires_inspection")
    counts = Counter(row["run_id"] for row in rows)
    return {"contract_version": "run-catalog/1.0", "mode": "read_only", "status": "partial" if errors else "complete",
        "rows": rows, "errors": errors, "duplicate_run_ids": sorted(key for key, count in counts.items() if count > 1),
        "note": "Recorded metadata is not validated completion or native state; use each original frozen CLI and its guards for execution."}
