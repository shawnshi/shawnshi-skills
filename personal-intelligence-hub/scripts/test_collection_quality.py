from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import collection_quality as quality
import fetch_news
from native_capture import capture_fields, validate_capture
from receipt_assemble import main as assemble
from test_native_article_evidence import new_run, timely_scenario, search, reserve, URL, text


def capture(tmp_path, text="Title\r\n\r\nPublished October 8, 2026\r\n" + "正文" * 1800):
    path = tmp_path / "tool.capture.json"
    path.write_bytes(json.dumps({"responseId": "raw-1", "urls": [{"url": "https://example.com/news", "status": 200, "content": text}]}, ensure_ascii=False).encode("utf-8"))
    return path


def test_native_broker_rejects_reconstruction_before_mutation_and_rechecks_capture(new_run, monkeypatch):
    import article_broker as broker
    import run_contract as rc
    path, request, _, clock, _ = timely_scenario(new_run, monkeypatch, worker_delivery_version=1)
    search(request)
    _, receipt = reserve(request, started_at=clock.value.isoformat(), completed_at=clock.value.isoformat())
    receipt.pop("native_capture", None)
    before = path.read_bytes()
    with pytest.raises(rc.RunContractError, match="capture"):
        broker.operate(request, "tech", "record-fetch", receipt=receipt)
    assert path.read_bytes() == before
    captured = request.parent / "actual.capture.json"
    captured.write_text(json.dumps({"responseId": "native-test", "urls": [{"url": URL, "content": text(clock.value.date().isoformat()), "status": 200}]}), encoding="utf-8")
    receipt.update(capture_fields(captured, URL))
    data = broker.operate(request, "tech", "record-fetch", receipt=receipt)
    assert len(data["proofs"]) == 1
    captured.write_bytes(captured.read_bytes() + b" ")
    with pytest.raises(rc.RunContractError, match="capture"):
        broker.evidence(request, "tech")


def test_registered_shared_query_failure_reconciles_unstarted_lane(new_run, monkeypatch):
    import article_broker as broker
    import run_contract as rc
    path, request, _, _, _ = timely_scenario(new_run, monkeypatch, worker_delivery_version=1)
    data = broker.operate(request, "tech", "reserve-query", query="original release")
    reservation = data["query_reservations"][-1]
    broker.operate(request, "tech", "record-query", receipt={
        "request_sha256": data["request_sha256"], "gap_id": "tech", "reservation_id": reservation["id"],
        "tool": "web_search", "query": "original release", "responseId": "native-unavailable",
        "outcome": "error", "error": "[TOOL_UNAVAILABLE] native search unavailable", "results": [],
        "proof_subset": {"text": "[TOOL_UNAVAILABLE] native search unavailable"},
        "parent_attestation": "actual_public_tool_receipt",
    })
    broker.operate(request, "tech", "terminal")
    _, aggregate = rc.reconcile_supplement_progress(path, request, [], [], unstarted_gap_ids=["risk"])
    assert aggregate["status"] == "degraded"
    assert {item["gap_id"] for item in aggregate["results"]} == {"tech", "risk"}
    assert all(item["failure_kind"] == "infrastructure" and item["access_log"] == [] for item in aggregate["results"])
    assert rc.load_manifest(path)["stages"]["supplemental"]["status"] == "degraded"


def test_medical_reading_budget_and_frozen_required_ids_scale_with_candidates(tmp_path):
    import run_contract as rc
    from run_daily import assess_supplement_gaps
    from hub_utils import atomic_dump_json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    path, manifest = rc.create_run(runtime_dir=tmp_path, skill_path=Path(__file__).resolve().parents[1] / "SKILL.md", now=now)
    root = Path(manifest["run_dir"])
    baseline = root / "baseline.json"
    atomic_dump_json(baseline, {"items": []})
    rc.record_stage(path, "baseline", "completed", artifact_path=baseline, now=now)
    focus = rc.load_json(Path(__file__).resolve().parents[1] / "references/strategic_focus.json", {})
    focus["coverage_policy"]["lanes"] = {}
    focus["coverage_policy"]["healthcare_supply_trigger"] = 99
    items = [{"title": f"医院 FHIR EHR 接口发布 {i}", "url": f"https://example.org/health-{i}",
              "source": "CHIMA", "provisional_domain": "healthcare_digital", "heuristic_rank": 20,
              "domain_scores": {"technology": 0, "healthcare_digital": 20}} for i in range(10)]
    pool = {"items": items}
    pool_path = root / "medical-pool.json"
    atomic_dump_json(pool_path, pool)
    rc.record_run_artifact(path, "candidate_pool", pool_path, now=now)
    focus_path = root / "medical-focus.json"
    atomic_dump_json(focus_path, focus)
    rc.record_run_artifact(path, "focus_config", focus_path, now=now)
    gaps = assess_supplement_gaps(pool, manifest, focus)
    gap = next(g for g in gaps if g["lane"] == "HealthcareRadar")
    assert gap["max_urls"] == 8
    _, request = rc.build_supplement_request(path, [gap], worker_delivery_version=1, now=now)
    assert request["gaps"][0]["max_urls"] == 8
    packet = request["execution_packets"][0]
    lane = rc.load_json(Path(packet["lane_slice"]["path"]), {})
    assert len(lane["required_bound_candidate_ids"]) == 6
    assert gap["max_urls"] - len(lane["required_bound_candidate_ids"]) == 2
    legacy = dict(request["gaps"][0])
    legacy.pop("bound_reading_budget")
    from lane_selection import select_supplement_bound_candidates
    _, old_ids = select_supplement_bound_candidates(pool, legacy, focus, article_broker_version=3)
    assert len(old_ids) == 8


def test_new_policy_preserves_low_coverage_through_real_atomic_forge(tmp_path, monkeypatch):
    from test_native_article_evidence import test_native_mocked_end_to_end_temporary_forge
    test_native_mocked_end_to_end_temporary_forge(tmp_path, monkeypatch, False, low_coverage=True)


def test_capture_preserves_unicode_long_body_dates_and_crlf(tmp_path):
    path = capture(tmp_path)
    fields = capture_fields(path, "https://example.com/news")
    assert "October 8, 2026\r\n" in fields["text"]
    receipt = {**fields, "arguments": {"url": "https://example.com/news"}}
    validate_capture(receipt, {"native_capture_version": 1}, tmp_path / "request.json")
    receipt["text"] = receipt["text"][:100]
    with pytest.raises(ValueError, match="differs"):
        validate_capture(receipt, {"native_capture_version": 1}, tmp_path / "request.json")


def test_capture_tamper_foreign_url_and_missing_proof_rejected(tmp_path):
    path = capture(tmp_path)
    fields = capture_fields(path, "https://example.com/news")
    receipt = {**fields, "arguments": {"url": "https://example.com/news"}}
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes changed"):
        validate_capture(receipt, {"native_capture_version": 1}, tmp_path / "request.json")
    with pytest.raises(ValueError, match="matching requested URL"):
        capture_fields(path, "https://foreign.com/news")
    with pytest.raises(ValueError, match="required"):
        validate_capture({"text": "summary"}, {"native_capture_version": 1}, tmp_path / "request.json")
    validate_capture({}, {}, tmp_path / "legacy.json")


def test_native_capture_assembler_uses_tool_return_not_header_claims(tmp_path):
    path = capture(tmp_path)
    header = tmp_path / "header.json"
    header.write_text(json.dumps({"request_sha256": "a" * 64, "gap_id": "tech", "reservation_id": "fetch-1",
        "invocation_id": "a:tech:fetch-1", "tool": "fetch_content", "arguments": {"url": "https://example.com/news", "mode": "readable"},
        "started_at": "2026-10-13T01:00:00Z", "completed_at": "2026-10-13T01:00:01Z", "outcome": "error",
        "error": "made up", "truncated": True, "parent_attestation": "actual_public_tool_receipt"}), encoding="utf-8")
    target = tmp_path / "receipt.json"
    assert assemble(["--kind", "fetch", "--header", str(header), "--tool-output", str(path), "--out", str(target)]) == 0
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["outcome"] == "success" and result["error"] is None
    assert result["text"] == capture_fields(path, "https://example.com/news")["text"]
    validate_capture(result, {"native_capture_version": 1}, tmp_path / "request.json")


@pytest.mark.parametrize("code", ["NATIVE_CONTENT_NOT_VERIFIED", "HTTP_403", "UNKNOWN_DATE", "SOURCE_CLOCK_EXPIRED"])
def test_local_content_source_failures_never_stop_independent_lanes(code):
    assert not quality.shared_infrastructure_failure({"failure_kind": "infrastructure", "access_log": [{"error_code": code}]})


def test_shared_capability_failure_needs_explicit_error_evidence():
    assert not quality.shared_infrastructure_failure({"failure_kind": "infrastructure", "access_log": []})
    assert not quality.shared_infrastructure_failure({"failure_kind": "infrastructure", "access_log": [{"error_code": "TOOL_UNAVAILABLE"}]})
    ledger = {"events": [{"kind": "query_recorded", "receipt": {"outcome": "error", "error": "[TOOL_UNAVAILABLE] native search unavailable"}}]}
    assert quality.shared_infrastructure_failure({"failure_kind": "infrastructure", "access_log": []}, ledger)


def healthy_scan():
    return {"metadata": {"sources": {name: "OK" for names in quality.STRATEGIC_SOURCES.values() for name in names}}, "items": [], "quarantine": []}


def test_expansion_cannot_compensate_for_unread_or_unavailable_sources():
    scan = healthy_scan()
    core = {"candidate_funnel": {"quality_gate_reasons": {"missing_verified_access": 28}}}
    assert not quality.expansion_diagnostics(core, scan, {"results": []})["allow_expansion"]
    core = {"candidate_funnel": {"quality_gate_reasons": {}}}
    assert quality.expansion_diagnostics(core, scan, {"results": []})["allow_expansion"]
    scan["metadata"]["sources"]["国家医保局 (NHSA)"] = "403"
    assert not quality.expansion_diagnostics(core, scan, {"results": []})["allow_expansion"]
    assert quality.source_diagnostics(scan)["groups"]["china_policy"]["failed_sources"] == ["国家医保局 (NHSA)"]


def test_historical_keyword_match_does_not_outrank_current_policy():
    recap = {"title": "NVIDIA first GPU GeForce 256", "heuristic_rank": 11}
    policy = {"title": "新的接口规范", "source": "CHIMA", "heuristic_rank": 8}
    assert quality.candidate_reading_priority(recap) < quality.candidate_reading_priority(policy)


@pytest.mark.parametrize("cdata", [False, True])
def test_official_list_dates_are_row_local_and_links_same_host(cdata):
    rows = '<li><a href="/art/2026/10/9/art_14_23108.html">支付政策</a><span>2026-10-09</span></li><li><a href="https://evil.example/art/2026/10/9/art_14_1.html">其他</a><span>2026-10-09</span></li><li><a href="/art/2026/10/8/art_14_2.html">日期缺失</a></li>'
    text = f'<record><![CDATA[{rows}]]></record>' if cdata else rows
    feed = {"name": "国家医保局 (NHSA)", "url": "https://www.nhsa.gov.cn/col/col14/index.html", "article_path": r"^/art/"}
    items = fetch_news.public_list_items(text, feed)
    assert len(items) == 2 and items[0]["published_at"] == "2026-10-09"
    assert items[1]["published_at"] == "unknown"
    nested = '<section><div><a href="/art/2026/10/8/art_14_3.html">无日期文章</a></div><div><a href="/art/2026/10/9/art_14_4.html">另一篇</a><span>2026-10-09</span></div></section>'
    nested_items = fetch_news.public_list_items(nested, feed)
    assert nested_items[0]["published_at"] == "unknown"
    assert nested_items[1]["published_at"] == "2026-10-09"
    with pytest.raises(ValueError, match="not a verified no-data"):
        fetch_news.public_list_items("<html>Please enable JavaScript</html>", feed)


def test_atom_updated_is_discovery_not_claimed_original_publication(monkeypatch):
    async def returned(*args, **kwargs):
        return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Feed</title><entry><title>Article</title><link href="https://example.com/news"/><updated>2026-10-08T05:00:00+08:00</updated></entry></feed>'
    monkeypatch.setattr(fetch_news, "fetch_with_retry", returned)
    items, status = asyncio.run(fetch_news.parse_rss(None, "https://example.com/feed", "test", {}))
    assert status == "OK"
    assert items[0]["published_at"] == "unknown"
    assert items[0]["published_at_source"] == "unknown"
    assert items[0]["discovery_date_source"] == "atom_updated"
    assert items[0]["discovery_updated_at"].startswith("2026-10-08T05:00:00")
