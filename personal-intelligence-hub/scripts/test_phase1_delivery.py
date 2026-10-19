import copy
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import article_broker as broker
import run_contract as rc
import supplement_agent as sa
from claim_grounding import validate_registered_claims
from hub_utils import atomic_dump_json
from semantic_agent import _registered_evidence_excerpt, validate_item_grounding
from test_native_article_evidence import new_run, timely_scenario
from test_semantic_readability import native_fixture


@pytest.fixture
def worker_lanes(new_run, monkeypatch):
    result = timely_scenario(new_run, monkeypatch, worker_delivery_version=1)
    result[3].value = new_run[2]
    return result


def test_worker_cli_canary_and_delayed_registration_preserve_authorship(worker_lanes):
    path, request, packets, clock, seal = worker_lanes
    draft = seal("tech")
    completed = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", packets[0]["agent_helper"]["path"],
         "finalize", "--request", str(request), "--gap-id", "tech"],
        capture_output=True, text=True,
        encoding="utf8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    manifest = rc.load_manifest(path)
    assert "tech" in manifest["worker_supplement_finalizations"]
    assert not manifest.get("parent_supplement_finalizations")
    original = draft.read_bytes()
    clock.value += timedelta(seconds=packets[0]["finalization"]["grace_seconds"] + 10)
    sa.validate_canary_delivery(request, "risk")
    risk = seal("risk")
    sa._finalize_with_receipt(request, "risk", worker=True)
    sa.finalize_parent_draft(request, "tech")
    assert draft.read_bytes() == original
    assert not rc.load_manifest(path).get("parent_supplement_finalizations")
    _, aggregate = rc.register_supplement_results(path, request, [draft, risk], publish_drafts=True)
    assert aggregate["child_delivery"]["parent_authored_gaps"] == []
    assert set(aggregate["child_delivery"]["child_authored_gaps"]) == {"tech", "risk"}


@pytest.mark.parametrize("case", ["missing", "tamper", "foreign", "missing_file"])
def test_canary_rejection_is_before_downstream_source_mutation(worker_lanes, case):
    path, request, packets, clock, seal = worker_lanes
    draft = seal("tech")
    if case != "missing":
        sa._finalize_with_receipt(request, "tech", worker=True)
    if case == "tamper":
        draft.write_bytes(draft.read_bytes() + b" ")
    if case == "foreign":
        manifest = rc.load_manifest(path)
        manifest["worker_supplement_finalizations"]["tech"]["gap_id"] = "risk"
        atomic_dump_json(path, manifest)
    if case == "missing_file":
        draft.unlink()
    before = path.read_bytes()
    with pytest.raises(rc.RunContractError):
        broker.operate(request, "risk", "checkpoint")
    assert path.read_bytes() == before
    with pytest.raises(rc.RunContractError):
        sa.build_agent_context(request, "risk")
    with pytest.raises(rc.RunContractError):
        sa.preflight_launch(request, "risk", {"agent": "delegate", "output": False, "context": "fresh"})
    assert path.read_bytes() == before


def test_worker_late_first_finalize_preserves_draft_and_manifest(worker_lanes):
    path, request, packets, clock, seal = worker_lanes
    draft = seal("tech")
    before = path.read_bytes(), draft.read_bytes()
    clock.value += timedelta(seconds=packets[0]["finalization"]["grace_seconds"] + 1)
    with pytest.raises(rc.RunContractError, match="grace expired"):
        sa._finalize_with_receipt(request, "tech", worker=True)
    assert (path.read_bytes(), draft.read_bytes()) == before


def test_parent_fallback_cannot_be_relabelled_as_worker(worker_lanes):
    path, request, _, _, seal = worker_lanes
    draft = seal("tech")
    sa.finalize_parent_draft(request, "tech")
    before = path.read_bytes(), draft.read_bytes()
    with pytest.raises(rc.RunContractError, match="relabelled"):
        sa._finalize_with_receipt(request, "tech", worker=True)
    assert (path.read_bytes(), draft.read_bytes()) == before


def test_worker_journal_crash_recovery_and_immutability(worker_lanes, monkeypatch):
    path, request, packets, clock, seal = worker_lanes
    draft = seal("tech")
    materialize = sa._materialize_parent_draft

    def crash(*args):
        raise OSError("interruption after worker journal commit")

    monkeypatch.setattr(sa, "_materialize_parent_draft", crash)
    with pytest.raises(OSError):
        sa._finalize_with_receipt(request, "tech", worker=True)
    receipt = copy.deepcopy(rc.load_manifest(path)["worker_supplement_finalizations"]["tech"])
    with pytest.raises(rc.RunContractError):
        sa.validate_canary_delivery(request, "risk")
    clock.value += timedelta(seconds=packets[0]["finalization"]["grace_seconds"] + 10)
    monkeypatch.setattr(sa, "_materialize_parent_draft", materialize)
    sa._finalize_with_receipt(request, "tech", worker=True)
    assert rc.file_sha256(draft) == receipt["final_draft_sha256"]
    assert rc.load_manifest(path)["worker_supplement_finalizations"]["tech"] == receipt
    with pytest.raises(rc.RunContractError, match="immutable"), rc.locked_manifest(path) as (manifest, sha):
        manifest["worker_supplement_finalizations"].clear()
        rc.commit_manifest(path, manifest, sha)


def test_registration_cannot_infer_worker_authorship_from_missing_journal(worker_lanes):
    path, request, packets, _, seal = worker_lanes
    first = seal("tech")
    sa._finalize_with_receipt(request, "tech", worker=True)
    second = seal("risk")
    dynamic = rc.load_json(second, {})
    _, assembled = sa.assemble_result(request, "risk", dynamic, _validate_only=True)
    atomic_dump_json(second, assembled)
    before = path.read_bytes(), first.read_bytes(), second.read_bytes()
    with pytest.raises(rc.RunContractError, match="finalization journal"):
        rc.register_supplement_results(path, request, [first, second], publish_drafts=True)
    assert (path.read_bytes(), first.read_bytes(), second.read_bytes()) == before
    assert not any(Path(packet["output_paths"]["result"]).exists() for packet in packets)


def test_new_seal_handoff_is_worker_owned_and_parent_fallback_is_explicit(worker_lanes, capsys):
    import broker_handoff
    import supplement_seal

    path, request, packets, _, seal = worker_lanes
    seal("tech")
    assert supplement_seal.main(["--request", str(request), "--gap-id", "tech"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "sealed_awaiting_worker"
    assert not rc.load_manifest(path).get("parent_supplement_finalizations")
    snapshot = broker.evidence(request, "tech")
    lane = rc.load_json(Path(packets[0]["lane_slice"]["path"]), {})
    assert "Worker runs" in broker_handoff.compact_packet(snapshot, lane, worker_delivery_version=1)["instruction"]
    assert "Parent alone" in broker_handoff.compact_packet(snapshot, lane)["instruction"]
    assert supplement_seal.main(["--request", str(request), "--gap-id", "tech", "--parent-fallback"]) == 0
    capsys.readouterr()
    assert "tech" in rc.load_manifest(path)["parent_supplement_finalizations"]


def test_parent_canary_opens_independent_lane_without_cancelling_it(worker_lanes):
    path, request, _, _, seal = worker_lanes
    first = seal("tech")
    sa.finalize_parent_draft(request, "tech")
    before = path.read_bytes()
    with pytest.raises(rc.RunContractError, match="proven shared infrastructure"):
        rc.reconcile_supplement_progress(path, request, [first], [], unstarted_gap_ids=["risk"])
    assert path.read_bytes() == before
    sa.validate_canary_delivery(request, "risk")
    risk = seal("risk")
    sa._finalize_with_receipt(request, "risk", worker=True)
    _, aggregate = rc.register_supplement_results(path, request, [first, risk], publish_drafts=True)
    assert aggregate["child_delivery"]["parent_authored_gaps"] == ["tech"]
    assert aggregate["child_delivery"]["child_authored_gaps"] == ["risk"]


@pytest.mark.parametrize("level", ["L1", "L2", "L3", "L4"])
def test_policy_three_requires_every_formal_item_evidence(level):
    item = {"intelligence_level": level, "fact": "候选摘要描述了一项未读研究。"}
    with pytest.raises(ValueError, match="requires registered"):
        validate_registered_claims(item, lambda a, b: {}, policy_version=3)
    if level in {"L1", "L2"}:
        validate_registered_claims(item, lambda a, b: {}, policy_version=2)


def test_policy_three_real_body_span_and_complete_fact(tmp_path):
    quote = "The publisher released version 3 and documented its limitations."
    candidate, manifest, _ = native_fixture(tmp_path, "Published on September 23, 2026.\n" + quote)
    manifest["claim_grounding_version"] = 3
    span = _registered_evidence_excerpt(candidate, manifest, quote=quote)
    fact = "发布方发布了版本3，并说明了局限。"
    common = {"status": "grounded", "evidence": quote, "evidence_ref": {
        k: span[k] for k in ("readable_text_sha256", "start", "end")}}
    item = {"intelligence_level": "L2", "fact": fact, "claim_grounding": {
        "basis": "registered source", "claims": [
            {**common, "kind": "fact", "statement": fact},
            {**common, "kind": "number", "statement": "版本3", "value": "3"},
        ]}}
    validate_item_grounding(item, candidate, manifest)
    for change in ("quote", "complete_fact", "number"):
        changed = copy.deepcopy(item)
        if change == "quote":
            changed["claim_grounding"]["claims"][0]["evidence"] = "Unrelated navigation"
        elif change == "complete_fact":
            changed["claim_grounding"]["claims"][0]["statement"] = "只覆盖部分事实"
        else:
            changed["claim_grounding"]["claims"].pop()
        with pytest.raises(rc.RunContractError, match="registered claim grounding failed"):
            validate_item_grounding(changed, candidate, manifest)


def test_explicit_legacy_broker_prepare_keeps_its_supported_policy(tmp_path):
    from test_run_daily_broker_entry import prepare_fixture

    prepared = prepare_fixture(tmp_path, 0, 2)
    manifest = rc.load_manifest(prepared.manifest_path)
    assert manifest["claim_grounding_version"] == 2
    request = rc.load_json(prepared.supplement_request_path, {})
    assert "worker_delivery_version" not in request


@pytest.mark.parametrize("version", [True, 0, 4])
def test_unknown_grounding_policy_is_rejected_before_run_creation(tmp_path, version):
    with pytest.raises(rc.RunContractError, match="unsupported claim grounding"):
        rc.create_run(runtime_dir=tmp_path, claim_grounding_version=version)
    assert list(tmp_path.iterdir()) == []
