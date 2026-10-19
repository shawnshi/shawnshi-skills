"""Offline selection/audit regression; production validators are exercised by preview."""
import json
import subprocess

import pytest
from recovery_lifecycle import frozen_replay


STUB = '''
import json
from pathlib import Path

def load_manifest(path):
    return json.loads(Path(path).read_text(encoding="utf8"))

def register_supplement_results(manifest_path, request_path, paths, *, _reconciled_failures):
    m = load_manifest(manifest_path)
    if m.get("attempt_write"):
        Path(manifest_path).with_name("forbidden.txt").write_text("no", encoding="utf8")
    expected = json.loads(Path(m["stages"]["supplemental"]["artifact_path"]).read_text(encoding="utf8"))
    actual = []
    for path in paths:
        path = Path(path)
        value = json.loads(path.read_text(encoding="utf8"))
        if value["status"] == "failed":
            assert path.name.endswith(".failure.json")
            assert _reconciled_failures[path.resolve()] == value
        else:
            assert not path.name.endswith(".failure.json")
        actual.append(value)
    assert actual == expected["results"]
    return Path(m["stages"]["supplemental"]["artifact_path"]), expected

def review_input_bundle_sha256(m):
    return "b" * 64

def registered_candidate_lineage(m):
    return ["unit-test-lineage"]
'''


def setup_source(tmp_path, failed=True):
    scripts = tmp_path / "personal-intelligence-hub" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run_contract.py").write_text(STUB, encoding="utf8")
    result = {"gap_id": "risk", "status": "failed" if failed else "completed"}
    if failed:
        result["failure_kind"] = "infrastructure"
    final = tmp_path / "supplement_risk.json"
    receipt = final.with_suffix(".failure.json") if failed else final
    receipt.write_text(json.dumps(result), encoding="utf8")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({"execution_packets": [{
        "assigned_gap_ids": ["risk"], "output_paths": {"result": str(final)}
    }]}), encoding="utf8")
    aggregate_path = tmp_path / "aggregate.json"
    aggregate_path.write_text(json.dumps({"results": [result]}), encoding="utf8")
    manifest = {"artifacts": {"supplement_request": {"artifact_path": str(request_path)}},
                "stages": {"supplemental": {"status": "degraded" if failed else "completed",
                                             "artifact_path": str(aggregate_path),
                                             "artifact_sha256": "a" * 64}}}
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf8")
    return path, receipt


def test_replay_uses_registered_failure_without_normal_result(tmp_path):
    path, receipt = setup_source(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert frozen_replay(path)["status"] == "valid"
    assert not (tmp_path / "supplement_risk.json").exists()
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_replay_normal_result_unchanged(tmp_path):
    path, _ = setup_source(tmp_path, failed=False)
    assert frozen_replay(path)["status"] == "valid"


def test_replay_rejects_changed_failure_bytes(tmp_path):
    path, receipt = setup_source(tmp_path)
    data = json.loads(receipt.read_text(encoding="utf8"))
    data["failure_reason"] = "unregistered mutation"
    receipt.write_text(json.dumps(data), encoding="utf8")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        frozen_replay(path)
    assert "registered reconciliation receipt changed" in caught.value.stderr


def test_replay_does_not_fallback_to_normal_result(tmp_path):
    path, receipt = setup_source(tmp_path)
    receipt.rename(tmp_path / "supplement_risk.json")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        frozen_replay(path)
    assert "supplement_risk.failure.json" in caught.value.stderr


def test_frozen_replay_still_denies_writes(tmp_path):
    path, _ = setup_source(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf8"))
    manifest["attempt_write"] = True
    path.write_text(json.dumps(manifest), encoding="utf8")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        frozen_replay(path)
    assert "read-only frozen replay denied write" in caught.value.stderr
    assert not (tmp_path / "forbidden.txt").exists()
