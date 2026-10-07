"""Literal query evidence and provider-aware CLI assembly regression checks."""
from copy import deepcopy
import json

import pytest
import receipt_assemble as ra
from query_proof import build_query_proof, validate_query_proof
from test_receipt_assemble import QUERY_HEADER


@pytest.mark.parametrize("raw", ["工具原文\r\n第二行", "x" * 3000, "[sources: []] no result"])
def test_literal_proof_roundtrip(raw):
    proof = build_query_proof(raw)
    validate_query_proof(proof)
    assert proof["raw_response"] == raw
    assert raw.startswith(proof["text"])
    assert proof["coverage"] == ("full" if len(raw) <= 2048 else "prefix")


@pytest.mark.parametrize("field,value", [
    ("text", "parent paraphrase"), ("raw_sha256", "0" * 64),
    ("coverage", "prefix"), ("raw_response", "changed original"),
])
def test_literal_proof_rejects_tampering(field, value):
    proof = build_query_proof("actual returned text")
    proof[field] = value
    with pytest.raises(ValueError):
        validate_query_proof(proof)


def test_provider_cli_assembly_preserves_raw_crlf(tmp_path):
    header = deepcopy(QUERY_HEADER)
    header["provider"] = "openai"
    hp, source, out = [tmp_path / p for p in ("header.json", "returned.txt", "receipt.json")]
    hp.write_text(json.dumps(header), encoding="utf8")
    raw = "Actual result\r\nhttps://example.org/a 中文"
    source.write_bytes(raw.encode("utf8"))
    assert ra.main(["--kind", "query", "--header", str(hp),
                    "--query-response", str(source), "--out", str(out)]) == 0
    receipt = json.loads(out.read_text(encoding="utf8"))
    assert receipt["provider"] == "openai"
    assert receipt["proof_subset"]["raw_response"] == raw
    assert receipt["proof_subset"]["text"] == raw
    validate_query_proof(receipt["proof_subset"])


def test_provider_receipt_without_literal_source_is_rejected():
    with pytest.raises(ra.AssembleError, match="literal query proof"):
        ra.assemble_query({**deepcopy(QUERY_HEADER), "provider": "openai"})


def test_empty_or_oversized_original_is_not_silent_no_data():
    for raw in ("", " " , "x" * 65000):
        with pytest.raises(ValueError):
            build_query_proof(raw)


@pytest.mark.parametrize("declared", [False, True])
def test_second_angle_preserves_last_url_without_reinterpreting_legacy(declared):
    from datetime import datetime, timezone
    from article_broker import next_action
    now = datetime.now(timezone.utc)
    at = now.isoformat()
    arguments = {"query": "first"}
    if declared:
        arguments["provider"] = "openai"
    events = [
        {"kind": "query_reserved", "id": "query-1", "query": "first", "arguments": arguments, "at": at},
        {"kind": "query_recorded", "receipt": {"outcome": "matched", "results": [{"url": "https://example.org/article", "title": "Article"}]}, "at": at},
    ]
    manifest = {"article_broker_evidence": {"tech": {"events": events}}}
    gap = {"gap_id": "tech", "lane": "TechRadar", "max_urls": 1, "max_queries": 2, "max_duration_seconds": 600}
    lane = {"candidates": [], "required_bound_candidate_ids": [], "window": {"start": "2026-10-01", "end": "2026-10-02"}}
    first = next_action(manifest, {"article_broker_version": 3}, gap, lane, [], now=now)
    assert first["action"] == ("search_different" if declared else "fetch_discovered")
    if declared:
        assert first["stop_reason"] == "retain_url_for_second_query"
        events.extend([
            {"kind": "query_reserved", "id": "query-2", "query": "second", "arguments": {"provider": "openai"}, "at": at},
            {"kind": "query_recorded", "receipt": {"outcome": "empty", "results": []}, "at": at},
        ])
        second = next_action(manifest, {"article_broker_version": 3}, gap, lane, [], now=now)
        assert second["action"] == "fetch_discovered"
        assert second["remaining_queries"] == 0
        assert second["remaining_urls"] == 1
