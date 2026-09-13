"""Owner-approved closure policy plus bounded-excerpt receipt coverage.

Both behaviour changes were explicitly authorised on 2026-09-13:
- early closure after two successful searches with a settled but unproductive native attempt;
- an explicitly declared bounded excerpt is recorded as verified-with-disclosed-coverage
  instead of a false access failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import article_broker as broker
import pytest
from test_article_broker_contract import new_run as frozen_run  # noqa: F401 - fixture chain
from test_article_broker_evidence import network, new_run, search, setup  # noqa: F401

URL = "https://example.org/original-release"


def test_two_searches_with_unproductive_attempt_seal_without_spending_url_budget(
    new_run, monkeypatch
):
    request, _ = setup(new_run, max_queries=2)
    spare = "https://other.example/never-attempted"
    search(
        request,
        results=[
            {"url": URL, "title": "Blocked lead"},
            {"url": spare, "title": "Never attempted"},
            {"url": "https://other.example/second", "title": "Never attempted too"},
        ],
    )
    network(monkeypatch, code=403)
    data = broker.operate(request, "tech", "http", url=URL)
    assert data["next_action"]["remaining_urls"] == 3
    assert data["next_action"]["available_discovered_urls"]
    data = search(request, "empty", query="regulator original filing")
    next_action = data["next_action"]
    assert next_action["stop_eligible"] is True
    assert next_action["action"] == "seal"
    assert next_action["stop_reason"] == "searches_exhausted_without_qualifying_candidate"
    assert next_action["remaining_urls"] == 3
    assert broker.operate(request, "tech", "seal")["completed_at"]


def test_unproductive_seal_requires_a_settled_attempt(new_run, monkeypatch):
    """Without any settled native attempt the broker must still insist on fetching."""
    request, _ = setup(new_run, max_queries=2)
    search(request, results=[{"url": URL, "title": "Found but unfetched"}])
    data = search(request, "empty", query="second angle")
    next_action = data["next_action"]
    assert next_action["stop_eligible"] is False
    assert next_action["action"] in {"http_discovered", "fetch_discovered"}
    assert next_action["available_discovered_urls"]


def test_unproductive_seal_waits_while_query_budget_remains(new_run, monkeypatch):
    request, _ = setup(new_run, max_queries=2)
    search(request, results=[{"url": URL, "title": "Only result"}])
    network(monkeypatch, code=403)
    data = broker.operate(request, "tech", "http", url=URL)
    assert data["next_action"]["remaining_queries"] == 1
    assert data["next_action"]["stop_eligible"] is False
    assert data["next_action"]["action"] == "search_different"


LEDGER = {"request_sha256": "a" * 64, "gap_id": "technology-supply"}
RESERVATION = {
    "id": "fetch-9",
    "invocation_id": "a" * 64 + ":technology-supply:fetch-9",
    "url": "https://example.org/short",
    "arguments": {"url": "https://example.org/short", "mode": "readable"},
    "at": "2026-09-13T06:59:59+00:00",
}
RECEIPT = {
    "request_sha256": "a" * 64,
    "gap_id": "technology-supply",
    "reservation_id": "fetch-9",
    "invocation_id": RESERVATION["invocation_id"],
    "tool": "fetch_content",
    "arguments": RESERVATION["arguments"],
    "started_at": "2026-09-13T07:00:00+00:00",
    "completed_at": "2026-09-13T07:00:01+00:00",
    "outcome": "success",
    "error": None,
    "text": "tiny body",
    "truncated": None,
    "parent_attestation": "actual_public_tool_receipt",
}
CHECKED = "2026-09-13T07:00:02+00:00"


def test_bounded_excerpt_declaration_is_verified_with_disclosed_coverage():
    access = broker.native_proof(
        dict(RECEIPT, text_coverage="bounded_excerpt"), LEDGER, RESERVATION, CHECKED
    )["access"]
    assert access["status"] == "verified"
    assert access["error_code"] is None
    assert access["coverage"] == "bounded_excerpt"


def test_undeclared_short_body_still_blocks():
    access = broker.native_proof(dict(RECEIPT), LEDGER, RESERVATION, CHECKED)["access"]
    assert access["status"] == "blocked"
    assert access["error_code"] == "NATIVE_CONTENT_NOT_VERIFIED"
    assert access["coverage"] == "full"


def test_truncated_flag_still_blocks_a_bounded_excerpt():
    access = broker.native_proof(
        dict(RECEIPT, text_coverage="bounded_excerpt", truncated=True),
        LEDGER,
        RESERVATION,
        CHECKED,
    )["access"]
    assert access["status"] == "blocked"
    assert access["error_code"] == "NATIVE_TOOL_TRUNCATED"


def test_access_key_set_accepts_legacy_and_coverage_shapes():
    access = broker.native_proof(
        dict(RECEIPT, text_coverage="bounded_excerpt"), LEDGER, RESERVATION, CHECKED
    )["access"]
    legacy = {key: value for key, value in access.items() if key != "coverage"}
    # The key-set gate must not reject either shape; both stop at the invocation binding check.
    for candidate in (legacy, access, dict(access, coverage="nonsense")):
        with pytest.raises(Exception) as excinfo:
            broker.validate_native_access(candidate)
        message = str(excinfo.value)
        assert "native access cannot claim HTTP transport facts" not in message
        if candidate.get("coverage") == "nonsense":
            assert "coverage invalid" in message
