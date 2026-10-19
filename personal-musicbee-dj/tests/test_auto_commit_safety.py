"""Generated-media regressions; never access the real music library."""
import hashlib
import json
import os

import pytest

from test_tag_completion import media, task, research_rows
from src.core.tag_inventory import codec
from src.core.tag_writer import read_results
from src.tag_completion import (
    apply_batch, auto_commit_batch, import_result, review_batch, verify_task,
)


def auto_inputs(tmp_path, root, sources):
    work, records = task(tmp_path, root, sources)
    result_path = tmp_path / "auto-result.json"
    result_path.write_text(json.dumps(research_rows(records)), encoding="utf-8")
    updates = read_results(result_path, {r["path"]: r for r in records})
    review = {
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "run_reference": "synthetic-settled-run",
        "decisions": [
            {"file": path, "field": field, "decision": "approve",
             "note": "Synthetic semantic approval; not real music evidence",
             "url": "https://example.org/fixture", "recording_match": True}
            for path, fields in updates.items() for field in fields
        ],
    }
    review_path = tmp_path / "auto-parent-review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return work, records, result_path, review_path


def test_auto_requires_semantic_review_before_import(media, tmp_path):
    root, make = media
    source = make()
    work, _, result_path, review_path = auto_inputs(tmp_path, root, [source])
    before = source.read_bytes()
    review = json.loads(review_path.read_text())
    review["decisions"][0]["recording_match"] = False
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="recording|version"):
        auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert source.read_bytes() == before
    assert not (work / "batches/batch-0001/result.json").exists()
    assert not (work / "backups").exists()
    with pytest.raises(ValueError, match="run reference"):
        auto_commit_batch(work, "batch-0001", result_path, "", review_path)


def test_auto_honors_rejection_without_fabricating_approval(media, tmp_path):
    root, make = media
    source = make()
    work, _, result_path, review_path = auto_inputs(tmp_path, root, [source])
    before = source.read_bytes()
    review = json.loads(review_path.read_text())
    for decision in review["decisions"]:
        decision["decision"] = "reject"
        decision["note"] = "Synthetic insufficient evidence"
    review_path.write_text(json.dumps(review))
    outcome = auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert outcome["status"] == "auto_committed"
    assert outcome["approved_fields"] == 0
    assert outcome["rejected_fields"] == len(review["decisions"])
    assert outcome["applied_files"] == 0
    assert source.read_bytes() == before
    assert json.loads((work / "batches/batch-0001/review.json").read_text()) == review
    assert not (work / "verification_summary.json").exists()
    report = json.loads((work / "batches/batch-0001/verification_summary.json").read_text())
    assert not report["full_task_complete"]


def test_auto_is_one_bounded_slice_and_checks_resume_identity(media, tmp_path):
    root, make = media
    sources = [make() for _ in range(6)]
    work, _, result_path, review_path = auto_inputs(tmp_path, root, sources)
    first = auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert first["status"] == "applying"
    assert first["applied_files"] == 5
    assert first["verified_commits"] == 5
    second = auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert second["status"] == "auto_committed"
    assert second["applied_files"] == 1
    assert second["verified_commits"] == 6
    result_path.write_bytes(result_path.read_bytes() + b"\n")
    review = json.loads(review_path.read_text())
    review["result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="SHA256 changed"):
        auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)


def test_apply_preserves_original_mtime_baseline(media, tmp_path):
    root, make = media
    source = make()
    work, records, result_path, review_path = auto_inputs(tmp_path, root, [source])
    imported = import_result(work, "batch-0001", result_path)
    review_batch(work, "batch-0001", imported["result_sha256"], review_path)
    before = source.read_bytes()
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    with pytest.raises(ValueError, match="Concurrent modification since scan"):
        apply_batch(work, "batch-0001", imported["result_sha256"])
    assert source.read_bytes() == before
    assert records[0]["mtime_ns"] != source.stat().st_mtime_ns


def test_verify_reports_drift_without_rewriting_receipt(media, tmp_path):
    root, make = media
    source = make()
    work, _, result_path, review_path = auto_inputs(tmp_path, root, [source])
    auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    receipt_path = next((work / "backups").glob("*.json"))
    receipt = receipt_path.read_bytes()
    audio = codec().File(source)
    audio["COMMENT"] = ["Concurrent non-target mutation"]
    audio.save()
    report = verify_task(work)
    assert not report["all_checked_commits_valid"]
    assert report["receipt_failures"] >= 1
    assert receipt_path.read_bytes() == receipt
    with pytest.raises(ValueError, match="reconciliation"):
        auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)


def test_review_replacement_between_validation_and_import_is_rejected(media, tmp_path, monkeypatch):
    import src.tag_completion as completion
    root, make = media
    source = make()
    work, _, result_path, review_path = auto_inputs(tmp_path, root, [source])
    before = source.read_bytes()
    original_import = completion.import_result

    def replacing_import(*args, **kwargs):
        summary = original_import(*args, **kwargs)
        replacement = json.loads(review_path.read_text())
        replacement["run_reference"] = "different-synthetic-run"
        for decision in replacement["decisions"]:
            decision["decision"] = "reject"
        review_path.write_text(json.dumps(replacement))
        return summary

    monkeypatch.setattr(completion, "import_result", replacing_import)
    with pytest.raises(ValueError, match="Parent review changed before acceptance"):
        completion.auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert source.read_bytes() == before
    assert not (work / "backups").exists()
    assert not (work / "batches/batch-0001/review.json").exists()


def test_review_resume_is_bound_to_exact_bytes(media, tmp_path):
    root, make = media
    source = make()
    work, _, result_path, review_path = auto_inputs(tmp_path, root, [source])
    auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    before = source.read_bytes()
    review_path.write_bytes(review_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Parent review changed during automatic resume"):
        auto_commit_batch(work, "batch-0001", result_path, "synthetic-settled-run", review_path)
    assert source.read_bytes() == before
