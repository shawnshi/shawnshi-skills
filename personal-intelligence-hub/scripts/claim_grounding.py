from __future__ import annotations

import re
from typing import Any, Callable

NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)*")
KINDS = {"number", "policy_status", "causal"}


def requires_grounding(item: dict[str, Any]) -> bool:
    return (
        item.get("intelligence_level") in {"L3", "L4"}
        or item.get("near_term_decision_impact") is True
        or item.get("major_signal") is True
    )


def validate_registered_claims(
    item: dict[str, Any], read_span: Callable[[int, int], dict[str, Any]]
) -> None:
    """Verify source bytes and numeric coverage; semantic entailment still needs review."""
    ledger = item.get("claim_grounding")
    if ledger is None:
        if requires_grounding(item):
            raise ValueError("critical item requires registered claim_grounding")
        return
    if not isinstance(ledger, dict) or not isinstance(ledger.get("basis"), str) or not ledger["basis"].strip():
        raise ValueError("claim_grounding.basis is required")
    claims = ledger.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("claim_grounding.claims must be nonempty")
    fact = str(item.get("fact") or "")
    bound_numbers: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("kind") not in KINDS:
            raise ValueError("invalid claim kind")
        statement = claim.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("claim statement is required")
        if claim.get("status") != "grounded":
            raise ValueError("published factual claims must be grounded; move hypotheses to deduction")
        ref = claim.get("evidence_ref")
        if not isinstance(ref, dict) or set(ref) != {"readable_text_sha256", "start", "end"}:
            raise ValueError("claim requires evidence_ref hash/start/end")
        start, end = ref["start"], ref["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("invalid claim source span")
        quote = claim.get("evidence")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("claim evidence quote is required")
        span = read_span(start, end)
        if (
            span.get("status") != "available"
            or span.get("readable_text_sha256") != ref["readable_text_sha256"]
            or span.get("start") != start
            or span.get("end") != end
            or span.get("text") != quote
            or span.get("excerpt_truncated") is not False
        ):
            raise ValueError("claim evidence does not match the registered source span")
        if claim["kind"] == "number":
            value = str(claim.get("value") or "").strip()
            numbers = set(NUMBER.findall(value))
            if not numbers or value not in fact or not numbers.issubset(set(NUMBER.findall(quote))):
                raise ValueError("claim number is not supported by fact and source quote")
            bound_numbers.update(numbers)
    if requires_grounding(item) and set(NUMBER.findall(fact)) - bound_numbers:
        raise ValueError("critical fact contains numbers without registered bindings")
