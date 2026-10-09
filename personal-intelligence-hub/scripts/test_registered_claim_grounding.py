import hashlib

import pytest

from claim_grounding import validate_registered_claims
from run_contract import RunContractError
from semantic_agent import _registered_evidence_excerpt, read_agent_evidence, validate_item_grounding
from test_semantic_readability import native_fixture


def test_critical_ledger_is_required_but_legacy_is_readable():
    with pytest.raises(ValueError, match="requires registered"):
        validate_registered_claims({"intelligence_level": "L3", "fact": "成本降低90%"}, lambda a, b: {})
    validate_item_grounding({"intelligence_level": "L3"}, {}, {})


def test_source_quote_and_numeric_claim_are_bound():
    quote = "The measured cost reduction was 90%."
    digest = hashlib.sha256(quote.encode()).hexdigest()
    claim = {"kind": "number", "statement": "成本降低90%", "status": "grounded", "value": "90%",
             "evidence": quote, "evidence_ref": {"readable_text_sha256": digest, "start": 0, "end": len(quote)}}
    item = {"intelligence_level": "L3", "fact": "成本降低90%", "claim_grounding": {"basis": "registered", "claims": [claim]}}
    span = {"status": "available", "readable_text_sha256": digest, "start": 0, "end": len(quote),
            "text": quote, "excerpt_truncated": False}
    validate_registered_claims(item, lambda a, b: span)
    for changed in ({"text": "Unrelated evidence"}, {"readable_text_sha256": "0" * 64},
                    {"end": len(quote) - 1}, {"excerpt_truncated": True}):
        with pytest.raises(ValueError, match="does not match"):
            validate_registered_claims(item, lambda a, b: {**span, **changed})
    item["fact"] += "，样本120例"
    with pytest.raises(ValueError, match="without registered bindings"):
        validate_registered_claims(item, lambda a, b: span)


def test_number_in_fact_without_number_in_source_is_refused():
    quote = "This source reports no measured reduction."
    digest = hashlib.sha256(quote.encode()).hexdigest()
    item = {"intelligence_level": "L3", "fact": "成本降低90%", "claim_grounding": {"basis": "registered", "claims": [
        {"kind": "number", "statement": "成本降低90%", "status": "grounded", "value": "90%", "evidence": quote,
         "evidence_ref": {"readable_text_sha256": digest, "start": 0, "end": len(quote)}}]}}
    with pytest.raises(ValueError, match="not supported"):
        validate_registered_claims(item, lambda a, b: {"status": "available", "readable_text_sha256": digest,
                                                       "start": 0, "end": len(quote), "text": quote, "excerpt_truncated": False})


def test_registered_tail_span_is_readable_without_network(tmp_path):
    body = "Published on September 23, 2026.\n\n" + "Long article body. " * 420 + "Measured cost reduction was 90%."
    candidate, manifest, _ = native_fixture(tmp_path, body)
    start = body.index("Measured cost")
    span = _registered_evidence_excerpt(candidate, manifest, start=start, end=len(body))
    assert span["text"] == body[start:]
    assert span["start"] == start and span["end"] == len(body)
    assert span["excerpt_truncated"] is False
    located = _registered_evidence_excerpt(candidate, manifest, quote=body[start:])
    assert located == span
    with pytest.raises(RunContractError, match="exactly once"):
        _registered_evidence_excerpt(candidate, manifest, quote="Long article body. ")
    for start, end in ((-1, 8), (10, 5), (0, len(body) + 1)):
        with pytest.raises(RunContractError, match="outside"):
            _registered_evidence_excerpt(candidate, manifest, start=start, end=end)


def test_version_two_reads_real_bound_proof_and_refuses_forgery(tmp_path):
    body = "Published on September 23, 2026.\nMeasured cost reduction was 90%."
    candidate, manifest, _ = native_fixture(tmp_path, body)
    manifest["claim_grounding_version"] = 2
    quote = "Measured cost reduction was 90%."
    span = _registered_evidence_excerpt(candidate, manifest, quote=quote)
    item = {"intelligence_level": "L3", "fact": "成本降低90%", "claim_grounding": {"basis": "registered", "claims": [
        {"kind": "number", "statement": "成本降低90%", "status": "grounded", "value": "90%", "evidence": quote,
         "evidence_ref": {key: span[key] for key in ("readable_text_sha256", "start", "end")}}]}}
    validate_item_grounding(item, candidate, manifest)
    item["claim_grounding"]["claims"][0]["evidence"] = "An unrelated sentence claiming 90%."
    with pytest.raises(RunContractError, match="does not match"):
        validate_item_grounding(item, candidate, manifest)
    del item["claim_grounding"]
    with pytest.raises(RunContractError, match="requires registered"):
        validate_item_grounding(item, candidate, manifest)


def test_evidence_reader_refuses_unregistered_candidate(tmp_path, monkeypatch):
    candidate, manifest, _ = native_fixture(tmp_path, "Published on September 23, 2026.\nArticle content.")
    candidate["candidate_id"] = "registered"
    monkeypatch.setattr("semantic_agent._load_packet", lambda p: (None, {}, {}, manifest))
    monkeypatch.setattr("semantic_agent._eligible_candidates", lambda r, m: [candidate])
    with pytest.raises(RunContractError, match="eligible pool"):
        read_agent_evidence(tmp_path / "request.json", "unregistered", 0, 5)
