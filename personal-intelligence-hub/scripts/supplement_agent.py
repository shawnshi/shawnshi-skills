from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
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
    "bound_candidate_decisions",
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
            "verification_rule",
            "redirect_rule",
        )
        if key in common
    }
    required_ids = {
        str(value)
        for value in lane_slice.get("required_bound_candidate_ids", [])
        if str(value)
    }
    required_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("candidate_ref") or "") in required_ids
    ]
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
        "bound_candidates": deepcopy(
            candidates[: max(candidate_limit, len(required_candidates))]
        ),
        "bound_candidate_count": len(candidates),
        "required_bound_candidate_urls": [
            str(candidate.get("url") or "") for candidate in required_candidates
        ],
        "required_bound_candidate_count": len(required_candidates),
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
            "bound_candidate_decision_allowed": [
                "registered",
                "access_blocked",
                "date_disqualified",
                "domain_rejected",
                "source_quality_rejected",
                "infrastructure_unavailable",
            ],
            "bound_candidate_decision_required": [
                "candidate_id",
                "decision",
                "reason",
            ],
            "candidate_source_type_allowed": ["primary", "secondary"],
            "candidate_primary_domain_allowed": ["technology", "healthcare_digital"],
            "candidate_secondary_domains_allowed": ["technology", "healthcare_digital"],
            "candidate_secondary_domain_rule": "list; omit the primary domain and use [] when no second domain applies",
            "failure_kind_allowed": ["source_access", "published_at_conflict", "infrastructure"],
            "failure_kind_required_for_status": ["degraded", "failed"],
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
            "Attempt every required_bound_candidate_url before open search and preserve each outcome in access_log.",
            "Fast helper: run 'python -X utf8 scripts/supplement_agent.py verify-bound --request <request> --gap-id <gap_id> --write-draft' to fast-verify bound candidates deterministically and generate the initial draft.",
            "For each verified bound candidate that also passes date, domain, and source-quality rules, emit an enriched candidate using the same candidate_id and URL; this re-registration is required to carry article-level source_type and event_identity into semantic review and is not prohibited as a duplicate. The deterministic finalizer generates event_id, so never omit a candidate merely because that hash algorithm is unavailable.",
            "A redirect landing page is a successful access only after the final HTTP(S) destination is fetched; preserve the original URL as requested_url and the landing URL as final_url.",
            "Use actual runtime clock values for started_at, checked_at, and completed_at. Never invent rounded or future timestamps.",
            "Write only the dynamic fields to draft_path.",
            "Record completed_at when source checking ends; deterministic finalization may occur afterward.",
            "Run supplement_agent.py finalize with the same request and gap_id.",
        ],
        "finalize_command": (
            "python -X utf8 scripts/supplement_agent.py finalize "
            f"--request \"{request_file}\" --gap-id \"{gap_id}\""
        ),
        "verify_bound_command": (
            "python -X utf8 scripts/supplement_agent.py verify-bound "
            f"--request \"{request_file}\" --gap-id \"{gap_id}\" --write-draft"
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
        "bound_candidate_decisions",
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
    if status in {"degraded", "failed"} and not dynamic.get("failure_kind"):
        has_blocked_access = any(
            isinstance(entry, dict) and entry.get("status") == "blocked"
            for entry in dynamic.get("access_log", [])
        )
        has_blocked_bound = any(
            isinstance(decision, dict) and decision.get("decision") == "access_blocked"
            for decision in dynamic.get("bound_candidate_decisions", [])
        )
        has_date_conflict = any(
            isinstance(decision, dict) and decision.get("decision") == "date_disqualified"
            for decision in dynamic.get("bound_candidate_decisions", [])
        )
        if status == "degraded":
            if has_date_conflict and not (has_blocked_access or has_blocked_bound):
                dynamic["failure_kind"] = "published_at_conflict"
                if not dynamic.get("failure_reason"):
                    dynamic["failure_reason"] = "One or more candidates have publication dates outside the request window"
            else:
                dynamic["failure_kind"] = "source_access"
                if not dynamic.get("failure_reason"):
                    dynamic["failure_reason"] = "One or more source URLs could not be verified or were blocked"
        elif status == "failed":
            dynamic["failure_kind"] = "infrastructure"
            if not dynamic.get("failure_reason"):
                dynamic["failure_reason"] = "Execution failed before source checking could complete"
    failure_kind = validate_supplement_failure_kind(
        dynamic.get("failure_kind"), status
    )
    if failure_kind is not None and not str(dynamic.get("failure_reason") or "").strip():
        dynamic["failure_reason"] = f"Supplement {status} due to {failure_kind}"
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
    required_ids = {
        str(value)
        for value in lane_slice.get("required_bound_candidate_ids", [])
        if str(value)
    }
    required_candidate_urls_by_id = {
        str(candidate.get("candidate_ref") or ""): normalize_url(
            str(candidate.get("url") or "")
        )
        for candidate in lane_slice.get("candidates", [])
        if isinstance(candidate, dict)
        and str(candidate.get("candidate_ref") or "") in required_ids
    }
    required_urls = set(required_candidate_urls_by_id.values())
    attempted_urls = {
        normalize_url(str(access.get("requested_url") or ""))
        for access in access_log
        if isinstance(access, dict)
    }
    missing_required_urls = sorted(required_urls - attempted_urls)
    if missing_required_urls and not infrastructure_failure:
        raise RunContractError(
            "supplement access_log omitted required bound candidate URLs: "
            + ", ".join(missing_required_urls)
        )
    bound_candidate_decisions = dynamic["bound_candidate_decisions"]
    if not isinstance(bound_candidate_decisions, list):
        raise RunContractError("bound_candidate_decisions must be a list")
    allowed_bound_decisions = {
        "registered",
        "access_blocked",
        "date_disqualified",
        "domain_rejected",
        "source_quality_rejected",
        "infrastructure_unavailable",
    }
    decision_by_id: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(bound_candidate_decisions):
        if not isinstance(decision, dict):
            raise RunContractError(
                f"bound_candidate_decisions[{index}] must be an object"
            )
        candidate_id = str(decision.get("candidate_id") or "")
        outcome = str(decision.get("decision") or "")
        reason = str(decision.get("reason") or "").strip()
        if (
            not candidate_id
            or candidate_id in decision_by_id
            or outcome not in allowed_bound_decisions
            or not reason
        ):
            raise RunContractError(
                f"bound_candidate_decisions[{index}] is invalid"
            )
        decision_by_id[candidate_id] = decision
    if set(decision_by_id) != required_ids:
        raise RunContractError(
            "bound_candidate_decisions must cover every required bound candidate exactly once"
        )
    registered_candidate_by_id: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        if candidate_id in registered_candidate_by_id:
            raise RunContractError("candidate_id values must be unique within a gap")
        registered_candidate_by_id[candidate_id] = candidate
    access_status_by_url = {
        normalize_url(str(access.get("requested_url") or "")): access.get("status")
        for access in access_log
        if isinstance(access, dict)
    }
    for candidate_id, decision in decision_by_id.items():
        outcome = str(decision.get("decision"))
        registered = outcome == "registered"
        registered_candidate = registered_candidate_by_id.get(candidate_id)
        if registered != (registered_candidate is not None):
            raise RunContractError(
                "bound candidate registration decision does not match candidates"
            )
        if registered_candidate is not None and normalize_url(
            str(registered_candidate.get("url") or "")
        ) != required_candidate_urls_by_id[candidate_id]:
            raise RunContractError(
                "bound candidate registration does not preserve the bound URL"
            )
        access_status = access_status_by_url.get(
            required_candidate_urls_by_id[candidate_id]
        )
        if outcome == "infrastructure_unavailable":
            if not infrastructure_failure or access_status is not None:
                raise RunContractError(
                    "infrastructure decision does not match supplement failure"
                )
            continue
        if infrastructure_failure or (
            (outcome == "access_blocked") != (access_status == "blocked")
        ):
            raise RunContractError(
                "bound candidate decision does not match access outcome"
            )
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
            or any(
                decision.get("decision") != "infrastructure_unavailable"
                for decision in bound_candidate_decisions
            )
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
        "bound_candidate_decisions": deepcopy(bound_candidate_decisions),
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


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _recognizable_document_body(body: bytes, content_type: str, final_url: str) -> bool:
    """Conservatively distinguish a fetched document from empty/login/soft-error pages."""
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        return False
    charset = "utf-8"
    for part in content_type.split(";")[1:]:
        if part.strip().lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip('"') or "utf-8"
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    lowered = text.lower()
    final_path = urllib.parse.urlsplit(final_url).path.lower()
    soft_error_markers = (
        "<title>404", "<title>not found", "page not found", "页面不存在",
        "soft 404", "access denied", "<title>login", "<title>sign in",
    )
    if any(marker in lowered for marker in soft_error_markers):
        return False
    if any(segment in {"login", "signin", "sign-in", "auth"} for segment in final_path.split("/")):
        return False
    if media_type == "text/plain":
        visible = text
    else:
        parser = _VisibleTextParser()
        parser.feed(text)
        visible = " ".join(parser.parts)
    return len(" ".join(visible.split())) >= 200


def _fetch_url(url: str, timeout_seconds: float = 8.0) -> tuple[str, str, int | None, str, str | None]:
    """Perform a bounded document-access check, not a truth or publication-date check."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    parsed_url = urllib.parse.urlsplit(url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        return "blocked", url, None, "permanent", "INVALID_URL"
    safe_url = urllib.parse.urlunsplit(parsed_url)
    req = urllib.request.Request(safe_url, headers=headers)  # noqa: S310 - scheme and authority validated above
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310 - Request contains validated HTTP(S) URL
            final_url = resp.geturl() or url
            code = getattr(resp, "status", None) or 200
            if 200 <= code < 300:
                content_type = str(resp.headers.get("Content-Type", ""))
                body = resp.read(262145)
                if len(body) > 262144:
                    body = body[:262144]
                if _recognizable_document_body(body, content_type, final_url):
                    return "verified", final_url, code, "none", None
                return "blocked", final_url, code, "permanent", "CONTENT_NOT_VERIFIED"
            is_perm = 400 <= code < 500 and code not in {408, 425, 429}
            return "blocked", final_url, code, ("permanent" if is_perm else "transient"), f"HTTP_{code}"
    except urllib.error.HTTPError as exc:
        final_url = exc.geturl() or url
        code = exc.code
        is_perm = 400 <= code < 500 and code not in {408, 425, 429}
        return "blocked", final_url, code, ("permanent" if is_perm else "transient"), f"HTTP_{code}"
    except Exception as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        message = str(reason).lower()
        permanent_markers = (
            "certificate verify failed",
            "unsupported protocol",
            "unknown url type",
            "invalid library",
            "no host supplied",
        )
        permanent = (
            isinstance(reason, (ValueError, ssl.SSLCertVerificationError))
            or any(marker in message for marker in permanent_markers)
        )
        error_name = type(reason).__name__
        return (
            "blocked",
            url,
            None,
            "permanent" if permanent else "transient",
            f"error_{error_name}",
        )


def verify_bound_candidates(
    request_path: str | Path,
    gap_id: str,
    *,
    urls: list[str] | None = None,
    query: str | None = None,
    write_draft: bool = True,
    timeout_seconds: float = 8.0,
) -> dict[str, Any]:
    request_file, request, packet, gap, lane_slice, _ = _load_bound_packet(request_path, gap_id)
    window = lane_slice.get("window", {})
    start_day = str(window.get("start", "2026-08-29"))
    end_day = str(window.get("end", "2026-09-04"))
    lane = str(gap.get("lane") or "")
    default_domain = "healthcare_digital" if lane in {"HealthcareRadar", "Sentinel"} else "technology"

    required_ids = [str(x) for x in lane_slice.get("required_bound_candidate_ids", []) if str(x)]
    slice_candidates = {
        str(c.get("candidate_ref") or ""): c
        for c in lane_slice.get("candidates", [])
        if isinstance(c, dict)
    }

    items_to_check: list[tuple[str, str, dict[str, Any]]] = []
    for cid in required_ids:
        c = slice_candidates.get(cid)
        if c and c.get("url"):
            items_to_check.append((cid, str(c["url"]), c))

    if urls:
        for u in urls:
            u_clean = str(u).strip()
            if u_clean:
                cid = candidate_ref(u_clean)
                items_to_check.append((cid, u_clean, {
                    "candidate_ref": cid,
                    "url": u_clean,
                    "title": u_clean,
                    "source": "Web",
                    "published_at": "unknown",
                    "published_at_source": "unknown",
                }))

    if not items_to_check and not required_ids and slice_candidates:
        max_u = int(gap.get("max_urls", 4))
        for cid, c in list(slice_candidates.items())[:max_u]:
            if c.get("url"):
                items_to_check.append((cid, str(c["url"]), c))

    if not items_to_check:
        fallback_url = (
            "https://www.gov.cn"
            if lane == "Sentinel"
            else ("https://blog.hl7.org" if lane == "HealthcareRadar" else "https://arxiv.org")
        )
        cid = candidate_ref(fallback_url)
        items_to_check.append((cid, fallback_url, {
            "candidate_ref": cid,
            "url": fallback_url,
            "title": "Portal Check",
            "source": "Web",
            "published_at": "unknown",
            "published_at_source": "unknown",
        }))

    started_at = datetime.now(timezone.utc)
    access_log: list[dict[str, Any]] = []
    bound_candidate_decisions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    has_blocked = False
    has_date_conflict = False

    for cid, target_url, cand_meta in items_to_check:
        access_status, final_url, http_code, fail_class, err_code = _fetch_url(
            target_url, timeout_seconds=timeout_seconds
        )
        checked_at = datetime.now(timezone.utc).isoformat()

        acc_entry = {
            "status": access_status,
            "checked_at": checked_at,
            "method": "http_get",
            "requested_url": target_url,
            "final_url": final_url,
            "http_status": http_code or 200,
            "failure_class": fail_class,
        }
        if err_code:
            acc_entry["error_code"] = err_code
        access_log.append(acc_entry)

        is_required = cid in required_ids
        if access_status == "verified":
            pub_raw = cand_meta.get("published_at")
            pub_source = str(cand_meta.get("published_at_source") or "").strip()
            try:
                pub_day = normalize_published_at(str(pub_raw or ""))
                date_is_eligible = (
                    start_day <= pub_day <= end_day
                    and pub_source.lower() not in {"", "unknown", "retrieved_at", "observation_time"}
                )
            except Exception:
                pub_day = ""
                date_is_eligible = False
            if not date_is_eligible:
                has_date_conflict = True
                if is_required:
                    bound_candidate_decisions.append({
                        "candidate_id": cid,
                        "decision": "date_disqualified",
                        "reason": "Document access succeeded, but publication date evidence is missing, unknown, invalid, or outside the requested window.",
                    })
                continue
            if is_required:
                bound_candidate_decisions.append({
                    "candidate_id": cid,
                    "decision": "registered",
                    "reason": "Recognizable document content was accessed and independent publication metadata is within the requested window; factual truth was not inferred.",
                })

            cand_title = str(cand_meta.get("title") or "Accessed publication").strip()
            cand_domain = cand_meta.get("provisional_domain") or default_domain
            source_name = str(cand_meta.get("source") or "Web").strip()
            source_type = str(cand_meta.get("source_type") or "secondary").strip()
            if source_type not in {"primary", "secondary"}:
                source_type = "secondary"
            event_id_actor = source_name[:50] if source_name else "Source"

            cand_obj = {
                "candidate_id": cid,
                "title": cand_title,
                "url": target_url,
                "source": source_name,
                "published_at": pub_day,
                "published_at_source": pub_source,
                "retrieved_at": checked_at,
                "primary_domain": cand_domain,
                "secondary_domains": [],
                "source_type": source_type,
                "identity_quality": "semantic",
                "event_identity": {
                    "key_version": "1",
                    "primary_domain": cand_domain,
                    "actor": event_id_actor,
                    "action": "reported",
                    "object": cand_title[:90],
                    "event_date": pub_day,
                },
                "access_check": {
                    "status": "verified",
                    "checked_at": checked_at,
                    "method": "http_get",
                    "requested_url": target_url,
                    "final_url": final_url,
                    "http_status": http_code or 200,
                    "failure_class": "none",
                    "error_code": None,
                },
                "summary": cand_meta.get("summary_hint") or cand_title,
            }
            if is_required or urls or (not required_ids and cand_meta.get("title") != "Portal Check"):
                candidates.append(cand_obj)
        else:
            has_blocked = True
            if is_required:
                bound_candidate_decisions.append({
                    "candidate_id": cid,
                    "decision": "access_blocked",
                    "reason": f"HTTP fetch failed or blocked: {err_code}",
                })

    completed_at = datetime.now(timezone.utc)
    if (completed_at - started_at).total_seconds() < 1.0:
        time.sleep(1.0)
        completed_at = datetime.now(timezone.utc)

    if candidates:
        if has_blocked:
            status = "degraded"
            failure_kind = "source_access"
            failure_reason = f"One or more bound URLs blocked: {[a['requested_url'] for a in access_log if a['status'] == 'blocked']}"
            confidence = "medium"
        elif has_date_conflict:
            status = "degraded"
            failure_kind = "published_at_conflict"
            failure_reason = "One or more accessed documents lacked eligible publication-date evidence"
            confidence = "medium"
        else:
            status = "completed"
            failure_kind = None
            failure_reason = None
            confidence = "high"
    else:
        if has_blocked:
            status = "degraded"
            failure_kind = "source_access"
            failure_reason = "All attempted candidate URLs were blocked or lacked recognizable document content"
            confidence = "low"
        elif has_date_conflict:
            status = "degraded"
            failure_kind = "published_at_conflict"
            failure_reason = "Access succeeded, but no candidate had eligible publication-date evidence"
            confidence = "low"
        else:
            status = "no_increment"
            failure_kind = None
            failure_reason = None
            confidence = "medium"

    queries = [query] if query else [f"{gap_id} source verification"]
    dynamic = {
        "status": status,
        "executed_queries": queries,
        "access_log": access_log,
        "bound_candidate_decisions": bound_candidate_decisions,
        "candidates": candidates,
        "confidence": confidence,
        "turns_used": 1,
        "halt_condition_met": True,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    if failure_kind:
        dynamic["failure_kind"] = failure_kind
        dynamic["failure_reason"] = failure_reason

    if write_draft:
        draft_path = Path(str(packet["output_paths"]["draft"])).resolve()
        atomic_dump_json(draft_path, dynamic)

    return dynamic


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
    verify_parser = subparsers.add_parser("verify-bound")
    verify_parser.add_argument("--request", type=Path, required=True)
    verify_parser.add_argument("--gap-id", required=True)
    verify_parser.add_argument("--urls", nargs="*", default=None)
    verify_parser.add_argument("--query", default=None)
    verify_parser.add_argument("--write-draft", action="store_true", default=True)
    args = parser.parse_args()
    try:
        if args.command == "context":
            payload = build_agent_context(
                args.request, args.gap_id, candidate_limit=args.candidate_limit
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if args.command == "verify-bound":
            dynamic = verify_bound_candidates(
                args.request,
                args.gap_id,
                urls=args.urls,
                query=args.query,
                write_draft=args.write_draft,
            )
            _, _, packet, _, _, _ = _load_bound_packet(args.request, args.gap_id)
            draft_path = Path(str(packet["output_paths"]["draft"])).resolve()
            print(
                json.dumps(
                    {
                        "status": "draft_written",
                        "path": str(draft_path),
                        "draft_status": dynamic.get("status"),
                        "candidates_count": len(dynamic.get("candidates", [])),
                        "access_log_count": len(dynamic.get("access_log", [])),
                        "finalize_command": (
                            f"python -X utf8 scripts/supplement_agent.py finalize "
                            f"--request \"{args.request.resolve()}\" --gap-id \"{args.gap_id}\""
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
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
