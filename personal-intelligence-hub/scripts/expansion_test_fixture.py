"""Registered, real-gate fixtures for expansion tests (no validator mocks)."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from run_contract import (
    build_review_request, candidate_object_hash, canonical_json_bytes,
    create_run, file_sha256, load_manifest, record_stage, validate_semantic_draft,
)
from test_run_contract import RunContractTests, cloned_v14_payload, candidate_ref, item_hash
from history_manager import generate_event_id


def registered_selection(test_case, count):
    fixture = RunContractTests()
    fixture.setUp()
    test_case.addCleanup(fixture.doCleanups)
    manifest_path, manifest = create_run(
        runtime_dir=fixture.runtime_dir, skill_path=fixture.skill_file,
        report_date="2026-08-10", timezone_name="Asia/Shanghai", window_days=3,
        topic="技术与医疗数字化", region="中国、美国与全球", now=fixture.now,
        run_id="expansion-real-gate",
    )
    baseline = fixture.runtime_dir / "baseline.json"
    baseline.write_text('{"items": []}', encoding="utf-8")
    record_stage(manifest_path, "baseline", "degraded", artifact_path=baseline,
                 metadata={"coverage": {"source_attempted": 10, "source_succeeded": 8,
                     "source_failed": 2, "raw_candidates": 10, "dated_candidates": 9,
                     "reasons": []}}, now=fixture.now)
    fixture.bind_history(manifest_path)
    core = cloned_v14_payload()
    core.update({key: manifest[key] for key in ("run_id", "report_date", "topic", "region", "window")})
    template = core["top_10"][0]
    items, candidates, dispositions = [], [], []
    for index in range(count):
        item = deepcopy(template)
        url = f"https://example.org/verified-{index}"
        item.update(url=url, candidate_refs=[candidate_ref(url)])
        item["access_check"].update(requested_url=url, final_url=url)
        item["event_identity"]["object"] = f"clinical AI evaluation {index}"
        item["event_id"] = generate_event_id(item["event_identity"])
        candidate = {key: deepcopy(item[key]) for key in (
            "url", "title", "source", "published_at", "published_at_source", "access_check")}
        candidate["candidate_id"] = item["candidate_refs"][0]
        candidate["candidate_object_sha256"] = candidate_object_hash(candidate)
        candidates.append(candidate)
        items.append(item)
        dispositions.append({"candidate_id": candidate["candidate_id"], "url": url,
                             "source_type": "primary", "reason": "retained"})
    fixture.bind_candidates(manifest_path, candidates)
    supplement = fixture.runtime_dir / "supplement.json"
    supplement.write_text('{"coverage":{"attempted":0,"succeeded":0,"failed":0},"results":[]}', encoding="utf-8")
    record_stage(manifest_path, "supplemental", "completed", artifact_path=supplement, now=fixture.now)
    _, request = build_review_request(manifest_path, None, "semantic", now=fixture.now)
    core["top_10"] = items
    core["candidate_funnel"] = {"observed": count, "terminal_dispositions": {"retained": count},
        "quality_gate_reasons": {}, "candidate_dispositions": dispositions}
    technology_target = round(count * 0.6)
    core["mix"]["target_counts"] = {"technology": technology_target, "healthcare_digital": count - technology_target}
    core["mix"]["actual_counts"] = {"technology": 0, "healthcare_digital": count}
    access_log = [item["access_check"] for item in items]
    lineage = [{"output_item_sha256": item_hash(item), "inputs": [{
        "candidate_ref": candidate["candidate_id"],
        "candidate_object_sha256": candidate["candidate_object_sha256"]}]} for item, candidate in zip(items, candidates)]
    core["pipeline"]["semantic_review"].update(
        reviewed_item_hashes=[item_hash(item) for item in items], lineage_bindings=lineage,
        verified_access_count=count,
    )
    refined = Path(request["execution_packet"]["output_paths"]["refined_core"])
    refined.write_text(json.dumps(core), encoding="utf-8")
    manifest = load_manifest(manifest_path)
    receipt = {"contract_version": "review-receipt/1.0", "run_id": manifest["run_id"],
        "review_kind": "semantic", "status": "passed", "reviewer_kind": "semantic_model",
        "reviewer_id": request["reviewer_id"], "invocation_id": request["invocation_id"],
        "challenge": request["challenge"],
        "request_sha256": manifest["artifacts"]["semantic_review_request"]["artifact_sha256"],
        "baseline_sha256": manifest["stages"]["baseline"]["artifact_sha256"],
        "input_bundle_sha256": request["input_bundle_sha256"], "access_log": access_log,
        "data_provenance": {"input_bundle_sha256": request["input_bundle_sha256"],
            "access_log_sha256": hashlib.sha256(canonical_json_bytes(access_log)).hexdigest()},
        "output_sha256": file_sha256(refined), "reviewed_item_hashes": [item_hash(item) for item in items],
        "lineage_bindings": lineage, "turns_used": 1, "halt_condition_met": True,
        "completed_at": fixture.now.isoformat()}
    receipt_path = Path(request["execution_packet"]["output_paths"]["review_receipt"])
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    validate_semantic_draft(manifest_path, refined, receipt_path)
    return manifest_path, refined, receipt_path
