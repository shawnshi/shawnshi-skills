"""Offline native-v3 contract: actual gates, mocked public receipts, temporary archives only."""

# ruff: noqa: F811 -- pytest fixture dependency
import hashlib
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import article_broker as broker
import pytest
import run_contract as rc
from hub_utils import atomic_dump_json
from supplement_agent import _compact_broker_cli_evidence, verify_bound_candidates
from test_article_broker_contract import new_run  # noqa: F401
from test_article_broker_evidence import URL, dynamic
from test_run_daily_broker_entry import prepare_fixture


@pytest.mark.parametrize("duration", [None, 600, 150])
def test_native_builder_defaults_and_over_limit(new_run, duration):
    path, root, now = new_run
    gap = {
        "gap_id": "tech",
        "lane": "TechRadar",
        "query_scope": "release",
        "article_broker": True,
    }
    limits = {"max_queries": 2, "max_urls": 4, "max_duration_seconds": 600}
    for key, limit in limits.items():
        with pytest.raises(rc.RunContractError, match="native v3 budget"):
            rc.build_supplement_request(
                path, [{**gap, key: limit + 1}], article_broker_version=3, now=now
            )
        assert not (root / "supplement_request.json").exists()
    if duration is not None:
        gap["max_duration_seconds"] = duration
    _, request = rc.build_supplement_request(
        path, [gap], article_broker_version=3, now=now
    )
    expected = {**limits, "max_duration_seconds": duration or 600}
    assert {key: request["gaps"][0][key] for key in limits} == expected
    packet = request["execution_packets"][0]
    assert packet["execution_budget"] == expected
    assert packet["finalization"]["grace_seconds"] == 300
    worker = request["launch_plan"][0]["workers"][0]
    assert worker["timeout_ms"] == (expected["max_duration_seconds"] + 300) * 1000
    assert packet["tool_budget"]["hard"] == worker["tool_budget"]["hard"] == 12
    assert packet["usage_budget"]["tokens"] == worker["token_budget"] == 150000
    assert rc._normalized_supplement_budget({}) == {
        "max_queries": 3,
        "max_urls": 6,
        "max_duration_seconds": 180,
    }


def setup(run, **gap):
    path, root, now = run
    focus = root / "focus-native.json"
    atomic_dump_json(focus, {"filters": {"max_top10": 2}})
    rc.record_run_artifact(path, "focus_config", focus, now=now)
    request, value = rc.build_supplement_request(
        path,
        [
            {
                "gap_id": "tech",
                "lane": "TechRadar",
                "query_scope": "original release",
                "article_broker": True,
                "max_urls": 4,
                "max_queries": 2,
                "max_duration_seconds": 150,
                **gap,
            }
        ],
        article_broker_version=3,
        now=now,
    )
    return request, value["execution_packets"][0]


def search(request, gap="tech", *, query="release", matched=True, error=False, url=URL):
    data = broker.operate(request, gap, "reserve-query", query=query)
    reservation = data["query_reservations"][-1]
    return broker.operate(
        request,
        gap,
        "record-query",
        receipt={
            "request_sha256": data["request_sha256"],
            "gap_id": gap,
            "reservation_id": reservation["id"],
            "tool": "web_search",
            "query": query,
            "responseId": gap + ":" + query,
            "outcome": "error" if error else "matched" if matched else "empty",
            "error": "provider failed" if error else None,
            "results": [{"url": url, "title": "Original release"}]
            if matched and not error
            else [],
            "proof_subset": {"text": "offline actual returned search fixture"},
            "parent_attestation": "actual_public_tool_receipt",
        },
    )


def text(day=None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    return (
        f"Published: {day}\nOriginal product research release\n\n"
        + "Example released an original product and described its research methods and limitations. "
        * 4
        + "\n\n"
        + "The release provides deployment details, measured evaluation results and documented constraints. "
        * 4
    )


def reserve(request, gap="tech", url=URL, **changes):
    data = broker.operate(request, gap, "reserve-fetch", url=url)
    reserved = data["fetch_reservations"][-1]
    now = datetime.now(timezone.utc).isoformat()
    receipt = {
        "request_sha256": data["request_sha256"],
        "gap_id": gap,
        "reservation_id": reserved["id"],
        "invocation_id": reserved["invocation_id"],
        "tool": "fetch_content",
        "arguments": reserved["arguments"],
        "started_at": now,
        "completed_at": now,
        "outcome": "success",
        "error": None,
        "text": text(),
        "truncated": None,
        "parent_attestation": "actual_public_tool_receipt",
        **changes,
    }
    return data, receipt


ARXIV_URL = "https://arxiv.org/abs/2609.09356"
ARXIV_V1 = r"**\[v1\]** Tue, 8 Sep 2026 18:45:01 UTC (221 KB)"


def arxiv_text(version="v1", history=ARXIV_V1):
    """Minimized synthetic layout, not a copied receipt or independent source review."""
    return (
        f"[View PDF](/pdf/2609.09356) [HTML](https://arxiv.org/html/2609.09356{version})\n\n"
        "> Abstract:"
        + "The study describes a product evaluation with measured results, methods and limitations. "
        * 4
        + "\n\nCite as:\n\n[arXiv:2609.09356](https://arxiv.org/abs/2609.09356)\n\n"
        + f"(or [arXiv:2609.09356{version}](https://arxiv.org/abs/2609.09356{version}) for this version)\n\n"
        + "## Submission history\n\n"
        + history
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "url", [ARXIV_URL, ARXIV_URL + "v1", ARXIV_URL.replace("//arxiv", "//www.arxiv")]
)
def test_native_arxiv_single_abstract_exact_spans(newline, url):
    body = arxiv_text().replace("\n", newline)
    metadata = broker.readable_metadata(body, url)
    assert metadata["article"] and metadata["recognizable_body"]
    assert metadata["title"] == "arXiv:2609.09356v1"
    date = metadata["dates"][0]
    assert date["published_at"] == "2026-09-08"
    assert date["published_at_source"] == "native_readable:arxiv-submission-history/1"
    assert (
        body[date["start"] : date["end"]]
        == date["raw"]
        == "Tue, 8 Sep 2026 18:45:01 UTC"
    )
    assert date["text_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert not broker.readable_metadata(body, URL)["article"]


@pytest.mark.parametrize(
    "old,new",
    [
        ("Tue, 8 Sep 2026", "Wed, 15 Jul 2026"),  # actual body-1 mismatch shape
        ("Tue, 8 Sep 2026", "Sun, 8 Sep 2126"),
        ("Tue, 8 Sep 2026", "Tue, 31 Sep 2026"),
        ("Tue, 8 Sep 2026", "Tue, 8 Sep"),
        ("Tue, 8 Sep 2026", "Mon, 8 Sep 2026"),
        ("18:45:01", "24:45:01"),
        (" UTC ", " PST "),
        (ARXIV_V1, ""),
        (ARXIV_V1, ARXIV_V1 + "\n" + ARXIV_V1),
        (ARXIV_V1, ARXIV_V1 + "\n[v2] unknown"),
        (ARXIV_V1, ARXIV_V1 + "\nv2 missing date"),
        ("/pdf/2609.09356", "/pdf/2609.09166"),
        ("[arXiv:2609.09356]", "[arXiv:2609.09166]"),
        ("https://arxiv.org/abs/2609.09356)", "https://other.org/abs/2609.09356)"),
        ("https://arxiv.org/html/", "https://arxiv.org.evil.test/html/"),
        ("https://arxiv.org/html/", "https://user@arxiv.org/html/"),
        ("https://arxiv.org/html/", "javascript:/html/"),
        ("/html/2609.09356v1", "/html/2609.09356v2"),
        ("for this version", "unspecified version"),
        ("## Submission history", "## History"),
        ("> Abstract:", "> Summary:"),
        ("methods and limitations", "access denied"),
    ],
)
def test_native_arxiv_rejects_conflicting_or_missing_evidence(old, new):
    metadata = broker.readable_metadata(arxiv_text().replace(old, new), ARXIV_URL)
    assert not metadata["article"] and not metadata["dates"]


@pytest.mark.parametrize(
    "url",
    [
        ARXIV_URL + "v2",
        ARXIV_URL + "?version=v1",
        ARXIV_URL + "#v1",
        ARXIV_URL.replace("arxiv.org", "arxiv.org.evil.test"),
        ARXIV_URL.replace("arxiv.org", "user@arxiv.org"),
        ARXIV_URL.replace("https:", "file:"),
        ARXIV_URL.replace("/abs/", "/pdf/"),
        ARXIV_URL.replace("2609", "2613"),
    ],
)
def test_native_arxiv_url_identity_gate(url):
    assert not broker.readable_metadata(arxiv_text(), url)["article"]


def test_native_arxiv_displayed_version_and_window():
    history = (
        ARXIV_V1.replace("Tue, 8 Sep", "Tue, 1 Sep")
        + "\n[v2] Tue, 8 Sep 2026 18:45:01 UTC (222 KB)"
    )
    window = {"start": "2026-09-06", "end": "2026-09-08"}
    for version, eligible in [("v1", False), ("v2", True)]:
        body = arxiv_text(version, history)
        for url in [ARXIV_URL, ARXIV_URL + version]:
            metadata = broker.readable_metadata(body, url)
            assert metadata["article"]
            assert (
                broker._usable_article(
                    {"access": {"status": "verified"}, "metadata": metadata}, window
                )
                == eligible
            )
        other = "v2" if version == "v1" else "v1"
        assert not broker.readable_metadata(body, ARXIV_URL + other)["article"]
    for bad in [
        history + "\n[v2] Tue, 8 Sep 2026 19:45:01 UTC (222 KB)",
        history.replace("[v2] Tue, 8 Sep", "[v2] Mon, 31 Aug"),
        history.replace("[v2]", "[v3]"),
    ]:
        assert not broker.readable_metadata(arxiv_text(history=bad), ARXIV_URL)[
            "article"
        ]
    assert not broker.readable_metadata(
        "> Abstract:" + "Substantive but unbound text. " * 20, ARXIV_URL
    )["article"]


@pytest.mark.parametrize("size", ["221", "221.5", "1,301", "12,345.5", "1,234,567"])
def test_native_arxiv_grouped_sizes_are_not_date_evidence(size):
    body = arxiv_text(history=ARXIV_V1.replace("221", size))
    meta = broker.readable_metadata(body, ARXIV_URL)
    assert meta["article"] and len(meta["dates"]) == 1
    date = meta["dates"][0]
    assert date["published_at"] == "2026-09-08"
    assert body[date["start"] : date["end"]] == "Tue, 8 Sep 2026 18:45:01 UTC"


@pytest.mark.parametrize(
    "size", ["1,30", "1,301,", ",301", "1234,567", "1,,301", "01,301", "1,301.2,3"]
)
def test_native_arxiv_malformed_grouped_sizes_rejected(size):
    meta = broker.readable_metadata(
        arxiv_text(history=ARXIV_V1.replace("221", size)), ARXIV_URL
    )
    assert not meta["article"] and not meta["dates"]


MIXED_URLS = [
    ARXIV_URL,
    "https://arxiv.org/abs/2609.09349",
    "https://arxiv.org/abs/2609.09348",
    "https://arxiv.org/abs/2609.09166",
]


def mixed_body(url):
    body = arxiv_text().replace("2609.09356", url.rsplit("/", 1)[-1])
    if url == MIXED_URLS[1]:
        body = body.replace("221 KB", "1,301 KB")
    elif url == MIXED_URLS[2]:
        body = body.replace("221 KB", "1,30 KB")
    elif url == MIXED_URLS[3]:
        body = body.replace("Tue, 8 Sep 2026", "Wed, 15 Jul 2026")
    return body


def bound_dynamic(data, lane):
    value = dynamic(data, candidate=False)
    value["status"] = "degraded"
    for bound, proof in zip(lane["candidates"], data["proofs"], strict=True):
        usable = broker._usable_article(proof, lane["window"])
        if usable:
            candidate = dynamic({**data, "proofs": [proof]})["candidates"][0]
            candidate.update(
                url=bound["url"],
                candidate_id=bound["candidate_ref"],
                title=proof["metadata"]["title"],
                source="arXiv",
            )
            candidate["event_identity"]["object"] = bound["url"]
            value["candidates"].append(candidate)
        value["bound_candidate_decisions"].append(
            {
                "candidate_id": bound["candidate_ref"],
                "decision": "registered"
                if usable
                else "access_blocked"
                if proof["access"]["status"] == "blocked"
                else "date_disqualified",
                "reason": "Retained exact native body and publication evidence; no invented date",
            }
        )
    return value


@pytest.mark.parametrize("new_run", [4], indirect=True)
@pytest.mark.parametrize("all_failed", [False, True])
def test_native_partial_bound_closure_guards(new_run, monkeypatch, all_failed):
    from datetime import timedelta

    from supplement_agent import finalize_parent_draft

    request, packet = setup(new_run, verify_bound_candidates=True)
    monkeypatch.setattr(broker, "_transport", forbid)
    lane = rc.load_json(Path(packet["lane_slice"]["path"]), {})
    for index, bound in enumerate(lane["candidates"]):
        _, receipt = reserve(
            request,
            url=bound["url"],
            text="Malformed readable article" if all_failed or index > 1 else text(),
        )
        if index == 3:
            pending = broker.evidence(request, "tech")
            assert not pending["next_action"]["bound_budget_exhausted"]
            with pytest.raises(rc.RunContractError, match="unsettled"):
                broker.operate(request, "tech", "seal")
        data = broker.operate(request, "tech", "record-fetch", receipt=receipt)
        if index < 3:
            assert not data["next_action"]["bound_budget_exhausted"]
            with pytest.raises(rc.RunContractError):
                broker.operate(request, "tech", "seal")
    data = broker.evidence(request, "tech")
    manifest = rc.load_manifest(new_run[0])
    req = rc.load_json(request, {})
    gap = req["gaps"][0]
    for variant in (
        "v2",
        "available",
        "missing",
        "foreign",
        "no_required",
        "expired",
        "query",
        "error",
    ):
        m, r, g, lane_copy = (
            deepcopy(manifest),
            deepcopy(req),
            deepcopy(gap),
            deepcopy(lane),
        )
        proofs = deepcopy(data["proofs"])
        now = datetime.now(timezone.utc)
        if variant == "v2":
            r["article_broker_version"] = 2
        elif variant == "available":
            g["max_urls"] += 1
        elif variant == "missing":
            proofs.pop()
        elif variant == "foreign":
            proofs[0]["access"]["requested_url"] = URL
        elif variant == "no_required":
            lane_copy["required_bound_candidate_ids"] = []
        elif variant == "expired":
            now += timedelta(seconds=151)
        else:
            events = m["article_broker_evidence"]["tech"]["events"]
            events.append(
                {"kind": "query_reserved", "id": "query-1", "at": now.isoformat()}
            )
            if variant == "error":
                events.append(
                    {
                        "kind": "query_recorded",
                        "id": "query-1",
                        "at": now.isoformat(),
                        "receipt": {"results": [], "outcome": "error"},
                    }
                )
        advice = broker.next_action(m, r, g, lane_copy, proofs, now=now)
        assert not advice.get("bound_budget_exhausted", False), variant
        assert not advice["stop_eligible"], variant
    with pytest.raises(rc.RunContractError, match="URL attempt budget"):
        broker.operate(request, "tech", "reserve-query", query="artificial search")
    data = broker.operate(request, "tech", "seal")
    assert data["next_action"]["bound_budget_exhausted"]
    assert not data["next_action"]["bound_only_complete"]
    value = bound_dynamic(data, lane)
    for status, confidence in [
        ("completed", "low"),
        ("degraded", "high"),
        ("no_increment", "low"),
    ]:
        with pytest.raises(rc.RunContractError, match="degraded coverage"):
            broker.validate_result(
                request, "tech", {**value, "status": status, "confidence": confidence}
            )
    bad = deepcopy(value)
    bad["access_log"].pop()
    with pytest.raises(rc.RunContractError, match="authoritative access_log"):
        broker.validate_result(request, "tech", bad)
    if value["candidates"]:
        bad = deepcopy(value)
        bad["candidates"][0]["broker_body_proof_sha256"] = "f" * 64
        with pytest.raises(rc.RunContractError, match="exact helper"):
            broker.validate_result(request, "tech", bad)
    atomic_dump_json(Path(packet["output_paths"]["draft"]), value)
    ready, _ = finalize_parent_draft(request, "tech")
    _, aggregate = rc.register_supplement_results(
        new_run[0], request, [ready], publish_drafts=True
    )
    result = aggregate["results"][0]
    assert result["status"] == "degraded" and result["confidence"] == "low"
    assert len(result["access_log"]) == 4
    assert len(result["candidates"]) == (0 if all_failed else 2)


def forbid(*args, **kwargs):
    raise AssertionError("v3 called custom transport")


@pytest.mark.parametrize("arxiv", [False, True])
def test_native_receipt_seal_exact_proof_and_mutation(new_run, monkeypatch, arxiv):
    monkeypatch.setattr(broker, "_transport", forbid)
    monkeypatch.setattr("supplement_agent._fetch_url", forbid)
    request, _ = setup(new_run)
    url = ARXIV_URL if arxiv else URL
    search(request, url=url)
    data, receipt = reserve(request, url=url, text=arxiv_text() if arxiv else text())
    compact = _compact_broker_cli_evidence(request, "tech", data)
    assert compact["fetch_reservations"][-1]["arguments"] == {
        "url": url,
        "mode": "readable",
    }
    data = broker.operate(request, "tech", "record-fetch", receipt=receipt)
    proof = data["proofs"][0]
    assert "responseId" not in proof["receipt"]
    assert proof["receipt"] == receipt
    assert (
        proof["readable_text_sha256"]
        == hashlib.sha256(receipt["text"].encode()).hexdigest()
    )
    assert "body_sha256" not in proof and "body_base64" not in proof
    assert (
        proof["access"]["http_status"] is None and proof["access"]["final_url"] is None
    )
    assert proof["transport_visibility"] == broker.NATIVE_VISIBILITY
    with pytest.raises(rc.RunContractError):
        broker.operate(request, "tech", "record-fetch", receipt=receipt)
    data = broker.operate(request, "tech", "seal")
    candidate = dynamic(data)
    candidate["candidates"][0]["url"] = url
    assert broker.validate_result(request, "tech", candidate) is False
    bad = deepcopy(candidate)
    bad["candidates"][0]["published_at_proof"]["start"] += 1
    with pytest.raises(rc.RunContractError, match="publication"):
        broker.validate_result(request, "tech", bad)
    changed = deepcopy(proof["access"])
    changed["native_evidence"]["receipt_sha256"] = "f" * 64
    assert rc._validate_access_log_entry(changed, 0) != rc._validate_access_log_entry(
        proof["access"], 0
    )
    with pytest.raises(rc.RunContractError, match="sealed"):
        broker.operate(request, "tech", "reserve-fetch", url=URL)
    path = Path(new_run[1]) / "broker_tech_body_1.json"
    stored = rc.load_json(path, {})
    stored["readable_text"] += "mutation"
    atomic_dump_json(path, stored)
    with pytest.raises(rc.RunContractError, match="changed"):
        rc.load_manifest(new_run[0])


@pytest.mark.parametrize(
    "changes",
    [
        {"gap_id": "foreign"},
        {"request_sha256": "f" * 64},
        {"arguments": {"url": URL, "mode": "answer"}},
        {"parent_attestation": "model_summary"},
        {"text": ""},
        {"text": "x" * (broker.MAX_BODY + 1)},
        {"http_status": 200},
    ],
)
def test_native_foreign_malformed_receipt_retains_pending(new_run, changes):
    request, _ = setup(new_run)
    search(request)
    _, receipt = reserve(request, **changes)
    with pytest.raises(rc.RunContractError):
        broker.operate(request, "tech", "record-fetch", receipt=receipt)
    data = broker.evidence(request, "tech")
    assert data["remaining_urls"] == 3
    assert data["next_action"]["unsettled_reservations"] == ["fetch-1"]
    with pytest.raises(rc.RunContractError, match="unsettled"):
        broker.operate(request, "tech", "reserve-query", query="alternative")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/a",
        "http://2130706433/a",
        "https://user:pass@example.org/a",
        "http://localhost/a",
        "http://198.18.0.1/a",
        "file:///tmp/a",
    ],
)
def test_native_unsafe_url_before_reservation(new_run, url):
    request, _ = setup(new_run)
    with pytest.raises(rc.RunContractError, match="unsafe"):
        broker.operate(request, "tech", "reserve-fetch", url=url)
    assert broker.evidence(request, "tech")["remaining_urls"] == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"truncated": True},
        {"text": text().replace("Original product", "Access denied Original product")},
        {"outcome": "error", "error": "fetch failed", "text": ""},
        {"outcome": "partial", "error": "tool output incomplete"},
    ],
)
def test_native_error_truncated_challenge_unusable(new_run, changes):
    request, _ = setup(new_run)
    search(request)
    _, receipt = reserve(request, **changes)
    data = broker.operate(request, "tech", "record-fetch", receipt=receipt)
    access = data["access_log"][0]
    assert access["status"] == "blocked" and access["failure_class"] == "transient"
    assert not data["next_action"]["usable_article_count"]


@pytest.mark.parametrize(
    "header,eligible",
    [
        ("Published: 2026-09-08", True),
        ("Sep 08, 2026", True),
        ("Updated: 2026-09-08", False),
        ("Event: 2026-09-08", False),
        ("Published: Sep 08", False),
        ("Published: 2026-02-30", False),
        ("Published: 2026-09-08\nPublished: 2026-09-07", False),
        ("Published: 2026-09-08\nPublished: unknown", False),
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_native_publication_spans(header, eligible, newline):
    body = (
        text("2026-09-08")
        .replace("Published: 2026-09-08", header)
        .replace("\n", newline)
    )
    metadata = broker.readable_metadata(body, URL)
    assert bool(metadata["article"]) == eligible
    for proof in metadata["dates"]:
        assert body[proof["start"] : proof["end"]] == proof["raw"]
        assert proof["text_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    assert not broker.readable_metadata(body, "https://example.org/news")["article"]


def test_native_custom_http_and_verify_bound_forbidden(new_run, monkeypatch):
    request, _ = setup(new_run)
    monkeypatch.setattr(broker, "_transport", forbid)
    monkeypatch.setattr("supplement_agent._fetch_url", forbid)
    with pytest.raises(rc.RunContractError, match="custom HTTP forbidden"):
        broker.operate(request, "tech", "http", url=URL)
    with pytest.raises(rc.RunContractError, match="parent"):
        verify_bound_candidates(request, "tech")


@pytest.mark.parametrize("new_run", [4], indirect=True)
def test_native_full_required_budget_bound_only(new_run, monkeypatch):
    # Simulate an already frozen pre-FIX2 v3 request; finalization must not rerank it.
    selector = rc.select_supplement_bound_candidates
    with monkeypatch.context() as frozen:
        frozen.setattr(
            rc,
            "select_supplement_bound_candidates",
            lambda pool, gap, focus, **kw: selector(
                pool, gap, focus, article_broker_version=2
            ),
        )
        request, packet = setup(new_run, verify_bound_candidates=True)
    monkeypatch.setattr(broker, "_transport", forbid)
    monkeypatch.setattr("supplement_agent._fetch_url", forbid)
    lane = rc.load_json(Path(packet["lane_slice"]["path"]), {})
    assert len(lane["required_bound_candidate_ids"]) == 4
    for candidate in lane["candidates"]:
        _, receipt = reserve(request, url=candidate["url"])
        broker.operate(request, "tech", "record-fetch", receipt=receipt)
    with pytest.raises(rc.RunContractError, match="budget exhausted"):
        broker.operate(
            request, "tech", "reserve-fetch", url=lane["candidates"][0]["url"]
        )
    data = broker.operate(request, "tech", "seal")
    assert data["next_action"]["bound_only_complete"]
    assert data["remaining_urls"] == 0 and data["remaining_queries"] == 2
    assert (
        rc.load_manifest(new_run[0])["telemetry"]["summary"]["reserved_tokens"]
        == 150000
    )


def test_native_out_of_window_error_search_and_expired_clock(new_run, monkeypatch):
    from datetime import timedelta

    request, _ = setup(new_run)
    search(request)
    _, receipt = reserve(request, text=text("2020-01-01"))
    data = broker.operate(request, "tech", "record-fetch", receipt=receipt)
    assert data["next_action"]["usable_article_count"] == 0
    search(request, query="different agency", matched=False, error=True)
    with pytest.raises(rc.RunContractError, match="search proof"):
        broker.operate(request, "tech", "seal")
    real_datetime = datetime

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(seconds=151)

    monkeypatch.setattr(broker, "datetime", ExpiredClock)
    with pytest.raises(rc.RunContractError, match="clock expired"):
        broker.operate(request, "tech", "reserve-fetch", url=URL)


@pytest.mark.parametrize("arxiv", [False, True, "mixed"])
def test_native_mocked_end_to_end_temporary_forge(tmp_path, monkeypatch, arxiv):
    mixed = arxiv == "mixed"
    if mixed:
        import json

        import test_run_daily_broker_entry as entry

        original_scan = entry.scan_fixture

        def mixed_scan(count):
            async def scan(**kwargs):
                payload = await original_scan(count)(**kwargs)
                for item, url in zip(payload["items"], MIXED_URLS, strict=True):
                    item["url"] = url
                for name in ("output_path", "current_output_path"):
                    kwargs[name].write_text(json.dumps(payload), encoding="utf-8")
                return payload

            return scan

        monkeypatch.setattr(entry, "scan_fixture", mixed_scan)
    prepared = prepare_fixture(tmp_path, 4 if mixed else 0, 3)
    request = prepared.supplement_request_path
    assert request is not None
    packets = rc.load_json(request, {})["execution_packets"]
    monkeypatch.setattr(broker, "_transport", forbid)
    monkeypatch.setattr("supplement_agent._fetch_url", forbid)
    drafts = []
    for packet in packets:
        gap = packet["assigned_gap_ids"][0]
        selected = (
            next(g for g in rc.load_json(request, {})["gaps"] if g["gap_id"] == gap)[
                "lane"
            ]
            == "TechRadar"
        )
        url = ARXIV_URL if arxiv else URL
        if mixed and selected:
            lane = rc.load_json(Path(packet["lane_slice"]["path"]), {})
            for bound in lane["candidates"]:
                _, receipt = reserve(
                    request, gap, url=bound["url"], text=mixed_body(bound["url"])
                )
                broker.operate(request, gap, "record-fetch", receipt=receipt)
            data = broker.operate(request, gap, "seal")
            assert data["next_action"]["bound_budget_exhausted"]
            assert not data["next_action"]["bound_only_complete"]
            assert data["next_action"]["usable_article_count"] == 2
            assert (data["remaining_urls"], data["remaining_queries"]) == (0, 2)
            value = bound_dynamic(data, lane)
            assert len(value["candidates"]) == 2 and len(value["access_log"]) == 4
            for status in ("completed", "no_increment"):
                with pytest.raises(rc.RunContractError, match="degraded coverage"):
                    broker.validate_result(request, gap, {**value, "status": status})
            with pytest.raises(rc.RunContractError, match="degraded coverage"):
                broker.validate_result(request, gap, {**value, "confidence": "high"})
            draft = Path(packet["output_paths"]["draft"])
            atomic_dump_json(draft, value)
            drafts.append(str(draft))
            continue
        search(request, gap, matched=selected, url=url)
        if selected:
            _, receipt = reserve(
                request,
                gap,
                url=url,
                text=arxiv_text() if arxiv else text("2026-09-08"),
            )
            broker.operate(request, gap, "record-fetch", receipt=receipt)
        search(request, gap, query="different agency release", matched=False)
        data = broker.operate(request, gap, "seal")
        draft = Path(packet["output_paths"]["draft"])
        value = dynamic(data, candidate=selected)
        if selected and arxiv:
            value["candidates"][0].update(
                url=url, source="arXiv", title=data["proofs"][0]["metadata"]["title"]
            )
        atomic_dump_json(draft, value)
        drafts.append(str(draft))
    snapshot = Path(rc.load_manifest(prepared.manifest_path)["skill_path"]).parent
    # Execute the frozen helpers, not patched validators; all files/archives remain under tmp_path.
    code = r"""
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import run_contract as rc
from supplement_agent import finalize_parent_draft
from semantic_agent import build_agent_context, assemble_and_finalize
from forge import forge_briefing
from briefing_gate import validate_briefing_data
manifest,request,news=map(Path,sys.argv[2:5])
for packet in rc.load_json(request,{})['execution_packets']:
    finalize_parent_draft(request,packet['assigned_gap_ids'][0])
_,aggregate=rc.register_supplement_results(manifest,request,[Path(p) for p in sys.argv[5:]],publish_drafts=True)
candidate=next(c for result in aggregate['results'] for c in result['candidates'])
m=rc.load_manifest(manifest)
pool=rc.load_json(Path(m['artifacts']['candidate_pool']['artifact_path']),{})
assert rc.candidate_date_owned(candidate,rc.candidate_date_ownership(m,pool,aggregate))
assert rc.registered_candidate_lineage(m)[candidate['candidate_id']]['eligible_hashes']
review,_=rc.build_review_request(manifest,None,'semantic')
context=build_agent_context(review)
expected=2 if len(candidate_list := [c for r in aggregate['results'] for c in r['candidates']])==2 else 1
assert context['eligible_candidate_count']==expected
for c in candidate_list:
    assert rc.candidate_date_owned(c,rc.candidate_date_ownership(m,pool,aggregate))
    assert rc.registered_candidate_lineage(m)[c['candidate_id']]['eligible_hashes']
if expected==2:
    tech=next(r for r in aggregate['results'] if r['lane']=='TechRadar')
    assert tech['status']=='degraded' and len(tech['access_log'])==4
    assert tech['executed_queries']==[] and len(tech['bound_candidate_decisions'])==4
item=context['eligible_candidates'][0]
assert item['access_check']==candidate['access_check']
dynamic={
 'contract_version':'semantic-dynamic/1.0','status':'passed','turns_used':1,'halt_condition_met':True,
 'punchline':'已核验产品发布，保留适用范围。','insights':'检查产品文档与部署限制。',
 'digest':'来源报告产品发布与研究方法。','market':'不能据此推断普遍采用。',
 'action_levers':[{'domain':'technology','task':'评估文档','owner_type':'技术负责人','trigger':'测试前','indicator':'范围核对完成'}],
 'selected_items':[{'candidate_id':item['candidate_id'],'event_identity':candidate['event_identity'],
 'title_zh':'原始产品研究发布','fact':'来源描述产品能力与研究方法。','connection':'为技术评估提供输入。',
 'deduction':'应先验证适用范围。','actionability':'由技术负责人核对约束并安排测试。',
 'intelligence_level':'L2','confidence':'medium','summary_zh':'发布提供部署信息和研究限制。',
 'major_signal':False,'major_signal_reason':'none','near_term_decision_impact':False,'decision_impact_reason':'none'}]}
if expected==2:
    second=next(c for c in candidate_list if c['candidate_id']!=item['candidate_id'])
    extra=dict(dynamic['selected_items'][0],candidate_id=second['candidate_id'],event_identity=second['event_identity'])
    dynamic['selected_items'].append(extra)
core,semantic=assemble_and_finalize(review,dynamic)
_,red=rc.build_review_request(manifest,core,'red_team',semantic_receipt_path=semantic)
assert red.get('deterministic_fast_path')
result=forge_briefing(manifest,core,news_dir=news,update_runtime_state=False)
payload=rc.load_json(result.json_path,{})
assert not validate_briefing_data(payload)[0]
assert payload['top_10'][0]['access_check']==candidate['access_check']
diagnostic='diagnostic/article: attempts=4; completed=4; verified=2' if expected==2 else 'diagnostic/article: attempts=1; completed=1; verified=1'
assert any(diagnostic in reason for reason in payload['coverage']['reasons'])
assert len(payload['top_10'])==expected
assert rc.load_manifest(manifest)['stages']['archive']['status']=='completed'
print('NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-c",
            code,
            str(snapshot / "scripts"),
            str(prepared.manifest_path),
            str(request),
            str(tmp_path / "news"),
            *drafts,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_E2E_RECEIPT_SEAL_DATE_SEMANTIC_GATE_FORGE_PASS" in result.stdout


@pytest.fixture
def timely_lanes(new_run, monkeypatch):
    from datetime import timedelta

    import supplement_agent as sa

    path, root, created = new_run

    class Clock(datetime):
        value = created + timedelta(seconds=10)

        @classmethod
        def now(cls, tz=None):
            return cls.value.astimezone(tz)

    monkeypatch.setattr(sa, "datetime", Clock)
    monkeypatch.setattr(broker, "datetime", Clock)
    monkeypatch.setattr(rc, "datetime", Clock)
    focus = root / "focus-timely.json"
    atomic_dump_json(focus, {"filters": {"max_top10": 2}})
    rc.record_run_artifact(path, "focus_config", focus, now=created)
    request, value = rc.build_supplement_request(
        path,
        [
            {
                "gap_id": gap,
                "lane": lane,
                "query_scope": "release",
                "article_broker": True,
            }
            for gap, lane in [("tech", "TechRadar"), ("risk", "Sentinel")]
        ],
        article_broker_version=3,
        now=created,
    )
    packets = value["execution_packets"]

    def seal(gap):
        search(request, gap, matched=False, query="first")
        search(request, gap, matched=False, query="second")
        data = broker.operate(request, gap, "seal")
        packet = next(p for p in packets if p["assigned_gap_ids"] == [gap])
        draft = Path(packet["output_paths"]["draft"])
        atomic_dump_json(draft, dynamic(data, candidate=False))
        return draft

    return path, request, packets, Clock, seal


def test_timely_two_lane_staggered_registration_and_replay(timely_lanes):
    from datetime import timedelta

    import supplement_agent as sa

    path, request, packets, clock, seal = timely_lanes
    a = seal("tech")
    sa.finalize_parent_draft(request, "tech")
    before = a.read_bytes()
    receipt = deepcopy(
        rc.load_manifest(path)["parent_supplement_finalizations"]["tech"]
    )
    clock.value += timedelta(seconds=310)
    b = seal("risk")
    sa.finalize_parent_draft(request, "risk")
    sa.finalize_parent_draft(request, "tech")
    assert a.read_bytes() == before
    assert rc.load_manifest(path)["parent_supplement_finalizations"]["tech"] == receipt
    output, result = rc.register_supplement_results(
        path, request, [a, b], publish_drafts=True
    )
    assert len(result["results"]) == 2
    assert Path(packets[0]["output_paths"]["result"]).read_bytes() == before
    finals = [Path(p["output_paths"]["result"]) for p in packets]
    assert (
        rc.register_supplement_results(path, request, finals, publish_drafts=True)[0]
        == output
    )
    with pytest.raises(rc.RunContractError):
        sa.finalize_parent_draft(request, "tech")


@pytest.mark.parametrize(
    "case",
    [
        "no_receipt",
        "late_first",
        "tamper",
        "foreign",
        "deadline",
        "progress",
        "failed",
        "failure_file",
        "semantic",
    ],
)
def test_timely_negative_cases_preserve_evidence(timely_lanes, case):
    from datetime import timedelta

    import supplement_agent as sa

    path, request, packets, clock, seal = timely_lanes
    a = seal("tech")
    if case != "late_first":
        sa.finalize_parent_draft(request, "tech")
    manifest = rc.load_manifest(path)
    if case == "no_receipt":
        manifest.pop("parent_supplement_finalizations")
    if case == "foreign":
        manifest["parent_supplement_finalizations"]["tech"]["gap_id"] = "risk"
    if case == "deadline":
        manifest["parent_supplement_finalizations"]["tech"]["finalized_at"] = (
            clock.value + timedelta(seconds=301)
        ).isoformat()
    if case == "failed":
        manifest["stages"]["supplemental"]["status"] = "failed"
    atomic_dump_json(path, manifest)
    if case == "tamper":
        a.write_bytes(a.read_bytes() + b" ")
    if case == "semantic":
        changed = rc.load_json(a, {})
        changed["halt_condition_met"] = False
        atomic_dump_json(a, changed)
    if case == "progress":
        atomic_dump_json(
            Path(packets[0]["progress"]["state_path"]),
            {"progress_id": "tech", "terminal_status": "declare_lost"},
        )
    if case == "failure_file":
        atomic_dump_json(
            Path(packets[0]["output_paths"]["result"]).with_suffix(".failure.json"),
            {"failed": True},
        )
    clock.value += timedelta(seconds=310)
    before = a.read_bytes(), path.read_bytes()
    with pytest.raises(rc.RunContractError):
        sa.finalize_parent_draft(request, "tech")
    assert (a.read_bytes(), path.read_bytes()) == before
    assert not Path(packets[0]["output_paths"]["result"]).exists()


def test_timely_journal_crash_recovery_and_append_immutability(
    timely_lanes, monkeypatch
):
    from datetime import timedelta

    import supplement_agent as sa

    path, request, packets, clock, seal = timely_lanes
    a = seal("tech")
    original = a.read_bytes()
    materialize = sa._materialize_parent_draft

    def crash(*args):
        raise OSError("simulated interruption after journal commit")

    monkeypatch.setattr(sa, "_materialize_parent_draft", crash)
    with pytest.raises(OSError):
        sa.finalize_parent_draft(request, "tech")
    receipt = deepcopy(
        rc.load_manifest(path)["parent_supplement_finalizations"]["tech"]
    )
    assert a.read_bytes() == original
    clock.value += timedelta(seconds=310)
    monkeypatch.setattr(sa, "_materialize_parent_draft", materialize)
    sa.finalize_parent_draft(request, "tech")
    assert rc.file_sha256(a) == receipt["final_draft_sha256"]
    assert rc.load_manifest(path)["parent_supplement_finalizations"]["tech"] == receipt
    with (
        pytest.raises(rc.RunContractError, match="immutable"),
        rc.locked_manifest(path) as (manifest, sha),
    ):
        manifest["parent_supplement_finalizations"]["tech"]["finalized_at"] = (
            clock.value.isoformat()
        )
        rc.commit_manifest(path, manifest, sha)
