"""Supplement bound-candidate and lane selection (extracted from run_contract.py).

Heuristic lane slices only: they order and discover leads, never authenticate a
source, a date, or an eligibility decision.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from contract_core import (
    RunContractError,
    candidate_ref,
    canonical_json_bytes,
)
from history_manager import normalize_url
from relevance import content_relevance, source_preference


def _candidate_lane_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "candidate_ref": candidate_ref(str(candidate.get("url") or "")),
        "source_object_sha256": hashlib.sha256(
            canonical_json_bytes(candidate)
        ).hexdigest(),
    }
    for field in (
        "title",
        "url",
        "published_at",
        "published_at_source",
        "source",
        "source_type",
        "provisional_domain",
        "primary_domain",
        "access_check",
    ):
        if field in candidate:
            summary[field] = deepcopy(candidate[field])
    text = str(candidate.get("summary") or candidate.get("description") or "").strip()
    if text:
        summary["summary_excerpt"] = text[:500]
    return summary


def _lane_candidate_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in (
            "title",
            "summary",
            "description",
            "fact",
            "summary_hint",
            "keyword_connection_hint",
        )
    ).casefold()


def _lane_candidate_domains(item: dict[str, Any]) -> set[str]:
    domains = {str(item.get("provisional_domain") or item.get("primary_domain") or "")}
    for field in ("secondary_domains", "provisional_secondary_domains"):
        values = item.get(field)
        if isinstance(values, list):
            domains.update(str(value) for value in values)
    return domains


def _lane_candidate_rank(item: dict[str, Any]) -> tuple[Any, ...]:
    """Lead priority only: never authenticate a source from claims or its hostname."""
    text = _lane_candidate_text(item)
    concrete = any(
        word in text
        for word in (
            "release",
            "launch",
            "policy",
            "regulation",
            "procurement",
            "payment",
            "vulnerability",
            "benchmark",
            "clinical trial",
            "technical report",
            "发布",
            "上线",
            "政策",
            "监管",
            "采购",
            "支付",
            "漏洞",
            "临床试验",
            "技术报告",
        )
    )
    opinion = any(
        word in text
        for word in (
            "opinion",
            "essay",
            "i think",
            "commentary",
            "观点",
            "随笔",
            "我认为",
            "评论",
        )
    )
    medical = "healthcare_digital" in _lane_candidate_domains(item) or any(
        word in text
        for word in (
            "medical",
            "clinical",
            "healthcare",
            "hospital",
            "医疗",
            "临床",
            "医院",
        )
    )
    # Stable URL/title ties are independent of input order and untrusted assurance fields.
    return (
        int(opinion),
        -int(medical),
        -int(concrete),
        normalize_url(str(item.get("url") or "")),
        str(item.get("title") or ""),
        text,
    )


def _technical_lead_evidence(
    item: dict[str, Any], focus: dict[str, Any]
) -> tuple[str, tuple[Any, ...]]:
    """Selection hints, not source authentication or live availability evidence.

    refine.make_candidate retains raw_desc[:220] (or title) as summary_hint;
    keyword_connection_hint and heuristic_rank are generated and never evidence.
    """
    text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "raw_desc", "summary", "description", "summary_hint")
    ).casefold()
    title = str(item.get("title") or "").strip().casefold()
    url = normalize_url(str(item.get("url") or ""))
    parsed = urlparse(url)
    path = parsed.path.casefold().rstrip("/")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "invalid_url", ()
    if not path or path in {"/index.html", "/index.htm", "/home"}:
        return "homepage", ()
    if (
        (parsed.hostname or "").endswith(".wikipedia.org")
        or re.search(
            r"/(?:wiki|encyclopedia|search|login|signin|sign-in|challenge)(?:/|$)", path
        )
        or re.search(r"(?:^|&)(?:q|query|search)=", parsed.query)
    ):
        return "non_article_url", ()
    if re.match(
        r"(?:what is |what are |encyclopedia\b|sign in\b|log in\b|access denied\b|just a moment\b)",
        title,
    ) or re.search(r"\b(?:explained|an overview)\s*[?.!]*$", title):
        return "explanation_or_access_page", ()
    if any(
        marker in text
        for marker in (
            "verify you are human",
            "checking your browser",
            "enable javascript and cookies to continue",
            "sign in to continue",
            "log in to continue",
            "making sure you're not a bot",
        )
    ):
        return "challenge_or_login_content", ()
    domain_config = focus.get("domains", {}).get("technology", {})
    relevance, matches = content_relevance(text, domain_config)
    if not matches:
        return "no_technical_text", ()
    opinion = bool(
        re.search(
            r"\b(?:opinion|essay|commentary|why we should|i think)\b|观点|随笔", text
        )
    )
    concrete = bool(
        re.search(
            r"\b(?:release[ds]?|launch(?:ed)?|ship(?:ped)?|patch(?:es)?|updates?|cve|security holes)\b|发布|漏洞",
            text,
        )
    )
    # Original-release/project paths are a tie-breaking potential hint only.
    original_path = bool(
        re.search(r"/(?:releases?|newsroom)(?:/|$)", path)
        or parsed.hostname == "github.com"
        and len(path.split("/")) >= 3
    )
    return "technical_text", (
        int(opinion),
        -int(concrete),
        -relevance,
        -source_preference(str(item.get("source") or ""), domain_config),
        -int(original_path),
        url,
        title,
        text,
    )


def _lane_slice_candidates(
    candidate_pool: dict[str, Any],
    lane: str,
    focus: dict[str, Any],
    *,
    article_broker_version: int = 2,
) -> list[dict[str, Any]]:
    items = candidate_pool.get("items")
    if not isinstance(items, list):
        raise RunContractError("candidate pool items must be a list")
    if article_broker_version == 3 and lane == "TechRadar":
        ranked = []
        for item in items:
            if isinstance(item, dict):
                reason, rank = _technical_lead_evidence(item, focus)
                if reason == "technical_text":
                    ranked.append(
                        (
                            rank,
                            hashlib.sha256(canonical_json_bytes(item)).hexdigest(),
                            item,
                        )
                    )
        return [
            _candidate_lane_summary(item)
            for _, _, item in sorted(ranked, key=lambda row: row[:2])
        ]
    domain_by_lane = {
        "TechRadar": "technology",
        "HealthcareRadar": "healthcare_digital",
    }
    required_domain = domain_by_lane.get(lane)
    configured_lane = (
        focus.get("coverage_policy", {}).get("lanes", {}).get(lane, {})
        if isinstance(focus, dict)
        else {}
    )
    keywords = (
        [
            str(value).casefold()
            for value in configured_lane.get("keywords", [])
            if str(value).strip()
        ]
        if isinstance(configured_lane, dict)
        else []
    )
    selected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        domains = _lane_candidate_domains(item)
        explicit_lane = str(item.get("lane") or "")
        text = _lane_candidate_text(item)
        matches = (
            explicit_lane == lane
            or (required_domain is not None and required_domain in domains)
            or (
                required_domain is None and any(keyword in text for keyword in keywords)
            )
        )
        if matches:
            selected.append(item)
    return [
        _candidate_lane_summary(item)
        for item in sorted(selected, key=_lane_candidate_rank)
    ]


def select_supplement_bound_candidates(
    candidate_pool: dict[str, Any],
    gap: dict[str, Any],
    focus: dict[str, Any],
    *,
    article_broker_version: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Used only before request registration; finalizers consume frozen IDs."""
    candidates = _lane_slice_candidates(
        candidate_pool,
        gap["lane"],
        focus,
        article_broker_version=article_broker_version,
    )
    if not gap.get("verify_bound_candidates"):
        return candidates, []
    limit = int(gap["max_urls"])
    if article_broker_version == 3 and gap["lane"] == "TechRadar":
        limit = min(limit, 2)
        unique = {}
        for candidate in candidates:
            unique.setdefault(candidate["candidate_ref"], candidate)
        candidates = list(unique.values())
    required = [str(candidate["candidate_ref"]) for candidate in candidates[:limit]]
    return candidates, required
