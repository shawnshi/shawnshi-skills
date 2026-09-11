"""Real new frozen bundles: direct parent registration, no helper/consumer bypass mocks."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import run_contract as rc
from history_manager import generate_event_id


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def bound_run(tmp_path):
    now = datetime.now(timezone.utc)
    started = now - timedelta(seconds=120)
    manifest_path, manifest = rc.create_run(
        runtime_dir=tmp_path, skill_path=Path(__file__).resolve().parents[1] / "SKILL.md", now=started)
    root = Path(manifest["run_dir"])
    baseline = root / "baseline.json"
    dump(baseline, {"items": []})
    rc.record_stage(manifest_path, "baseline", "completed", artifact_path=baseline, now=started)
    pool_path = root / "pool.json"
    pool = {"items": [{"url": "https://example.org/B", "title": "Multimodal release", "source": "Example",
        "source_type": "primary", "published_at": now.date().isoformat(),
        "published_at_source": "rss_published", "provisional_domain": "technology", "lane": "Ranger"}]}
    pool["items"][0]["candidate_id"] = rc.candidate_ref(pool["items"][0]["url"])
    pool["items"][0]["candidate_object_sha256"] = rc.candidate_object_hash(pool["items"][0])
    dump(pool_path, pool)
    rc.record_run_artifact(manifest_path, "candidate_pool", pool_path, now=started)
    focus_path = root / "focus.json"
    dump(
        focus_path,
        rc.load_json(
            Path(__file__).resolve().parents[1] / "references" / "strategic_focus.json", {}
        ),
    )
    rc.record_run_artifact(manifest_path, "focus_config", focus_path, now=started)
    request_path, request = rc.build_supplement_request(manifest_path, [
        {"gap_id": gap, "lane": lane, "query_scope": "release", "verify_bound_candidates": True}
        for gap, lane in [("tech", "TechRadar"), ("ranger", "Ranger")]], now=started)
    pool = rc.load_json(pool_path, {})
    paths, results = [], []
    for packet in request["execution_packets"]:
        gap = packet["assigned_gap_ids"][0]
        access = {"status": "verified", "checked_at": (now-timedelta(seconds=2)).isoformat(),
            "method": "http_get", "requested_url": "https://example.org/B", "final_url": "https://example.org/C",
            "http_status": 200, "failure_class": "none", "error_code": None}
        identity = {"key_version": "1", "primary_domain": "technology", "actor": "Example",
                    "action": "published", "object": "Release", "event_date": now.date().isoformat()}
        candidate = {"url": access["requested_url"], "title": "Release", "source": "Example",
            "published_at": now.date().isoformat(), "published_at_source": "rss_published",
            "retrieved_at": access["checked_at"], "primary_domain": "technology", "source_type": "primary",
            "summary": "Registered release metadata", "access_check": deepcopy(access),
            "identity_quality": "semantic", "event_identity": identity, "event_id": generate_event_id(identity)}
        candidate["candidate_id"] = rc.candidate_ref(candidate["url"])
        candidate["candidate_object_sha256"] = rc.candidate_object_hash(candidate)
        result = {"contract_version": "supplement-result/1.0", "run_id": request["run_id"],
            "request_sha256": rc.file_sha256(request_path), "baseline_sha256": request["baseline_sha256"],
            "candidate_pool_sha256": request["candidate_pool_sha256"], "gap_id": gap,
            "lane": packet["assigned_lanes"][0], "status": "completed", "executed_queries": ["release"],
            "access_log": [access], "candidates": [candidate], "bound_candidate_decisions": [
                {"candidate_id": candidate["candidate_id"], "decision": "registered", "reason": "Existing metadata"}],
            "coverage": {"attempted": 1, "succeeded": 1, "failed": 0}, "confidence": "medium",
            "data_provenance": {"request_sha256": rc.file_sha256(request_path),
                "candidate_pool_sha256": request["candidate_pool_sha256"],
                "access_log_sha256": hashlib.sha256(rc.canonical_json_bytes([access])).hexdigest()},
            "turns_used": 1, "halt_condition_met": True,
            "started_at": (now-timedelta(seconds=3)).isoformat(), "completed_at": (now-timedelta(seconds=1)).isoformat()}
        path = Path(packet["output_paths"]["draft"])
        paths.append(path)
        results.append(result)
    return manifest_path, request_path, request, pool, paths, results, now


def register(bound):
    manifest, request_path, _, _, paths, results, now = bound
    for path, result in zip(paths, results, strict=True):
        dump(path, result)
    return rc.register_supplement_results(manifest, request_path, paths, publish_drafts=True, now=now)


def test_parent_builds_exact_attempt_input_output_edges(bound_run):
    manifest_path, request_path, request, pool, _, original, _ = bound_run
    _, aggregate = register(bound_run)
    assert request["candidate_date_evidence_version"] == 1
    envelope = aggregate["candidate_date_evidence"]
    assert envelope == rc.build_candidate_date_evidence(request, rc.file_sha256(request_path), pool, aggregate["results"])
    for record in envelope["records"]:
        result = next(r for r in aggregate["results"] if r["gap_id"] == record["attempt"]["gap_id"])
        assert record["attempt"] == {"request_sha256": rc.file_sha256(request_path), "gap_id": result["gap_id"], "access_log_index": 0}
        assert record["inputs"] == [{"source_object_sha256": hashlib.sha256(rc.canonical_json_bytes(pool["items"][0])).hexdigest(),
                                     "candidate_object_sha256": rc.candidate_object_hash(pool["items"][0])}]
        assert record["inputs"][0]["source_object_sha256"] != record["inputs"][0]["candidate_object_sha256"]
        assert record["output_candidate_object_sha256"] == rc.candidate_object_hash(result["candidates"][0])
    assert [r["access_log"] for r in aggregate["results"]] == [r["access_log"] for r in sorted(original, key=lambda r:r["gap_id"])]
    ownership = rc.candidate_date_ownership(rc.load_manifest(manifest_path), pool, aggregate)
    assert rc.candidate_date_owned(aggregate["results"][0]["candidates"][0], ownership)
    assert not rc.candidate_date_owned(pool["items"][0], ownership)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "mismatch", "unknown", "retrieved_at", "borrowed"])
def test_parent_bypass_helper_rejects_bad_decisions_and_metadata(bound_run, mutation):
    result = bound_run[5][0]
    if mutation == "missing":
        result.pop("bound_candidate_decisions")
    elif mutation == "duplicate":
        result["bound_candidate_decisions"] *= 2
    elif mutation == "foreign":
        result["bound_candidate_decisions"][0]["candidate_id"] = rc.candidate_ref("https://foreign.example/")
    elif mutation == "mismatch":
        result["bound_candidate_decisions"][0]["decision"] = "date_disqualified"
    elif mutation == "borrowed":
        result["candidates"][0]["access_check"]["requested_url"] = "https://foreign.example/"
    else:
        result["candidates"][0]["published_at_source"] = mutation
    manifest_bytes = bound_run[0].read_bytes()
    with pytest.raises(rc.RunContractError):
        register(bound_run)
    assert bound_run[0].read_bytes() == manifest_bytes
    for path, value in zip(bound_run[4], bound_run[5], strict=True):
        assert json.loads(path.read_text(encoding="utf-8")) == value
        assert not path.with_name(path.name.replace(".draft", "")).exists()


@pytest.mark.parametrize("mutation", ["missing", "version", "boolversion", "foreign_attempt", "index", "boolindex", "source_hash", "input_hash", "output_hash"])
def test_marked_envelope_corruption_never_falls_back(bound_run, mutation):
    _, aggregate = register(bound_run)
    manifest = rc.load_manifest(bound_run[0])
    bad = deepcopy(aggregate)
    record = bad["candidate_date_evidence"]["records"][0]
    if mutation == "missing":
        bad.pop("candidate_date_evidence")
    elif mutation == "version":
        bad["candidate_date_evidence"]["contract_version"] = 2
    elif mutation == "boolversion":
        bad["candidate_date_evidence"]["contract_version"] = True
    elif mutation == "foreign_attempt":
        record["attempt"]["request_sha256"] = "f"*64
    elif mutation == "index":
        record["attempt"]["access_log_index"] = 9
    elif mutation == "boolindex":
        record["attempt"]["access_log_index"] = False
    elif mutation == "source_hash":
        record["inputs"][0]["source_object_sha256"] = "f"*64
    elif mutation == "input_hash":
        record["inputs"][0]["candidate_object_sha256"] = "f"*64
    else:
        record["output_candidate_object_sha256"] = "f"*64
    with pytest.raises(rc.RunContractError, match="envelope"):
        rc.candidate_date_ownership(manifest, bound_run[3], bad)


def test_registered_cross_lane_rejection_blocks_timestamp_repackaging(bound_run):
    result = bound_run[5][0]
    result.update(status="degraded", failure_kind="published_at_conflict", failure_reason="Conflicting registered date metadata")
    result["candidates"] = []
    result["bound_candidate_decisions"][0]["decision"] = "date_disqualified"
    other = bound_run[5][1]["candidates"][0]
    # Keep retrieval within result execution interval; changed access also changes object hash.
    other["retrieved_at"] = bound_run[5][1]["completed_at"]
    _, aggregate = register(bound_run)
    ownership = rc.candidate_date_ownership(rc.load_manifest(bound_run[0]), bound_run[3], aggregate)
    assert not rc.candidate_date_owned(other, ownership)
    lineage = rc.registered_candidate_lineage(rc.load_manifest(bound_run[0]))
    assert all(not entry["eligible_hashes"] for entry in lineage.values())


@pytest.mark.parametrize("same_day", [False, True])
def test_same_input_positive_dates_conflict_without_poisoning_unrelated_A(bound_run, same_day):
    first, second = bound_run[5]
    candidate = second["candidates"][0]
    day = bound_run[6].date() - timedelta(days=0 if same_day else 1)
    candidate["published_at"] = day.isoformat() + "T01:30:00+00:00"
    candidate["published_at_source"] = "source page"
    candidate["event_identity"]["event_date"] = day.isoformat()
    candidate["event_id"] = generate_event_id(candidate["event_identity"])
    independent = deepcopy(first["candidates"][0])
    independent["url"] = "https://independent.example/A"
    independent["candidate_id"] = rc.candidate_ref(independent["url"])
    independent["access_check"].update(requested_url=independent["url"], final_url=independent["url"])
    first["candidates"].append(independent)
    first["access_log"].append(deepcopy(independent["access_check"]))
    first["coverage"].update(attempted=2, succeeded=2)
    first["data_provenance"]["access_log_sha256"] = hashlib.sha256(rc.canonical_json_bytes(first["access_log"])).hexdigest()
    _, aggregate = register(bound_run)
    ownership = rc.candidate_date_ownership(rc.load_manifest(bound_run[0]), bound_run[3], aggregate)
    outputs = [c for r in aggregate["results"] for c in r["candidates"]]
    assert all(rc.candidate_date_owned(c, ownership) == (same_day or c["url"] == independent["url"]) for c in outputs)
    lineage = rc.registered_candidate_lineage(rc.load_manifest(bound_run[0]))
    assert bool(lineage[candidate["candidate_id"]]["eligible_hashes"]) == same_day
    assert lineage[independent["candidate_id"]]["eligible_hashes"]
