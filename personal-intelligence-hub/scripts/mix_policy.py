from __future__ import annotations

import math
from typing import Any


DOMAINS = ("technology", "healthcare_digital")


def _normalized_ratio(ratio: dict[str, float]) -> dict[str, float]:
    values = {domain: float(ratio.get(domain, 0.0)) for domain in DOMAINS}
    total = sum(values.values())
    if total <= 0:
        raise ValueError("domain ratio must have a positive sum")
    return {domain: values[domain] / total for domain in DOMAINS}


def allocate_target_counts(total: int, ratio: dict[str, float]) -> dict[str, int]:
    if total < 0:
        raise ValueError("total must be non-negative")
    normalized = _normalized_ratio(ratio)
    raw = {domain: total * normalized[domain] for domain in DOMAINS}
    counts = {domain: math.floor(raw[domain]) for domain in DOMAINS}
    remaining = total - sum(counts.values())
    order = sorted(
        DOMAINS,
        key=lambda domain: (raw[domain] - counts[domain], normalized[domain]),
        reverse=True,
    )
    for domain in order[:remaining]:
        counts[domain] += 1
    return counts


def _effective_ratio(
    candidates: list[dict[str, Any]], policy: dict[str, Any]
) -> tuple[dict[str, float], dict[str, Any]]:
    default_ratio = _normalized_ratio(policy["default_ratio"])
    major_by_domain = {
        domain: [
            item
            for item in candidates
            if item.get("primary_domain") == domain and item.get("major_signal") is True
        ]
        for domain in DOMAINS
    }
    favored = [domain for domain in DOMAINS if major_by_domain[domain]]
    if len(favored) != 1:
        reason = (
            "none"
            if not favored
            else "两个领域均有高影响资讯，维持默认比例"
        )
        return default_ratio, {
            "applied": False,
            "favored_domain": "none",
            "reason": reason,
            "trigger_urls": [],
        }

    favored_domain = favored[0]
    other_domain = next(domain for domain in DOMAINS if domain != favored_domain)
    max_shift = max(0.0, float(policy.get("max_ratio_shift", 0.2)))
    shift = min(max_shift, default_ratio[other_domain])
    effective_ratio = dict(default_ratio)
    effective_ratio[favored_domain] += shift
    effective_ratio[other_domain] -= shift
    trigger_items = major_by_domain[favored_domain]
    reasons = sorted(
        {
            str(item.get("major_signal_reason") or "已通过高影响资讯门槛")
            for item in trigger_items
        }
    )
    return effective_ratio, {
        "applied": True,
        "favored_domain": favored_domain,
        "reason": "；".join(reasons),
        "trigger_urls": [str(item.get("url") or "") for item in trigger_items],
    }


def select_candidates_with_mix(
    candidates: list[dict[str, Any]],
    max_items: int,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_items < 0:
        raise ValueError("max_items must be non-negative")
    invalid_domains = sorted(
        {
            str(item.get("primary_domain"))
            for item in candidates
            if item.get("primary_domain") not in DOMAINS
        }
    )
    if invalid_domains:
        raise ValueError(f"invalid primary_domain values: {invalid_domains}")

    ranked = sorted(
        candidates,
        key=lambda item: (
            -int(item.get("major_signal") is True),
            -int(item.get("strategic_score", item.get("score", 0))),
            str(item.get("title") or ""),
            str(item.get("url") or ""),
        ),
    )
    total = min(max_items, len(ranked))
    effective_ratio, adjustment = _effective_ratio(
        ranked if total > 0 else [], policy
    )
    target_counts = allocate_target_counts(total, effective_ratio)
    buckets = {
        domain: [item for item in ranked if item["primary_domain"] == domain]
        for domain in DOMAINS
    }

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for domain in DOMAINS:
        for item in buckets[domain][: target_counts[domain]]:
            selected.append(item)
            selected_ids.add(id(item))

    if len(selected) < total:
        for item in ranked:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            if len(selected) == total:
                break

    selected.sort(
        key=lambda item: (
            -int(item.get("major_signal") is True),
            -int(item.get("strategic_score", item.get("score", 0))),
            str(item.get("title") or ""),
            str(item.get("url") or ""),
        )
    )
    actual_counts = {
        domain: sum(1 for item in selected if item["primary_domain"] == domain)
        for domain in DOMAINS
    }
    missing_domains = [
        domain for domain in DOMAINS if actual_counts[domain] < target_counts[domain]
    ]
    supply_exception = {
        "applied": bool(missing_domains),
        "reason": (
            "合格候选不足：" + "、".join(missing_domains)
            if missing_domains
            else "none"
        ),
        "missing_domains": missing_domains,
    }
    if adjustment["applied"]:
        retained_triggers = [
            item
            for item in selected
            if item.get("major_signal") is True
            and item.get("primary_domain") == adjustment["favored_domain"]
        ]
        adjustment["trigger_urls"] = [
            str(item.get("url") or "") for item in retained_triggers
        ]
        adjustment["reason"] = "；".join(
            sorted(
                {
                    str(item.get("major_signal_reason") or "已通过高影响资讯门槛")
                    for item in retained_triggers
                }
            )
        )
    mix = {
        "default_ratio": _normalized_ratio(policy["default_ratio"]),
        "effective_ratio": effective_ratio,
        "target_counts": target_counts,
        "actual_counts": actual_counts,
        "adjustment": adjustment,
        "supply_exception": supply_exception,
    }
    return selected, mix
