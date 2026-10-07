"""Path binding for RAW broker.evidence proofs (not the enriched CLI envelope)."""

from copy import deepcopy

import article_broker as broker
import pytest
import run_contract as rc
from broker_handoff import bind_registered_proof_paths, compact_packet


def fixture():
    ledger = {"events": [
        {"kind": "fetch_recorded", "id": "fetch-1", "proof_path": "registered-body.json", "proof_sha256": "a" * 64},
        {"kind": "sealed", "at": "2026-10-01T01:01:00+00:00"},
    ]}
    raw = {"id": "fetch-1", "proof_sha256": "a" * 64, "metadata": {"dates": [], "article_core": False},
           "access": {"requested_url": "https://example.org/article", "coverage": "full"},
           "body_text": "Retained body " * 400, "body_text_sha256": "b" * 64, "body_text_truncated": False}
    snapshot = {"completed_at": ledger["events"][-1]["at"], "next_action": {"action": "sealed", "stop_reason": "url_budget_exhausted"},
                "proofs": [raw], "broker_evidence_sha256": broker.digest(ledger), "request_sha256": "c" * 64,
                "gap_id": "tech", "started_at": "2026-10-01T01:00:00+00:00", "access_log": [raw["access"]],
                "executed_queries": [], "required_bound_candidate_ids": []}
    return snapshot, ledger


def test_raw_snapshot_path_is_bound_only_from_registered_hash_matched_event():
    snapshot, ledger = fixture()
    before = deepcopy((snapshot, ledger))
    assert "proof_path" not in snapshot["proofs"][0]
    bound = bind_registered_proof_paths(snapshot, ledger)
    packet = compact_packet(bound, {}, preview_chars=20)
    assert packet["proofs"][0]["proof_path"] == ledger["events"][0]["proof_path"]
    assert packet["proofs"][0]["broker_body_proof_sha256"] == ledger["events"][0]["proof_sha256"]
    assert packet["proofs"][0]["preview_truncated"] is True
    assert packet["proofs"][0]["native_body_truncated"] is False
    assert packet["proofs"][0]["access_check"]["coverage"] == "full"
    assert (snapshot, ledger) == before


@pytest.mark.parametrize("bad", ["missing_path", "bad_hash", "duplicate_ref", "clock_mismatch", "ledger_changed"])
def test_path_binding_fails_closed_without_path_guessing(bad):
    snapshot, ledger = fixture()
    if bad == "missing_path":
        ledger["events"][0].pop("proof_path")
    elif bad == "bad_hash":
        ledger["events"][0]["proof_sha256"] = "d" * 64
    elif bad == "duplicate_ref":
        ledger["events"].insert(1, deepcopy(ledger["events"][0]))
    elif bad == "clock_mismatch":
        snapshot["completed_at"] = "2026-10-01T01:02:00+00:00"
    if bad != "ledger_changed":
        snapshot["broker_evidence_sha256"] = broker.digest(ledger)
    else:
        ledger["events"][0]["proof_path"] = "changed-path.json"
    with pytest.raises(rc.RunContractError):
        bind_registered_proof_paths(snapshot, ledger)
