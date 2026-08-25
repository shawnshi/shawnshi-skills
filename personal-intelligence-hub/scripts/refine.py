from __future__ import annotations

import argparse
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from blackboard import update_phase
from history_manager import load_recent_history, match_history
from hub_utils import (
    CANDIDATES_PATH,
    HUB_DIR,
    LATEST_SCAN_PATH,
    REFINED_PATH as _REFINED_PATH,
    atomic_dump_json,
    ensure_runtime_dirs,
    load_json,
)
from mix_policy import DOMAINS
from run_contract import (
    RunContractError,
    candidate_object_hash,
    candidate_ref,
    file_sha256,
    require_stage,
)


FOCUS_PATH = HUB_DIR / "references" / "strategic_focus.json"
PROMPT_PATH = HUB_DIR / "references" / "prompts" / "v1_refine_system.md"
# Retained as a compatibility injection point for existing callers and tests.
REFINED_PATH = _REFINED_PATH


def keyword_matches(text: str, keyword: str) -> bool:
    normalized_keyword = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+\-/]*", normalized_keyword):
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return normalized_keyword in text


def load_inputs(
    focus_path: Path | None = None,
    scan_path: Path | None = None,
) -> tuple[dict, dict]:
    source_path = scan_path or LATEST_SCAN_PATH
    scan_data = load_json(source_path, {})
    focus_data = load_json(focus_path or FOCUS_PATH, {})
    if not isinstance(scan_data.get("items"), list):
        raise RuntimeError(f"No valid scan data found at {source_path}")
    return scan_data, focus_data


def score_item(item: dict, focus_data: dict) -> tuple[int, list[str], str, dict[str, int]]:
    text = (item.get("title", "") + " " + item.get("raw_desc", "")).lower()
    domain_scores: dict[str, int] = {}
    matched_by_domain: dict[str, list[str]] = {}
    for domain in DOMAINS:
        domain_config = focus_data.get("domains", {}).get(domain, {})
        score = 0
        matched: list[str] = []
        for entry in domain_config.get("keywords", []):
            keyword = str(entry["keyword"])
            if keyword_matches(text, keyword):
                score += int(entry["weight"])
                matched.append(keyword)
        score += int(domain_config.get("priority_sources", {}).get(item.get("source", ""), 0))
        domain_scores[domain] = score
        matched_by_domain[domain] = matched

    explicit_domain = item.get("primary_domain")
    if explicit_domain in DOMAINS:
        primary_domain = explicit_domain
    else:
        primary_domain = max(DOMAINS, key=lambda domain: domain_scores[domain])
    return (
        domain_scores[primary_domain],
        matched_by_domain[primary_domain],
        primary_domain,
        domain_scores,
    )


def confidence_from_source(source: str, focus_data: dict) -> str:
    conf = focus_data.get("source_confidence", {})
    if source in conf.get("high", []):
        return "high"
    if source in conf.get("medium", []):
        return "medium"
    return "medium"


def level_from_score(score: int, runner_available: bool) -> str:
    if score >= 4:
        return "L2"
    return "L1"


def make_candidate(
    item: dict,
    score: int,
    matched: list[str],
    primary_domain: str,
    domain_scores: dict[str, int],
    runner_available: bool,
    focus_data: dict,
) -> dict:
    summary = item.get("raw_desc", "").strip() or item.get("title", "")
    summary = summary[:220]
    connection = "、".join(matched[:3]) if matched else "与当前战略重心关联较弱，但建议观察"
    provisional_level = level_from_score(score, runner_available)
    candidate_id = candidate_ref(str(item.get("url") or ""))
    candidate = {
        "candidate_id": candidate_id,
        "title": item.get("title", "Untitled"),
        "url": item.get("url", ""),
        "source": item.get("source", "Unknown"),
        "published_at": item.get("time", "unknown"),
        "published_at_source": item.get("published_at_source", "unknown"),
        "observed_at": item.get("observed_at") or item.get("retrieved_at"),
        "retrieved_at": item.get("retrieved_at") or datetime.now().astimezone().isoformat(),
        "provisional_domain": primary_domain,
        "provisional_secondary_domains": [
            domain
            for domain in DOMAINS
            if domain != primary_domain and domain_scores.get(domain, 0) > 0
        ],
        "domain_scores": domain_scores,
        "heuristic_rank": score,
        "provisional_level": provisional_level,
        "source_confidence_hint": confidence_from_source(item.get("source", ""), focus_data),
        "summary_hint": summary,
        "keyword_connection_hint": connection,
        "claimed_major_signal": item.get("major_signal") is True,
        "claimed_major_signal_reason": (
            str(item.get("major_signal_reason") or "已通过高影响资讯门槛")
            if item.get("major_signal") is True
            else "none"
        ),
    }
    candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
    return candidate


def heuristics(
    scan_data: dict,
    focus_data: dict,
    *,
    min_score_override: int | None = None,
    max_items_override: int | None = None,
    history_entries: list[dict] | None = None,
) -> dict:
    runner_available = False
    scored = []
    for item in scan_data["items"]:
        if match_history(item, entries=history_entries or [])["redundant"]:
            continue
        score, matched, primary_domain, domain_scores = score_item(item, focus_data)
        scored.append(
            make_candidate(
                item,
                score,
                matched,
                primary_domain,
                domain_scores,
                runner_available,
                focus_data,
            )
        )

    max_candidates = max_items_override if max_items_override is not None else focus_data.get("filters", {}).get("max_candidates", focus_data.get("filters", {}).get("max_top10", 10) * 5)
    min_score = min_score_override if min_score_override is not None else focus_data.get("filters", {}).get("min_score_for_top10", 4)
    qualified_candidates = [
        candidate for candidate in scored if candidate["heuristic_rank"] >= min_score
    ]
    ranked_candidates = sorted(
        qualified_candidates,
        key=lambda candidate: (
            -int(candidate.get("heuristic_rank", 0)),
            str(candidate.get("title") or ""),
            str(candidate.get("url") or ""),
        ),
    )[:max_candidates]

    rejected_by_reason = {
        "historical_duplicate": len(scan_data["items"]) - len(scored),
        "below_heuristic_threshold": len(scored) - len(qualified_candidates),
        "candidate_capacity": max(0, len(qualified_candidates) - len(ranked_candidates)),
    }
    baseline_funnel = scan_data.get("candidate_funnel")
    if isinstance(baseline_funnel, dict) and isinstance(baseline_funnel.get("raw"), int):
        observed = int(baseline_funnel["raw"])
        terminal_dispositions = {
            "invalid_or_unknown_date": int(baseline_funnel.get("quarantined", 0)),
            "outside_window": int(baseline_funnel.get("outside_window", 0)),
            "source_exclusion": int(baseline_funnel.get("excluded", 0)),
            **rejected_by_reason,
            "retained_for_review": len(ranked_candidates),
        }
    else:
        observed = len(scan_data["items"])
        terminal_dispositions = {
            **rejected_by_reason,
            "retained_for_review": len(ranked_candidates),
        }
    if sum(terminal_dispositions.values()) != observed:
        raise RuntimeError("refinement candidate funnel does not conserve baseline observations")
    return {
        "contract_version": "candidate-pool/1.0",
        "artifact_kind": "candidates_only",
        "review_status": "unreviewed",
        "model_used": "heuristic",
        "created_at": datetime.now().astimezone().isoformat(),
        "items": ranked_candidates,
        "candidate_funnel": {
            "observed": observed,
            "retained_for_review": len(ranked_candidates),
            "rejected_by_reason": rejected_by_reason,
            "terminal_dispositions": terminal_dispositions,
        },
        "metadata": scan_data.get("metadata", {}),
    }





def enforce_entity_linking(text: str, entities: list[str]) -> str:
    if not text:
        return text
    for entity in entities:
        if len(entity) >= 2:
            pattern = re.compile(rf"(?<!\[\[)({re.escape(entity)})(?!\]\])", flags=re.IGNORECASE)
            text = pattern.sub(r"[[\1]]", text)
    return text


def post_process_entities(output: dict, focus_data: dict) -> dict:
    competitors = focus_data.get("competitors", [])
    keywords = [
        entry["keyword"]
        for domain in DOMAINS
        for entry in focus_data.get("domains", {}).get(domain, {}).get("keywords", [])
    ]
    entities = sorted(list(set(competitors + keywords)), key=len, reverse=True)
    
    for candidate in output.get("top_10", []):
        if "summary_zh" in candidate:
            candidate["summary_zh"] = enforce_entity_linking(candidate["summary_zh"], entities)
        if "deduction" in candidate:
            candidate["deduction"] = enforce_entity_linking(candidate["deduction"], entities)
    return output


def refine(
    focus_path: Path | None = None,
    min_score: int | None = None,
    max_items: int | None = None,
    dedupe_days: int | None = None,
    manifest_path: Path | None = None,
    scan_path: Path | None = None,
    candidates_path: Path | None = None,
    blackboard_path: Path | None = None,
) -> None:
    if blackboard_path is None:
        ensure_runtime_dirs()
    if manifest_path is None:
        raise RunContractError("--manifest is required; heuristic refinement must belong to an active run")
    manifest = require_stage(manifest_path, "baseline", {"completed", "degraded"})
    baseline = manifest["stages"]["baseline"]
    baseline_path = scan_path or LATEST_SCAN_PATH
    output_path = candidates_path or CANDIDATES_PATH
    if file_sha256(baseline_path) != baseline.get("artifact_sha256"):
        raise RunContractError("latest scan bytes do not match the baseline receipt")
    history_record = manifest.get("artifacts", {}).get("history_snapshot")
    if not isinstance(history_record, dict):
        raise RunContractError("history_snapshot artifact is required before refinement")
    history_path = Path(str(history_record.get("artifact_path") or ""))
    if (
        not history_path.is_file()
        or file_sha256(history_path) != history_record.get("artifact_sha256")
    ):
        raise RunContractError("history_snapshot bytes changed")
    update_phase("refine", "running", blackboard_path=blackboard_path)
    scan_data, focus_data = load_inputs(focus_path, baseline_path)
    dedupe_window = dedupe_days or focus_data.get("filters", {}).get("dedupe_days", 7)
    report_clock = datetime.combine(
        date.fromisoformat(manifest["report_date"]),
        time.max,
        tzinfo=ZoneInfo(manifest["timezone"]),
    )
    history_entries = load_recent_history(
        days=int(dedupe_window),
        now=report_clock,
        path=history_path,
    )
    output = heuristics(
        scan_data,
        focus_data,
        min_score_override=min_score,
        max_items_override=max_items,
        history_entries=history_entries,
    )
    for candidate in output.get("items", []):
        if isinstance(candidate, dict):
            candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
    output["run_id"] = manifest["run_id"]
    output["baseline_sha256"] = baseline["artifact_sha256"]
    atomic_dump_json(output_path, output)
    update_phase("refine", "candidates_ready", blackboard_path=blackboard_path)
    print(f"[OK] heuristic candidates saved to {output_path}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build parameterized intelligence candidates.")
    parser.add_argument("--focus-config", type=Path)
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--dedupe-days", type=int)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    refine(
        args.focus_config,
        args.min_score,
        args.max_items,
        args.dedupe_days,
        args.manifest,
        args.scan,
        args.output,
    )
