"""Tests for receipt_assemble.py: bounded-schema assembly only, never ledger writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import receipt_assemble as ra  # noqa: E402

FETCH_HEADER = {
    "request_sha256": "a" * 64,
    "gap_id": "technology-supply",
    "reservation_id": "fetch-1",
    "invocation_id": "a" * 64 + ":technology-supply:fetch-1",
    "tool": "fetch_content",
    "arguments": {"url": "https://example.org/a", "mode": "readable"},
    "started_at": "2026-09-13T07:00:00+00:00",
    "completed_at": "2026-09-13T07:00:01+00:00",
    "outcome": "success",
    "error": None,
    "truncated": False,
    "parent_attestation": "actual_public_tool_receipt",
}

QUERY_HEADER = {
    "request_sha256": "a" * 64,
    "gap_id": "technology-supply",
    "reservation_id": "query-1",
    "tool": "web_search",
    "query": "example query",
    "responseId": "resp-1",
    "outcome": "matched",
    "error": None,
    "results": [{"url": "https://example.org/a", "title": "Example"}],
    "proof_subset": {"delivered_result_count": 1, "bounded": True},
    "parent_attestation": "actual_public_tool_receipt",
}


def _write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_fetch_assembly_writes_receipt_with_exact_body(tmp_path):
    header = _write(tmp_path, "header.json", FETCH_HEADER)
    body = _write(tmp_path, "body.txt", "line one\n\nline two with 中文")
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["text"] == "line one\n\nline two with 中文"
    assert receipt["reservation_id"] == "fetch-1"
    assert set(receipt) - {"responseId"} == ra.FETCH_REQUIRED


def test_fetch_assembly_refuses_overwrite(tmp_path):
    header = _write(tmp_path, "header.json", FETCH_HEADER)
    body = _write(tmp_path, "body.txt", "text")
    out = _write(tmp_path, "receipt.json", {"already": True})
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2


@pytest.mark.parametrize("mutate", ["missing", "extra", "tool", "empty-body", "truncated"])
def test_fetch_assembly_rejects_schema_violations(tmp_path, mutate):
    header_payload = dict(FETCH_HEADER)
    body_text = "text body"
    if mutate == "missing":
        header_payload.pop("invocation_id")
    elif mutate == "extra":
        header_payload["surprise"] = 1
    elif mutate == "tool":
        header_payload["tool"] = "web_search"
    elif mutate == "empty-body":
        body_text = "   "
    elif mutate == "truncated":
        header_payload["truncated"] = "no"
    header = _write(tmp_path, "header.json", header_payload)
    body = _write(tmp_path, "body.txt", body_text)
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2
    assert not out.exists()


def test_fetch_assembly_rejects_error_outcome_without_error(tmp_path):
    payload = dict(FETCH_HEADER)
    payload["outcome"] = "error"
    header = _write(tmp_path, "header.json", payload)
    body = _write(tmp_path, "body.txt", "")
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2


def test_fetch_assembly_rejects_oversized_body(tmp_path):
    header = _write(tmp_path, "header.json", FETCH_HEADER)
    body = _write(tmp_path, "body.txt", "x" * (ra.MAX_BODY + 1))
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2


def test_query_assembly_requires_results_and_proof(tmp_path):
    header = _write(tmp_path, "header.json", QUERY_HEADER)
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "query", "--header", str(header), "--out", str(out)]) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert set(receipt) == ra.QUERY_REQUIRED

    out2 = tmp_path / "receipt2.json"
    bad = dict(QUERY_HEADER)
    bad["results"] = []
    header2 = _write(tmp_path, "header2.json", bad)
    assert ra.main(["--kind", "query", "--header", str(header2), "--out", str(out2)]) == 2
    assert not out2.exists()


def test_query_assembly_rejects_body_flag(tmp_path):
    header = _write(tmp_path, "header.json", QUERY_HEADER)
    body = _write(tmp_path, "body.txt", "text")
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "query", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2


def test_fetch_assembly_accepts_bounded_excerpt_declaration(tmp_path):
    header = _write(tmp_path, "header.json", dict(FETCH_HEADER, text_coverage="bounded_excerpt"))
    body = _write(tmp_path, "body.txt", "short excerpt")
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 0
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["text_coverage"] == "bounded_excerpt"
    assert set(receipt) - ra.OPTIONAL == ra.FETCH_REQUIRED


def test_fetch_assembly_rejects_invalid_coverage_value(tmp_path):
    header = _write(tmp_path, "header.json", dict(FETCH_HEADER, text_coverage="partial"))
    body = _write(tmp_path, "body.txt", "text")
    out = tmp_path / "receipt.json"
    assert ra.main(["--kind", "fetch", "--header", str(header), "--body", str(body), "--out", str(out)]) == 2
    assert not out.exists()
