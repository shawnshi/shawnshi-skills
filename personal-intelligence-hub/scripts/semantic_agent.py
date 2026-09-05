from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from history_manager import generate_event_id, load_recent_history, match_history, normalize_url
from hub_utils import atomic_dump_json, load_json
from mix_policy import major_signal_eligible, select_candidates_with_mix
from run_contract import (
    RunContractError,
    candidate_object_hash,
    file_sha256,
    finalize_semantic_decision,
    load_manifest,
    normalize_published_at,
    normalize_supplement_failure_kind,
)


CONTEXT_VERSION = "semantic-agent-context/1.0"
DYNAMIC_VERSION = "semantic-dynamic/1.0"
IDENTITY_FIELDS = {
    "key_version",
    "primary_domain",
    "actor",
    "action",
    "object",
    "event_date",
}
DYNAMIC_FIELDS = {
    "contract_version",
    "status",
    "turns_used",
    "halt_condition_met",
    "punchline",
    "insights",
    "digest",
    "market",
    "action_levers",
    "selected_items",
}
ITEM_FIELDS = {
    "candidate_id",
    "title_zh",
    "event_identity",
    "fact",
    "connection",
    "deduction",
    "actionability",
    "intelligence_level",
    "confidence",
    "summary_zh",
    "major_signal",
    "major_signal_reason",
    "near_term_decision_impact",
    "decision_impact_reason",
}
ACTION_FIELDS = {"domain", "task", "owner_type", "trigger", "indicator"}


def _bound_artifact(
    request: dict[str, Any],
    name: str,
) -> tuple[Path, dict[str, Any]]:
    record = (request.get("bound_artifacts") or {}).get(name)
    if not isinstance(record, dict):
        raise RunContractError(f"semantic bound artifact is missing: {name}")
    path = Path(str(record.get("path") or "")).resolve()
    if not path.is_file() or file_sha256(path) != record.get("sha256"):
        raise RunContractError(f"semantic bound artifact changed: {name}")
    return path, load_json(path, {})


def _load_packet(
    request_path: str | Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    request_file = Path(request_path).resolve()
    request = load_json(request_file, {})
    if (
        request.get("contract_version") != "review-request/1.1"
        or request.get("review_kind") != "semantic"
    ):
        raise RunContractError("semantic review request is invalid")
    packet = request.get("execution_packet")
    if not isinstance(packet, dict):
        raise RunContractError("semantic execution packet is missing")
    manifest_path = Path(str(packet.get("run_manifest_path") or "")).resolve()
    manifest = load_manifest(manifest_path)
    record = manifest.get("artifacts", {}).get("semantic_review_request")
    if (
        not isinstance(record, dict)
        or Path(str(record.get("artifact_path") or "")).resolve() != request_file
        or record.get("artifact_sha256") != file_sha256(request_file)
    ):
        raise RunContractError("semantic review request is not registered")
    if manifest.get("run_id") != request.get("run_id"):
        raise RunContractError("semantic request run_id mismatch")
    helper = packet.get("agent_helper")
    helper_path = Path(str((helper or {}).get("path") or "")).resolve()
    if (
        helper_path != Path(__file__).resolve()
        or file_sha256(helper_path) != (helper or {}).get("sha256")
    ):
        raise RunContractError("semantic helper binding changed")
    prompt = packet.get("prompt_config")
    prompt_path = Path(str((prompt or {}).get("path") or "")).resolve()
    if not prompt_path.is_file() or file_sha256(prompt_path) != (prompt or {}).get("sha256"):
        raise RunContractError("semantic prompt binding changed")
    for name in request.get("bound_artifacts", {}):
        _bound_artifact(request, str(name))
    return request_file, request, packet, manifest


def _access_projection(access: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(access[key])
        for key in (
            "status",
            "checked_at",
            "method",
            "requested_url",
            "final_url",
            "http_status",
        )
        if key in access
    }


def _source_type(candidate: dict[str, Any]) -> str:
    claimed = candidate.get("source_type")
    if claimed in {"primary", "secondary"}:
        return str(claimed)
    url = normalize_url(str(candidate.get("url") or ""))
    source = str(candidate.get("source") or "").lower()
    if "arxiv.org/" in url or "research" in source or "journal" in source:
        return "primary"
    return "secondary"


def _date_failure_disqualifies(result: dict[str, Any]) -> bool:
    return (
        normalize_supplement_failure_kind(result.get("failure_kind"))
        == "published_at_conflict"
    )


def _candidate_event_id(candidate: dict[str, Any]) -> str:
    identity = candidate.get("event_identity")
    if isinstance(identity, dict):
        try:
            return generate_event_id(identity)
        except ValueError:
            return ""
    value = str(candidate.get("event_id") or "")
    return value if value.startswith("evt1_") else ""


def _source_identity(candidate: dict[str, Any]) -> str:
    normalized = normalize_url(str(candidate.get("url") or ""))
    host = str(urlsplit(normalized).hostname or "").casefold()
    if host:
        return f"host:{host}"
    source = str(candidate.get("source") or "").strip().casefold()
    return f"source:{source}"


def _candidate_projection(
    entry: dict[str, Any],
    *,
    candidate_refs: list[str],
    corroboration_status: str,
) -> dict[str, Any]:
    candidate = entry["candidate"]
    source_type = _source_type(candidate)
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_refs": candidate_refs,
        "title": candidate.get("title"),
        "url": candidate.get("url"),
        "source": candidate.get("source"),
        "published_at": normalize_published_at(candidate.get("published_at")),
        "published_at_source": candidate.get("published_at_source"),
        "primary_domain": str(
            candidate.get("primary_domain")
            or candidate.get("provisional_domain")
            or ""
        ),
        "secondary_domains": deepcopy(
            candidate.get("secondary_domains")
            or candidate.get("provisional_secondary_domains")
            or []
        ),
        "source_type": source_type,
        "corroboration_status": corroboration_status,
        "summary": str(
            candidate.get("summary") or candidate.get("summary_hint") or ""
        ).strip(),
        "suggested_event_identity": deepcopy(candidate.get("event_identity")),
        "access_check": _access_projection(entry["access_check"]),
    }


def _candidate_assessment(
    request: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    _, pool = _bound_artifact(request, "candidate_pool")
    _, supplement = _bound_artifact(request, "supplement")
    history_path, _ = _bound_artifact(request, "history_snapshot")
    verified_access: dict[str, dict[str, Any]] = {}
    date_disqualified_urls: set[str] = set()
    results = supplement.get("results")
    if not isinstance(results, list):
        raise RunContractError("semantic supplement results are invalid")
    for result in results:
        if not isinstance(result, dict):
            continue
        date_disqualified = _date_failure_disqualifies(result)
        for access in result.get("access_log", []):
            if not isinstance(access, dict) or access.get("status") != "verified":
                continue
            for raw_url in (access.get("requested_url"), access.get("final_url")):
                normalized = normalize_url(str(raw_url or ""))
                if normalized:
                    verified_access.setdefault(normalized, deepcopy(access))
                    if date_disqualified:
                        date_disqualified_urls.add(normalized)

    entries: list[dict[str, Any]] = []
    # Prefer the article-level supplement projection when it re-registers a
    # heuristic candidate. The untouched pool record remains an explicit
    # duplicate disposition so funnel conservation is preserved.
    for result in results:
        if not isinstance(result, dict):
            continue
        for candidate in result.get("candidates", []):
            if isinstance(candidate, dict):
                normalized_url = normalize_url(str(candidate.get("url") or ""))
                access = candidate.get("access_check")
                entries.append(
                    {
                        "candidate": deepcopy(candidate),
                        "access_check": access if isinstance(access, dict) else None,
                        "date_disqualified": normalized_url in date_disqualified_urls,
                    }
                )
    for candidate in pool.get("items", []):
        if isinstance(candidate, dict):
            normalized_url = normalize_url(str(candidate.get("url") or ""))
            entries.append(
                {
                    "candidate": deepcopy(candidate),
                    "access_check": verified_access.get(normalized_url),
                    "date_disqualified": normalized_url in date_disqualified_urls,
                }
            )

    report_clock = datetime.combine(
        date.fromisoformat(str(manifest["report_date"])),
        time.max,
        tzinfo=ZoneInfo(str(manifest["timezone"])),
    )
    history_record = manifest.get("artifacts", {}).get("history_snapshot", {})
    recent_history = load_recent_history(
        days=int(history_record.get("metadata", {}).get("dedupe_days", 7)),
        now=report_clock,
        path=history_path,
    )
    eligible: list[dict[str, Any]] = []
    dispositions: list[dict[str, str]] = []
    pending_secondary: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for entry in entries:
        candidate = entry["candidate"]
        candidate_id = str(candidate.get("candidate_id") or "")
        disposition = {
            "candidate_id": candidate_id or "missing",
            "url": str(candidate.get("url") or ""),
            "source_type": _source_type(candidate),
            "reason": "eligible",
        }
        dispositions.append(disposition)
        if not candidate_id:
            disposition["reason"] = "missing_candidate_id"
            continue
        if candidate_id in seen:
            disposition["reason"] = "duplicate_candidate_id"
            continue
        seen.add(candidate_id)
        claimed_hash = str(candidate.get("candidate_object_sha256") or "")
        if claimed_hash != candidate_object_hash(candidate):
            raise RunContractError("semantic candidate hash is invalid")
        if entry["date_disqualified"]:
            disposition["reason"] = "published_at_conflict"
            continue
        access = entry.get("access_check")
        if not isinstance(access, dict) or access.get("status") != "verified":
            disposition["reason"] = "missing_verified_access"
            continue
        history_probe = {
            "url": candidate.get("url"),
            "title": candidate.get("title"),
            "source": candidate.get("source"),
            "published_at": candidate.get("published_at"),
        }
        if match_history(history_probe, entries=recent_history, now=report_clock).get("redundant"):
            disposition["reason"] = "historical_duplicate"
            continue
        try:
            normalize_published_at(candidate.get("published_at"))
        except RunContractError:
            disposition["reason"] = "invalid_published_at"
            continue
        primary_domain = str(
            candidate.get("primary_domain")
            or candidate.get("provisional_domain")
            or ""
        )
        if primary_domain not in {"technology", "healthcare_digital"}:
            disposition["reason"] = "unsupported_domain"
            continue
        if disposition["source_type"] == "primary":
            eligible.append(
                _candidate_projection(
                    entry,
                    candidate_refs=[candidate_id],
                    corroboration_status="single_primary",
                )
            )
            continue
        event_id = _candidate_event_id(candidate)
        if not event_id:
            disposition["reason"] = "secondary_without_independent_corroboration"
            continue
        pending_secondary.setdefault(event_id, []).append(
            {"entry": entry, "disposition": disposition}
        )

    for group in pending_secondary.values():
        independent = {_source_identity(value["entry"]["candidate"]) for value in group}
        if len(group) < 2 or len(independent) < 2:
            for value in group:
                value["disposition"]["reason"] = (
                    "secondary_without_independent_corroboration"
                )
            continue
        canonical = group[0]["entry"]
        refs = [
            str(value["entry"]["candidate"].get("candidate_id") or "")
            for value in group
        ]
        eligible.append(
            _candidate_projection(
                canonical,
                candidate_refs=refs,
                corroboration_status="multi_independent",
            )
        )
    return eligible, dispositions


def _eligible_candidates(
    request: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    eligible, _ = _candidate_assessment(request, manifest)
    return eligible


def build_agent_context(request_path: str | Path) -> dict[str, Any]:
    request_file, request, packet, manifest = _load_packet(request_path)
    eligible = _eligible_candidates(request, manifest)
    dynamic_path = Path(str((packet.get("draft_paths") or {}).get("dynamic") or "")).resolve()
    if dynamic_path not in {
        Path(str(value)).resolve() for value in packet.get("write_scope", [])
    }:
        raise RunContractError("semantic dynamic draft is not authorized")
    return {
        "contract_version": CONTEXT_VERSION,
        "run_id": request["run_id"],
        "request_path": str(request_file),
        "request_sha256": file_sha256(request_file),
        "window": deepcopy(manifest["window"]),
        "topic": manifest["topic"],
        "region": manifest["region"],
        "requested_ratio": deepcopy(manifest["mix_request"]["requested_ratio"]),
        "max_turns": request["max_turns"],
        "halt_condition": request["halt_condition"],
        "eligible_candidates": eligible,
        "eligible_candidate_count": len(eligible),
        "dynamic_draft_path": str(dynamic_path),
        "dynamic_contract": {
            "contract_version": DYNAMIC_VERSION,
            "required_top_level_fields": sorted(DYNAMIC_FIELDS),
            "status": "passed",
            "turns_used": f"integer 1..{request['max_turns']}",
            "halt_condition_met": True,
            "action_lever_required_fields": sorted(ACTION_FIELDS),
            "selected_item_required_fields": sorted(ITEM_FIELDS),
            "event_identity_exact_fields": sorted(IDENTITY_FIELDS),
            "intelligence_level_allowed": ["L1", "L2", "L3", "L4"],
            "confidence_allowed": ["high", "medium", "low"],
            "selection_rule": "Select only candidate_id values from eligible_candidates; every exposed item is either a registered primary source or a secondary-source event group with at least two independent candidate_refs. Weak supply may yield fewer than 10 items.",
            "top_level_text_fields": ["punchline", "insights", "digest", "market"],
            "text_rule": "Every text field must be one non-empty natural-language string; insights is not a list, and actionability must describe an action rather than a rating word.",
        },
        "instructions": [
            "Review only eligible_candidates; do not read baseline, history, candidate pool, supplement, schema, old runs, or script source.",
            "Write only the semantic-dynamic object to dynamic_draft_path.",
            "Use one semantic event_identity per selected candidate; event_date and primary_domain must match its registered evidence.",
            "After writing, stop analysis and run finalize_command exactly.",
        ],
        "finalize_command": " ".join(str(value) for value in (packet["agent_helper"]["finalize_command"])),
    }


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise RunContractError(f"semantic dynamic {field} must be a string")
    text = value.strip()
    if not text:
        raise RunContractError(f"semantic dynamic {field} is required")
    return text


def _coverage(manifest: dict[str, Any], supplement: dict[str, Any]) -> dict[str, Any]:
    baseline_stage = manifest["stages"]["baseline"]
    baseline = baseline_stage["metadata"]["coverage"]
    supplement_coverage = supplement.get("coverage") or {}
    attempted = int(baseline["source_attempted"]) + int(supplement_coverage.get("attempted", 0))
    succeeded = int(baseline["source_succeeded"]) + int(supplement_coverage.get("succeeded", 0))
    failed = int(baseline["source_failed"]) + int(supplement_coverage.get("failed", 0))
    failures: set[str] = set()
    raw_results = supplement.get("results")
    results: list[Any] = []
    if isinstance(raw_results, list):
        results.extend(raw_results)
    supplemental_candidates = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        result_coverage = result.get("coverage") or {}
        if result.get("status") in {"degraded", "failed"} or int(result_coverage.get("failed", 0)) > 0:
            failures.add(str(result.get("lane")))
        if isinstance(result.get("candidates"), list):
            supplemental_candidates += len(result["candidates"])
    run_status = "degraded" if baseline_stage.get("status") == "degraded" or manifest["stages"]["supplemental"].get("status") == "degraded" else "complete"
    denominator = int(baseline["raw_candidates"]) + supplemental_candidates
    reasons = sorted(str(value) for value in baseline.get("reasons", []) if str(value))
    reasons.extend(f"supplement lane degraded: {lane}" for lane in sorted(failures))
    return {
        "run_status": run_status,
        "coverage_confidence": "medium" if run_status == "degraded" else "high",
        "baseline_status": baseline_stage.get("status"),
        "source_attempted": attempted,
        "source_succeeded": succeeded,
        "source_failed": failed,
        "source_success_rate": succeeded / attempted if attempted else 0.0,
        "dated_candidate_rate": (
            (int(baseline["dated_candidates"]) + supplemental_candidates) / denominator
            if denominator
            else 0.0
        ),
        "required_lane_failures": sorted(failures),
        "reasons": reasons,
    }


def _candidate_funnel(
    pool: dict[str, Any],
    supplemental_count: int,
    eligible: list[dict[str, Any]],
    selected_candidate_ids: set[str],
    dispositions: list[dict[str, str]],
) -> dict[str, Any]:
    baseline = pool["candidate_funnel"]
    fixed = {
        str(key): int(value)
        for key, value in baseline["terminal_dispositions"].items()
        if key != "retained_for_review"
    }
    downstream = int(baseline["retained_for_review"]) + supplemental_count
    if len(dispositions) != downstream:
        raise RunContractError("semantic candidate dispositions do not cover registered supply")
    selected_groups = {
        str(candidate["candidate_id"]): [str(value) for value in candidate["candidate_refs"]]
        for candidate in eligible
        if str(candidate["candidate_id"]) in selected_candidate_ids
    }
    selected_ref_owner = {
        reference: canonical
        for canonical, references in selected_groups.items()
        for reference in references
    }
    final_dispositions: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()
    for record in dispositions:
        finalized = deepcopy(record)
        candidate_id = str(finalized["candidate_id"])
        if finalized["reason"] == "eligible":
            owner = selected_ref_owner.get(candidate_id)
            if owner is None:
                finalized["reason"] = "semantic_not_selected"
            elif owner == candidate_id:
                finalized["reason"] = "retained"
            else:
                finalized["reason"] = "semantic_duplicate"
        reason_counts[finalized["reason"]] += 1
        final_dispositions.append(finalized)
    retained = reason_counts.pop("retained", 0)
    semantic_duplicate = reason_counts.pop("semantic_duplicate", 0)
    if retained != len(selected_candidate_ids):
        raise RunContractError("semantic retained dispositions do not match selected items")
    below_quality_gate = sum(reason_counts.values())
    fixed.update(
        {
            "semantic_duplicate": semantic_duplicate,
            "below_quality_gate": below_quality_gate,
            "semantic_capacity": 0,
            "red_team_rejected": 0,
            "retained": retained,
        }
    )
    return {
        "observed": int(baseline["observed"]) + supplemental_count,
        "terminal_dispositions": fixed,
        "quality_gate_reasons": dict(sorted(reason_counts.items())),
        "candidate_dispositions": final_dispositions,
    }


def _mix(manifest: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    mix_request = manifest["mix_request"]
    _, mix = select_candidates_with_mix(
        items,
        len(items),
        {
            "default_ratio": deepcopy(mix_request["schema_default_ratio"]),
            "requested_ratio": deepcopy(mix_request["requested_ratio"]),
            "ratio_source": mix_request["ratio_source"],
            "ratio_reason": mix_request["ratio_reason"],
            "max_ratio_shift": mix_request.get("max_ratio_shift", 0.2),
        },
    )
    return mix


def _data_gaps(
    supplement: dict[str, Any],
    mix: dict[str, Any],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for result in supplement.get("results", []):
        if not isinstance(result, dict):
            continue
        coverage = result.get("coverage") or {}
        failed = int(coverage.get("failed", 0))
        if result.get("status") not in {"degraded", "failed"} and failed == 0:
            continue
        gap_id = str(result.get("gap_id") or "supplement-coverage")
        lane = str(result.get("lane") or "supplement")
        gaps.append(
            {
                "gap_id": gap_id,
                "lane": lane,
                "status": "open",
                "description": f"补检车道状态为 {result.get('status')}，并保留 {failed} 条受阻访问。",
                "impact": "该车道的事件供给与结论覆盖置信度降低。",
            }
        )
    supply = mix.get("supply_exception") or {}
    if supply.get("applied") is True:
        missing = "、".join(str(value) for value in supply.get("missing_domains", []))
        gaps.append(
            {
                "gap_id": "verified-domain-supply",
                "lane": "SemanticEvaluator",
                "status": "open",
                "description": f"登记且已核验的候选供给不足，未达到请求比例：{missing}。",
                "impact": "正式条目领域比例偏离请求比例，不以弱证据补数。",
            }
        )
    return gaps


def assemble_and_finalize(
    request_path: str | Path,
    dynamic: dict[str, Any],
) -> tuple[Path, Path]:
    _, request, packet, manifest = _load_packet(request_path)
    if not isinstance(dynamic, dict) or set(dynamic) != DYNAMIC_FIELDS:
        raise RunContractError("semantic dynamic draft fields are invalid")
    if dynamic.get("contract_version") != DYNAMIC_VERSION or dynamic.get("status") != "passed":
        raise RunContractError("semantic dynamic decision is invalid")
    turns = dynamic.get("turns_used")
    if not isinstance(turns, int) or isinstance(turns, bool) or not 1 <= turns <= int(request["max_turns"]):
        raise RunContractError("semantic dynamic turns_used is invalid")
    if dynamic.get("halt_condition_met") is not True:
        raise RunContractError("semantic dynamic halt condition is not met")
    eligible_items, candidate_dispositions = _candidate_assessment(request, manifest)
    eligible = {item["candidate_id"]: item for item in eligible_items}
    selected = dynamic.get("selected_items")
    if not isinstance(selected, list) or len(selected) > 10:
        raise RunContractError("semantic selected_items must contain 0..10 items")
    seen: set[str] = set()
    final_items: list[dict[str, Any]] = []
    for index, review in enumerate(selected):
        if not isinstance(review, dict) or set(review) != ITEM_FIELDS:
            raise RunContractError(f"semantic selected_items[{index}] fields are invalid")
        candidate_id = str(review.get("candidate_id") or "")
        if candidate_id in seen or candidate_id not in eligible:
            raise RunContractError(f"semantic selected_items[{index}] candidate_id is invalid")
        seen.add(candidate_id)
        candidate = eligible[candidate_id]
        identity = review.get("event_identity")
        if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
            raise RunContractError(f"semantic selected_items[{index}] event_identity is invalid")
        if identity.get("primary_domain") != candidate["primary_domain"] or identity.get("event_date") != candidate["published_at"]:
            raise RunContractError(f"semantic selected_items[{index}] identity does not match evidence")
        try:
            event_id = generate_event_id(identity)
        except ValueError as exc:
            raise RunContractError(f"semantic selected_items[{index}] identity is invalid") from exc
        level = review.get("intelligence_level")
        confidence = review.get("confidence")
        if level not in {"L1", "L2", "L3", "L4"} or confidence not in {"high", "medium", "low"}:
            raise RunContractError(f"semantic selected_items[{index}] level or confidence is invalid")
        major = review.get("major_signal")
        near_term = review.get("near_term_decision_impact")
        if not isinstance(major, bool) or not isinstance(near_term, bool):
            raise RunContractError(f"semantic selected_items[{index}] signal flags must be boolean")
        major_reason = _nonempty(review.get("major_signal_reason"), f"selected_items[{index}].major_signal_reason")
        decision_reason = _nonempty(review.get("decision_impact_reason"), f"selected_items[{index}].decision_impact_reason")
        item = {
            "event_id": event_id,
            "event_identity": deepcopy(identity),
            "identity_quality": "semantic",
            "candidate_refs": deepcopy(candidate["candidate_refs"]),
            "title": candidate["title"],
            "title_zh": _nonempty(review.get("title_zh"), f"selected_items[{index}].title_zh"),
            "url": candidate["url"],
            "source": candidate["source"],
            "source_type": candidate["source_type"],
            "access_check": deepcopy(candidate["access_check"]),
            "event_date": candidate["published_at"],
            "event_date_source": "published_at",
            "published_at": candidate["published_at"],
            "published_at_source": candidate["published_at_source"],
            "observed_at": candidate["access_check"]["checked_at"],
            "retrieved_at": candidate["access_check"]["checked_at"],
            "primary_domain": candidate["primary_domain"],
            "secondary_domains": deepcopy(candidate["secondary_domains"]),
            "major_signal": major,
            "major_signal_reason": major_reason,
            "near_term_decision_impact": near_term,
            "decision_impact_reason": decision_reason,
            "fact": _nonempty(review.get("fact"), f"selected_items[{index}].fact"),
            "connection": _nonempty(review.get("connection"), f"selected_items[{index}].connection"),
            "deduction": _nonempty(review.get("deduction"), f"selected_items[{index}].deduction"),
            "actionability": _nonempty(review.get("actionability"), f"selected_items[{index}].actionability"),
            "intelligence_level": level,
            "confidence": confidence,
            "corroboration_status": candidate["corroboration_status"],
            "summary_zh": _nonempty(review.get("summary_zh"), f"selected_items[{index}].summary_zh"),
        }
        if item["major_signal"] is True and not major_signal_eligible(item):
            item["major_signal"] = False
            item["major_signal_reason"] = "none"
        final_items.append(item)
    actions = dynamic.get("action_levers")
    if not isinstance(actions, list) or not actions:
        raise RunContractError("semantic action_levers are required")
    validated_actions: list[dict[str, str]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or set(action) != ACTION_FIELDS:
            raise RunContractError(f"semantic action_levers[{index}] fields are invalid")
        validated_actions.append({key: _nonempty(action.get(key), f"action_levers[{index}].{key}") for key in ACTION_FIELDS})
    _, pool = _bound_artifact(request, "candidate_pool")
    _, supplement = _bound_artifact(request, "supplement")
    supplemental_count = sum(
        len(result.get("candidates", []))
        for result in supplement.get("results", [])
        if isinstance(result, dict) and isinstance(result.get("candidates"), list)
    )
    generated_at = datetime.now(ZoneInfo(str(manifest["timezone"]))).isoformat()
    mix = _mix(manifest, final_items)
    core = {
        "schema_version": "1.4",
        "run_id": manifest["run_id"],
        "report_date": manifest["report_date"],
        "generated_at": generated_at,
        "model_used": os.environ.get("PI_MODEL") or os.environ.get("PI_MODEL_ID") or "semantic_model",
        "topic": manifest["topic"],
        "region": manifest["region"],
        "window": deepcopy(manifest["window"]),
        "punchline": _nonempty(dynamic.get("punchline"), "punchline"),
        "insights": _nonempty(dynamic.get("insights"), "insights"),
        "digest": _nonempty(dynamic.get("digest"), "digest"),
        "market": _nonempty(dynamic.get("market"), "market"),
        "action_levers": validated_actions,
        "pipeline": {},
        "coverage": _coverage(manifest, supplement),
        "candidate_funnel": _candidate_funnel(
            pool,
            supplemental_count,
            eligible_items,
            seen,
            candidate_dispositions,
        ),
        "mix": mix,
        "top_10": final_items,
        "data_gaps": _data_gaps(supplement, mix),
    }
    draft_paths = packet["draft_paths"]
    core_path = Path(str(draft_paths["refined_core"])).resolve()
    decision_path = Path(str(draft_paths["decision"])).resolve()
    atomic_dump_json(core_path, core)
    atomic_dump_json(
        decision_path,
        {
            "contract_version": "semantic-decision/1.0",
            "status": "passed",
            "turns_used": turns,
            "halt_condition_met": True,
        },
    )
    return finalize_semantic_decision(
        packet["run_manifest_path"],
        core_path,
        decision_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and finalize compact semantic-review work packets.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    context_parser = subparsers.add_parser("context")
    context_parser.add_argument("--request", type=Path, required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "context":
            print(json.dumps(build_agent_context(args.request), ensure_ascii=False, indent=2))
            return 0
        _, _, packet, _ = _load_packet(args.request)
        dynamic_path = Path(str(packet["draft_paths"]["dynamic"])).resolve()
        refined, receipt = assemble_and_finalize(args.request, load_json(dynamic_path, {}))
        print(
            json.dumps(
                {
                    "status": "decision_ready",
                    "refined_core_path": str(refined),
                    "refined_core_sha256": file_sha256(refined),
                    "receipt_path": str(receipt),
                    "receipt_sha256": file_sha256(receipt),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (RunContractError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
