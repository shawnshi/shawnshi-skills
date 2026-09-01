from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from history_manager import generate_event_id, normalize_url
from hub_utils import atomic_dump_json, load_json
from run_contract import (
    RunContractError,
    candidate_object_hash,
    candidate_ref,
    canonical_json_bytes,
    file_sha256,
    load_manifest,
    normalize_published_at,
    validate_supplement_failure_kind,
    _validate_access_log_entry,
    _validate_supplement_candidate,
)


CONTEXT_VERSION = "supplement-agent-context/1.0"
DYNAMIC_FIELDS = {
    "status",
    "failure_kind",
    "failure_reason",
    "executed_queries",
    "access_log",
    "candidates",
    "confidence",
    "turns_used",
    "halt_condition_met",
    "started_at",
    "completed_at",
}


def _aware_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RunContractError(f"{field} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RunContractError(f"{field} must be timezone-aware")
    return parsed


def _load_bound_packet(
    request_path: str | Path,
    gap_id: str,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    request_file = Path(request_path).resolve()
    request = load_json(request_file, {})
    if request.get("contract_version") != "supplement-request/1.1":
        raise RunContractError("supplement agent requires request 1.1")
    if not gap_id:
        raise RunContractError("gap_id is required")
    gaps = {
        str(gap.get("gap_id") or ""): gap
        for gap in request.get("gaps", [])
        if isinstance(gap, dict)
    }
    gap = gaps.get(gap_id)
    if gap is None:
        raise RunContractError("gap_id is not registered")
    packets = [
        packet
        for packet in request.get("execution_packets", [])
        if isinstance(packet, dict)
        and packet.get("assigned_gap_ids") == [gap_id]
    ]
    if len(packets) != 1:
        raise RunContractError("gap execution packet is missing or duplicated")
    packet = packets[0]
    manifest_path = Path(str(packet.get("run_manifest_path") or "")).resolve()
    manifest = load_manifest(manifest_path)
    if request.get("run_id") != manifest.get("run_id"):
        raise RunContractError("supplement request run_id mismatch")
    request_record = manifest.get("artifacts", {}).get("supplement_request")
    if (
        not isinstance(request_record, dict)
        or Path(str(request_record.get("artifact_path") or "")).resolve() != request_file
        or request_record.get("artifact_sha256") != file_sha256(request_file)
    ):
        raise RunContractError("supplement request does not match the registered artifact")
    if request.get("baseline_sha256") != manifest.get("stages", {}).get("baseline", {}).get("artifact_sha256"):
        raise RunContractError("supplement request baseline binding mismatch")
    candidate_record = manifest.get("artifacts", {}).get("candidate_pool")
    if (
        not isinstance(candidate_record, dict)
        or request.get("candidate_pool_sha256") != candidate_record.get("artifact_sha256")
    ):
        raise RunContractError("supplement request candidate binding mismatch")
    prompt_path = Path(str(packet.get("prompt_config_path") or "")).resolve()
    if not prompt_path.is_file() or packet.get("prompt_config_sha256") != file_sha256(prompt_path):
        raise RunContractError("supplement prompt config binding mismatch")
    prompt_config = load_json(prompt_path, {})
    lane_binding = packet.get("lane_slice")
    if not isinstance(lane_binding, dict) or lane_binding != (packet.get("bound_input_paths") or {}).get("lane_slice"):
        raise RunContractError("supplement lane slice binding is invalid")
    lane_path = Path(str(lane_binding.get("path") or "")).resolve()
    if not lane_path.is_file() or lane_binding.get("sha256") != file_sha256(lane_path):
        raise RunContractError("supplement lane slice bytes changed")
    lane_slice = load_json(lane_path, {})
    if (
        lane_slice.get("contract_version") != "supplement-lane-slice/1.0"
        or lane_slice.get("run_id") != manifest.get("run_id")
        or lane_slice.get("gap") != gap
        or lane_slice.get("candidate_pool_sha256") != request.get("candidate_pool_sha256")
    ):
        raise RunContractError("supplement lane slice binding mismatch")
    output_paths = packet.get("output_paths")
    authorization = packet.get("write_authorization")
    if not isinstance(output_paths, dict) or not isinstance(authorization, dict):
        raise RunContractError("supplement output authorization is invalid")
    draft_path = Path(str(output_paths.get("draft") or "")).resolve()
    allowed = [Path(str(value)).resolve() for value in authorization.get("agent_allowed_paths", [])]
    if authorization.get("forbid_other_writes") is not True or allowed != [draft_path]:
        raise RunContractError("supplement draft authorization mismatch")
    return request_file, request, packet, gap, lane_slice, prompt_config


def build_agent_context(
    request_path: str | Path,
    gap_id: str,
    *,
    candidate_limit: int = 6,
) -> dict[str, Any]:
    if not 1 <= candidate_limit <= 20:
        raise RunContractError("candidate_limit must be between 1 and 20")
    request_file, request, packet, gap, lane_slice, prompt_config = _load_bound_packet(
        request_path, gap_id
    )
    lane = str(gap["lane"])
    role = (prompt_config.get("supplement_agents") or {}).get(lane)
    common = prompt_config.get("common_contract")
    if not isinstance(role, dict) or not isinstance(common, dict):
        raise RunContractError("supplement role contract is missing")
    candidates = lane_slice.get("candidates")
    if not isinstance(candidates, list):
        raise RunContractError("supplement lane candidates are invalid")
    selected_rules = {
        key: common[key]
        for key in (
            "evidence_rule",
            "identity_rule",
            "date_rule",
            "stop_rule",
            "empty_rule",
            "coverage_rule",
            "failure_rule",
        )
        if key in common
    }
    draft_path = Path(str(packet["output_paths"]["draft"])).resolve()
    return {
        "contract_version": CONTEXT_VERSION,
        "run_id": request["run_id"],
        "request_path": str(request_file),
        "request_sha256": file_sha256(request_file),
        "gap": deepcopy(gap),
        "window": deepcopy(lane_slice["window"]),
        "lane": lane,
        "role": {
            "role": role.get("role"),
            "mission": role.get("mission"),
            "system_prompt": role.get("system_prompt"),
        },
        "rules": selected_rules,
        "bound_candidates": deepcopy(candidates[:candidate_limit]),
        "bound_candidate_count": len(candidates),
        "draft_path": str(draft_path),
        "draft_dynamic_fields": sorted(DYNAMIC_FIELDS),
        "draft_schema": {
            "status_allowed": ["completed", "no_increment", "degraded", "failed"],
            "confidence_allowed": ["high", "medium", "low"],
            "halt_condition_met_type": "boolean",
            "access_log_required": [
                "status",
                "checked_at",
                "method",
                "requested_url",
                "final_url",
                "http_status",
                "failure_class",
            ],
            "access_status_allowed": ["verified", "blocked"],
            "access_method_allowed": ["http_get", "browser", "api", "document"],
            "verified_access": "failure_class=none; error_code must be null, empty, or omitted",
            "blocked_access": "failure_class=transient|permanent; non-empty error_code required",
            "candidate_source_type_allowed": ["primary", "secondary"],
            "candidate_primary_domain_allowed": ["technology", "healthcare_digital"],
            "candidate_secondary_domains_allowed": ["technology", "healthcare_digital"],
            "candidate_secondary_domain_rule": "list; omit the primary domain and use [] when no second domain applies",
            "candidate_required": [
                "title",
                "url",
                "source",
                "published_at",
                "published_at_source",
                "retrieved_at",
                "primary_domain",
                "secondary_domains",
                "source_type",
                "identity_quality",
                "event_identity",
                "access_check",
                "summary",
            ],
        },
        "draft_instructions": [
            "Write only the dynamic fields to draft_path.",
            "Record completed_at when source checking ends; deterministic finalization may occur afterward.",
            "Run supplement_agent.py finalize with the same request and gap_id.",
        ],
        "finalize_command": (
            "python -X utf8 scripts/supplement_agent.py finalize "
            f"--request \"{request_file}\" --gap-id \"{gap_id}\""
        ),
    }


def assemble_result(
    request_path: str | Path,
    gap_id: str,
    dynamic: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    request_file, request, packet, gap, lane_slice, _ = _load_bound_packet(request_path, gap_id)
    if not isinstance(dynamic, dict):
        raise RunContractError("supplement dynamic draft must be an object")
    extra = sorted(set(dynamic) - DYNAMIC_FIELDS)
    if extra:
        raise RunContractError(f"supplement dynamic draft has forbidden fields: {extra}")
    required = {
        "status",
        "executed_queries",
        "access_log",
        "candidates",
        "confidence",
        "turns_used",
        "halt_condition_met",
        "started_at",
        "completed_at",
    }
    missing = sorted(required - set(dynamic))
    if missing:
        raise RunContractError(f"supplement dynamic draft missing fields: {missing}")
    started_at = _aware_datetime(dynamic["started_at"], "started_at")
    completed_at = _aware_datetime(dynamic["completed_at"], "completed_at")
    request_started_at = _aware_datetime(request["created_at"], "request.created_at")
    if started_at < request_started_at or completed_at < started_at:
        raise RunContractError("source-checking timestamps are outside the request window")
    if completed_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise RunContractError("completed_at cannot be in the future")
    if (completed_at - started_at).total_seconds() > int(gap["max_duration_seconds"]):
        raise RunContractError("source-checking duration exceeds execution budget")
    status = dynamic["status"]
    if status not in {"completed", "no_increment", "degraded", "failed"}:
        raise RunContractError("supplement dynamic draft status is invalid")
    failure_kind = validate_supplement_failure_kind(
        dynamic.get("failure_kind"), status
    )
    if failure_kind is not None and not str(dynamic.get("failure_reason") or "").strip():
        raise RunContractError("supplement failure_kind requires failure_reason")
    infrastructure_failure = failure_kind == "infrastructure"
    queries = dynamic["executed_queries"]
    if (
        not isinstance(queries, list)
        or (not queries and not infrastructure_failure)
        or any(not str(query).strip() for query in queries)
        or len(queries) > int(gap["max_queries"])
    ):
        raise RunContractError("supplement dynamic draft queries are invalid")
    access_log = deepcopy(dynamic["access_log"])
    candidates = deepcopy(dynamic["candidates"])
    if (
        not isinstance(access_log, list)
        or not isinstance(candidates, list)
        or (not access_log and not infrastructure_failure)
        or len(access_log) > int(gap["max_urls"])
    ):
        raise RunContractError("access_log or candidates are invalid")
    validated_access = [
        _validate_access_log_entry(
            access,
            index,
            require_machine_classification=True,
        )
        for index, access in enumerate(access_log)
    ]
    for index, evidence in enumerate(validated_access):
        checked_at = _aware_datetime(evidence[1], f"access_log[{index}].checked_at")
        if checked_at < started_at.astimezone(timezone.utc) or checked_at > completed_at.astimezone(timezone.utc):
            raise RunContractError(f"access_log[{index}].checked_at is outside source-checking time")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise RunContractError(f"candidate {index} must be an object")
        identity = candidate.get("event_identity")
        if not isinstance(identity, dict):
            raise RunContractError(f"candidate {index} requires event_identity")
        candidate["published_at"] = normalize_published_at(
            candidate.get("published_at"), f"candidate {index}.published_at"
        )
        try:
            candidate["event_id"] = generate_event_id(identity)
        except ValueError as exc:
            raise RunContractError(f"candidate {index} event_identity is invalid") from exc
        access = candidate.get("access_check")
        if not isinstance(access, dict) or normalize_url(str(access.get("requested_url") or "")) != normalize_url(str(candidate.get("url") or "")):
            raise RunContractError(f"candidate {index} access_check does not match url")
        candidate_evidence = _validate_supplement_candidate(
            candidate,
            index,
            lane_slice["window"],
            request_started_at,
            completed_at,
        )
        if candidate_evidence not in validated_access:
            raise RunContractError(f"candidate {index} access_check is absent from access_log")
        candidate["candidate_id"] = candidate_ref(str(candidate["url"]))
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
    succeeded = sum(1 for item in access_log if isinstance(item, dict) and item.get("status") == "verified")
    failed = sum(1 for item in access_log if isinstance(item, dict) and item.get("status") == "blocked")
    if succeeded + failed != len(access_log):
        raise RunContractError("access_log contains an invalid status")
    if status in {"completed", "no_increment"} and failed:
        raise RunContractError(
            "successful supplement status cannot contain failed coverage"
        )
    turns_used = dynamic["turns_used"]
    halt_condition_met = dynamic["halt_condition_met"]
    confidence = dynamic["confidence"]
    if confidence not in {"high", "medium", "low"}:
        raise RunContractError("supplement dynamic draft confidence is invalid")
    if infrastructure_failure:
        if (
            turns_used != 0
            or queries
            or access_log
            or candidates
            or halt_condition_met is not False
            or not str(dynamic.get("failure_reason") or "").strip()
        ):
            raise RunContractError("infrastructure failure draft is inconsistent")
    elif (
        not isinstance(turns_used, int)
        or isinstance(turns_used, bool)
        or not 1 <= turns_used <= int(gap["max_turns"])
        or not isinstance(halt_condition_met, bool)
    ):
        raise RunContractError("supplement dynamic draft turn or halt state is invalid")
    if status in {"completed", "no_increment"} and halt_condition_met is not True:
        raise RunContractError("terminal supplement draft must meet the halt condition")
    if status == "completed" and not candidates:
        raise RunContractError("completed supplement draft requires candidates")
    if status in {"no_increment", "failed"} and candidates:
        raise RunContractError(f"{status} supplement draft cannot contain candidates")
    result = {
        "contract_version": "supplement-result/1.0",
        "run_id": request["run_id"],
        "request_sha256": file_sha256(request_file),
        "baseline_sha256": request["baseline_sha256"],
        "candidate_pool_sha256": request["candidate_pool_sha256"],
        "gap_id": gap_id,
        "lane": gap["lane"],
        "status": dynamic["status"],
        "executed_queries": deepcopy(dynamic["executed_queries"]),
        "access_log": access_log,
        "candidates": candidates,
        "coverage": {
            "attempted": len(access_log),
            "succeeded": succeeded,
            "failed": failed,
        },
        "confidence": confidence,
        "data_provenance": {
            "request_sha256": file_sha256(request_file),
            "candidate_pool_sha256": request["candidate_pool_sha256"],
            "access_log_sha256": hashlib.sha256(canonical_json_bytes(access_log)).hexdigest(),
        },
        "turns_used": turns_used,
        "halt_condition_met": halt_condition_met,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    if str(dynamic.get("failure_reason") or "").strip():
        result["failure_reason"] = dynamic["failure_reason"]
    draft_path = Path(str(packet["output_paths"]["draft"])).resolve()
    atomic_dump_json(draft_path, result)
    return draft_path, result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a supplement packet, emit compact agent context, and deterministically assemble its draft."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--request", type=Path, required=True)
    context_parser.add_argument("--gap-id", required=True)
    context_parser.add_argument("--candidate-limit", type=int, default=6)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--request", type=Path, required=True)
    finalize_parser.add_argument("--gap-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "context":
            payload = build_agent_context(
                args.request, args.gap_id, candidate_limit=args.candidate_limit
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        _, _, packet, _, _, _ = _load_bound_packet(args.request, args.gap_id)
        draft_path = Path(str(packet["output_paths"]["draft"])).resolve()
        dynamic = load_json(draft_path, {})
        output_path, _ = assemble_result(args.request, args.gap_id, dynamic)
        print(
            json.dumps(
                {
                    "status": "draft_ready",
                    "path": str(output_path),
                    "sha256": file_sha256(output_path),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, TypeError, ValueError, RunContractError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
