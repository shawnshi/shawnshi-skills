"""Pure handoff projection and real frozen-launch construction; no network."""

from copy import deepcopy
import io
import json
from unittest.mock import patch

import pytest
import run_contract as rc
from broker_handoff import compact_packet, draft_contract, publication_options
from supplement_agent import build_agent_context
from test_article_broker_contract import new_run, request as build_request


def proof(url="https://example.org/news/item"):
    return {"id": "fetch-1", "proof_path": "registered-proof.json", "proof_sha256": "a" * 64,
            "access": {"requested_url": url, "coverage": "full"},
            "metadata": {"dates": [], "article_core": True}, "body_text": "Retained source body " * 200,
            "body_text_sha256": "b" * 64, "body_text_truncated": False}


def test_existing_body_date_always_wins_over_feed_and_path():
    p = proof("https://example.org/2026/09/30/item")
    p["metadata"]["dates"] = [{"published_at": "2026-09-29", "parser_rule": "published-label/1"}]
    lane = {"candidates": [{"url": p["access"]["requested_url"], "published_at": "2026-10-01", "published_at_source": "rss_published"}]}
    assert publication_options(p, lane) == p["metadata"]["dates"]


def test_registered_same_url_feed_basis_is_projected_not_invented():
    p = proof()
    lane = {"candidates": [{"url": p["access"]["requested_url"], "published_at": "2026-09-30", "published_at_source": "rss_published"}]}
    assert publication_options(p, lane) == [{"parser_rule": "pool-declared/1", "published_at": "2026-09-30", "published_at_source": "rss_published"}]
    assert publication_options(p, {"candidates": [{"url": "https://example.org/other", "published_at": "2026-09-30", "published_at_source": "rss_published"}]}) == []


@pytest.mark.parametrize("source", ["unknown", "retrieved_at", ""])
def test_unknown_or_observation_dates_are_not_projected(source):
    p = proof()
    assert publication_options(p, {"candidates": [{"url": p["access"]["requested_url"], "published_at": "2026-09-30", "published_at_source": source}]}) == []


def test_existing_url_path_basis_requires_undated_article_core():
    p = proof("https://example.org/2026/09/30/item")
    assert publication_options(p, {}) == [{"parser_rule": "url-path/1", "published_at": "2026-09-30", "published_at_source": "url_path"}]
    p["metadata"]["article_core"] = False
    assert publication_options(p, {}) == []


def test_preview_does_not_relabel_full_native_coverage_or_change_source():
    p = proof()
    snap = {"next_action": {"action": "sealed", "stop_reason": "url_budget_exhausted"}, "request_sha256": "c" * 64, "gap_id": "tech", "started_at": "2026-10-01T01:00:00+00:00", "completed_at": "2026-10-01T01:01:00+00:00", "broker_evidence_sha256": "d" * 64, "executed_queries": ["recorded query"], "access_log": [p["access"]], "required_bound_candidate_ids": [], "proofs": [p]}
    original = deepcopy(snap)
    result = compact_packet(snap, {}, preview_chars=20)
    assert result["proofs"][0]["preview_truncated"] is True
    assert result["proofs"][0]["native_body_truncated"] is False
    assert result["proofs"][0]["access_check"]["coverage"] == "full"
    assert snap == original
    snap["completed_at"] = None
    with pytest.raises(rc.RunContractError, match="sealed broker evidence required"):
        compact_packet(snap, {})


def test_draft_contract_recovers_complete_schema_without_full_context_or_writes(new_run):
    request_path, _ = build_request(new_run)
    before = new_run[0].read_bytes()
    full = build_agent_context(request_path, "tech")
    with patch("broker_handoff.broker.evidence", side_effect=AssertionError("no acquisition")):
        recovered = draft_contract(request_path, "tech")
    assert recovered["draft_schema"] == full["draft_schema"]
    assert recovered["draft_schema"]["candidate_identity_quality_allowed"] == ["semantic"]
    assert recovered["draft_schema"]["candidate_event_identity_required"] == ["key_version", "primary_domain", "actor", "action", "object", "event_date"]
    assert "exact registered candidate_id" in recovered["draft_schema"]["candidate_id_rule"]
    assert recovered["draft_path"] == full["draft_path"]
    assert recovered["required_bound_candidate_ids"] == full["required_bound_candidate_ids"]
    expected = [{"candidate_id": c["candidate_ref"], "url": c["url"]} for c in full["bound_candidates"] if c["candidate_ref"] in full["required_bound_candidate_ids"]]
    assert recovered["required_bound_candidates"] == expected
    assert recovered["max_turns"] == full["gap"]["max_turns"]
    assert "not supervisor messages" in recovered["turns_used_rule"]
    assert recovered["request_sha256"] == rc.file_sha256(request_path)
    assert not {"rules", "role", "bound_candidates", "article_broker"} & recovered.keys()
    assert len(json.dumps(recovered, ensure_ascii=False).encode("utf-8")) < 8192
    assert new_run[0].read_bytes() == before


def test_draft_contract_cli_works_without_sealed_evidence(new_run):
    from broker_handoff import main

    request_path, _ = build_request(new_run)
    output = io.StringIO()
    with patch("sys.stdout", output), patch("sys.argv", ["broker_handoff.py", "--request", str(request_path), "--gap-id", "tech", "--draft-contract"]), patch("broker_handoff.broker.evidence", side_effect=AssertionError("no acquisition")):
        main()
    assert json.loads(output.getvalue()) == draft_contract(request_path, "tech")


def test_draft_contract_rejects_changed_registered_request(new_run):
    request_path, _ = build_request(new_run)
    request_path.write_bytes(request_path.read_bytes() + b"\n")
    with pytest.raises(rc.RunContractError):
        draft_contract(request_path, "tech")


def test_frozen_worker_exchange_write_budget_and_telemetry_binding(new_run):
    request_path, request = build_request(new_run)
    worker = request["launch_plan"][0]["workers"][0]
    packet = request["execution_packets"][worker["packet_index"]]
    task = packet["context_instructions"]
    assert len(worker["task_message"]) < len(task) / 4
    assert worker["task_message"] == packet["task_message"]
    assert "broker_handoff.py" in worker["task_message"]
    assert "--draft-contract" in worker["task_message"]
    assert "at most 3 requests total, never polling" in task
    assert "at most ONE batched read" in task
    assert "persist the complete dynamic draft by tool call 8" in task
    assert "pool-declared/1" in task and "url-path/1" in task
    assert worker["tool_budget"] == {"soft": 20, "hard": 28, "block": "*"}
    assert worker["timeout_ms"] == 1500000
    assert worker["token_budget"] == 150000
    assert worker["cost_budget_usd"] == 0.5
    context = build_agent_context(request_path, "tech")
    assert "draft_schema" in context
    assert context["draft_instructions"] == [task]
    seat = rc.load_manifest(new_run[0])["telemetry"]["reservations"]["supplemental:tech"]
    assert seat["invocation_id"] == "tech" and seat["stage"] == "supplemental"
