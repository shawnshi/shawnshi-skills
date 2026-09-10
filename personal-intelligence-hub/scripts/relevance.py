"""Configured, presence-only lexical relevance; source names are sorting hints."""

from __future__ import annotations

import re

SCORING_VERSION = "content-relevance/2.0"


def keyword_matches(text: str, keyword: str) -> bool:
    text, keyword = text.casefold(), keyword.casefold()
    if not keyword:
        return False
    if keyword.isascii():
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text)
            is not None
        )
    return keyword in text


def content_relevance(text: str, domain_config: dict) -> tuple[int, list[str]]:
    """Each configured concept contributes once, regardless of alias/repetition."""
    score = 0
    matched = []
    for entry in domain_config.get("keywords", []):
        keyword = str(entry["keyword"])
        if any(
            keyword_matches(text, str(term))
            for term in [keyword, *entry.get("aliases", [])]
        ):
            score += int(entry["weight"])
            matched.append(keyword)
    return score, matched


def source_preference(source: str, domain_config: dict) -> int:
    """Not authentication, content evidence, or permission to admit a candidate."""
    return int(domain_config.get("priority_sources", {}).get(source, 0))
