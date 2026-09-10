"""New frozen requests; only public HTTP responses are stubbed, never contract gates."""

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import article_broker as broker
import pytest
import run_contract as rc
from hub_utils import atomic_dump_json
from supplement_agent import assemble_result, finalize_parent_draft
from test_article_broker_contract import (
    new_run as frozen_run,  # noqa: F401 - fixture alias retains real builder
)

URL = "https://example.org/release"


@pytest.fixture
def new_run(frozen_run):  # noqa: F811 - pytest fixture dependency
    return frozen_run


def setup(new_run, **gap):
    path, root, now = new_run
    if "focus_config" not in rc.load_manifest(path)["artifacts"]:
        focus = root / "fixture-focus.json"
        atomic_dump_json(focus, {"filters": {"max_top10": 2}})
        rc.record_run_artifact(path, "focus_config", focus, now=now)
    request_path, request = rc.build_supplement_request(
        path,
        [
            {
                "gap_id": "tech",
                "lane": "TechRadar",
                "query_scope": "original release",
                "article_broker": True,
                "max_urls": 4,
                **gap,
            }
        ],
        article_broker_version=2,
        now=now,
    )
    return request_path, request["execution_packets"][0]


def search(request, outcome="matched", query="release", **changes):
    data = broker.operate(request, "tech", "reserve-query", query=query)
    reserved = data["query_reservations"][-1]
    receipt = {
        "request_sha256": data["request_sha256"],
        "gap_id": "tech",
        "reservation_id": reserved["id"],
        "tool": "web_search",
        "query": query,
        "responseId": "response-" + query,
        "outcome": outcome,
        "error": "provider failed" if outcome == "error" else None,
        "results": [{"url": URL, "title": "Original release"}]
        if outcome == "matched"
        else [],
        "proof_subset": {"text": "offline public tool response fixture"},
        "parent_attestation": "actual_public_tool_receipt",
        **changes,
    }
    return broker.operate(request, "tech", "record-query", receipt=receipt)


def network(
    monkeypatch,
    *,
    day=None,
    field="article:published_time",
    code=200,
    redirect=None,
    body=None,
    content_encoding="",
    response_headers=None,
    read_limits=None,
):
    calls = []
    day = day or datetime.now(timezone.utc).date().isoformat()
    raw = (
        body
        if body is not None
        else (
            f'<html><title>Original release</title><meta property="{field}" content="{day}"><article>'
            + "A substantive original product release and research announcement. " * 10
            + "</article></html>"
        ).encode()
    )

    class Response:
        status = code
        headers = response_headers if response_headers is not None else {
            "Content-Type": "text/html; charset=utf-8",
            **({"Content-Encoding": content_encoding} if content_encoding else {}),
            **({"Location": redirect} if redirect else {}),
        }
        content = None

        def __init__(self, url):
            self.url = url
            self.content = self
            self.offset = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def read(self, size):
            if read_limits is not None:
                read_limits.append(size)
            chunk = raw[self.offset:self.offset + size]
            self.offset += len(chunk)
            assert self.offset <= broker.MAX_BODY + 1
            return chunk

    class Session:
        def __init__(self, **kwargs):
            self.connector = kwargs["connector"]
            assert kwargs["trust_env"] is False
            assert kwargs["auto_decompress"] is False
            assert kwargs["headers"] == {"Accept-Encoding": "identity"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, url, **kwargs):
            assert kwargs == {"allow_redirects": False}
            calls.append(url)
            return Response(url)

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    return calls


def dynamic(data, candidate=True):
    result = {
        k: deepcopy(data[k])
        for k in (
            "started_at",
            "completed_at",
            "executed_queries",
            "access_log",
            "broker_evidence_sha256",
        )
    }
    result.update(
        status="no_increment",
        candidates=[],
        confidence="low",
        turns_used=1,
        halt_condition_met=True,
        bound_candidate_decisions=[],
    )
    if candidate:
        proof = data["proofs"][-1]
        date = proof["metadata"]["dates"][0]
        result.update(
            status="completed",
            confidence="medium",
            candidates=[
                {
                    "title": "Original release",
                    "url": URL,
                    "source": "Example",
                    "published_at": date["published_at"],
                    "published_at_source": date["published_at_source"],
                    "published_at_proof": date,
                    "broker_body_proof_sha256": proof["proof_sha256"],
                    "retrieved_at": proof["access"]["checked_at"],
                    "primary_domain": "technology",
                    "secondary_domains": [],
                    "source_type": "primary",
                    "identity_quality": "semantic",
                    "event_identity": {
                        "key_version": "1",
                        "primary_domain": "technology",
                        "actor": "Example",
                        "action": "released",
                        "object": "Original product",
                        "event_date": date["published_at"],
                    },
                    "access_check": proof["access"],
                    "summary": "Example released an original product; the article describes its capabilities and release scope.",
                }
            ],
        )
    return result


def test_article_to_date_owned_eligible(new_run, monkeypatch):
    request, packet = setup(new_run)
    calls = network(monkeypatch)
    search(request)
    broker.operate(request, "tech", "http", url=URL)
    data = broker.operate(request, "tech", "seal")
    draft = Path(packet["output_paths"]["draft"])
    atomic_dump_json(draft, dynamic(data))
    snapshot = Path(rc.load_manifest(new_run[0])["skill_path"]).parent
    for command in (
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            str(snapshot / "scripts/supplement_agent.py"),
            "finalize",
            "--parent",
            "--request",
            str(request),
            "--gap-id",
            "tech",
        ],
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            str(snapshot / "scripts/run_daily.py"),
            "finalize-supplement",
            "--manifest",
            str(new_run[0]),
            "--request",
            str(request),
            "--draft",
            str(draft),
        ],
    ):
        result = subprocess.run(command, cwd=snapshot, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    aggregate = rc.load_json(new_run[1] / "supplement_results.json", {})
    candidate = aggregate["results"][0]["candidates"][0]
    manifest = rc.load_manifest(new_run[0])
    assert rc.candidate_date_owned(
        candidate, rc.candidate_date_ownership(manifest, {"items": []}, aggregate)
    )
    assert rc.registered_candidate_lineage(manifest)[candidate["candidate_id"]][
        "eligible_hashes"
    ]
    assert candidate["access_check"] == data["access_log"][0]
    assert manifest["telemetry"]["summary"]["reserved_tokens"] == 150000
    assert manifest["telemetry"]["summary"]["combined_tokens"] is None
    assert calls == [URL]
    assert "substantive original" in data["proofs"][0]["body_text"]


def test_true_empty_zero_url_no_increment_degraded_coverage_hold(new_run):
    request, packet = setup(new_run)
    search(request, "empty")
    search(request, "empty", query="alternative agency original filing")
    data = broker.operate(request, "tech", "seal")
    atomic_dump_json(Path(packet["output_paths"]["draft"]), dynamic(data, False))
    draft, _ = finalize_parent_draft(request, "tech")
    _, aggregate = rc.register_supplement_results(
        new_run[0], request, [draft], publish_drafts=True
    )
    assert aggregate["status"] == "degraded"
    assert aggregate["results"][0]["coverage"] == {
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
    }
    rc.expire_execution_reservation(
        new_run[0], "supplemental", "tech", reason="terminal"
    )
    assert (
        rc.load_manifest(new_run[0])["telemetry"]["summary"]["reserved_tokens"]
        == 150000
    )


@pytest.mark.parametrize("outcome", ["error", "none"])
def test_no_search_or_error_cannot_be_empty(new_run, outcome):
    request, _ = setup(new_run)
    if outcome == "error":
        search(request, "error")
    with pytest.raises(rc.RunContractError, match="search proof"):
        broker.operate(request, "tech", "seal")


def test_query_reservation_limits_duplicates_and_pending(new_run):
    request, _ = setup(new_run, max_queries=1)
    data = broker.operate(request, "tech", "reserve-query", query="release")
    assert data["query_reservations"][0]["arguments"] == {
        "query": "release",
        "numResults": 5,
        "workflow": "none",
        "includeContent": False,
    }
    with pytest.raises(rc.RunContractError, match="unsettled"):
        broker.operate(request, "tech", "reserve-query", query="other")
    receipt = {
        "request_sha256": data["request_sha256"],
        "gap_id": "tech",
        "reservation_id": "query-1",
        "tool": "web_search",
        "query": "release",
        "responseId": "actual",
        "outcome": "empty",
        "error": None,
        "results": [],
        "proof_subset": {"text": "zero results"},
        "parent_attestation": "actual_public_tool_receipt",
    }
    broker.operate(request, "tech", "record-query", receipt=receipt)
    with pytest.raises(rc.RunContractError, match="duplicate"):
        broker.operate(request, "tech", "record-query", receipt=receipt)
    with pytest.raises(rc.RunContractError, match="limit"):
        broker.operate(request, "tech", "reserve-query", query="other")


@pytest.mark.parametrize(
    "mutation",
    [
        {"gap_id": "foreign"},
        {"request_sha256": "foreign"},
        {"error": "failure", "outcome": "empty", "results": []},
        {"proof_subset": {}},
    ],
)
def test_foreign_missing_ambiguous_proof_denied(new_run, mutation):
    request, _ = setup(new_run)
    with pytest.raises(rc.RunContractError):
        search(request, **mutation)
    with pytest.raises(rc.RunContractError, match="unsettled"):
        broker.operate(request, "tech", "seal")


@pytest.mark.parametrize(
    "field,day",
    [
        ("observed_at", "2026-09-08"),
        ("article:published_time", "unknown"),
        ("article:published_time", "2000-01-01"),
    ],
)
def test_body_unknown_observation_or_outwindow_excludes(
    new_run, monkeypatch, field, day
):
    request, _ = setup(new_run)
    network(monkeypatch, field=field, day=day)
    search(request)
    broker.operate(request, "tech", "http", url=URL)
    search(request, "empty", query="alternative dated original release")
    data = broker.operate(request, "tech", "seal")
    if day == "2000-01-01":
        with pytest.raises(rc.RunContractError, match="outside window"):
            assemble_result(request, "tech", dynamic(data))
    else:
        assert not data["proofs"][0]["metadata"]["dates"]
    result = dynamic(data, False)
    result.update(
        status="degraded",
        failure_kind="published_at_conflict",
        failure_reason="No eligible publication metadata",
    )
    packet = rc.load_json(request, {})["execution_packets"][0]
    atomic_dump_json(Path(packet["output_paths"]["draft"]), result)
    finalize_parent_draft(request, "tech")


def test_all_attempts_cap_and_missing_proof_tamper(new_run, monkeypatch):
    request, _ = setup(new_run)
    calls = network(monkeypatch, code=503)
    search(request)
    data = None
    for _ in range(4):
        data = broker.operate(request, "tech", "http", url=URL)
    assert data is not None
    assert len(data["access_log"]) == 4 and data["remaining_urls"] == 0
    with pytest.raises(rc.RunContractError, match="exhausted"):
        broker.operate(request, "tech", "http", url=URL)
    assert len(calls) == 4
    with (
        pytest.raises(rc.RunContractError, match="append-only"),
        rc.locked_manifest(new_run[0]) as (manifest, sha),
    ):
        manifest["article_broker_evidence"]["tech"]["events"].pop()
        rc.commit_manifest(new_run[0], manifest, sha)
    (new_run[1] / "broker_tech_body_1.json").unlink()
    with pytest.raises(rc.RunContractError, match="proof missing"):
        broker.evidence(request, "tech")


@pytest.mark.parametrize("terminal", [True, False])
def test_terminal_or_expired_clock_blocks_http_before_io(
    new_run, monkeypatch, terminal
):
    request, packet = setup(new_run)
    calls = network(monkeypatch)
    search(request)
    if terminal:
        atomic_dump_json(
            Path(packet["progress"]["state_path"]),
            {"progress_id": "tech", "terminal_status": "declare_lost"},
        )
    else:
        manifest = rc.load_manifest(new_run[0])
        # Adversarial old clock fixture, not a mutation API.
        for event in manifest["article_broker_evidence"]["tech"]["events"]:
            event["at"] = (new_run[2] + timedelta(seconds=1)).isoformat()
        atomic_dump_json(new_run[0], manifest)
        import article_broker

        class LateClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(timezone.utc) + timedelta(seconds=500)

        monkeypatch.setattr(article_broker, "datetime", LateClock)
    with pytest.raises(rc.RunContractError, match="terminal|expired"):
        broker.operate(request, "tech", "http", url=URL)
    assert not calls


def test_private_redirect_not_followed(new_run, monkeypatch):
    request, _ = setup(new_run)
    calls = network(monkeypatch, code=302, redirect="http://127.0.0.1/secret")
    search(request)
    data = broker.operate(request, "tech", "http", url=URL)
    assert calls == [URL]
    assert data["access_log"][0]["status"] == "blocked"


@pytest.mark.parametrize(
    "url",
    [
        "file:///secret",
        "http://127.0.0.1/a",
        "http://10.0.0.1/a",
        "http://198.18.0.0/a",
        "http://198.18.0.21/a",
        "http://198.19.255.255/a",
        "http://[::ffff:198.18.0.21]/a",
        "https://localhost/a",
        "https://user:pass@example.org/a",
        "http://[::1]/a",
    ],
)
def test_nonpublic_urls_rejected(url):
    with pytest.raises(rc.RunContractError, match="unsafe"):
        broker.validate_url(url)


def test_missing_ledger_no_ordinary_fallback(new_run):
    request, _ = setup(new_run)
    manifest = rc.load_manifest(new_run[0])
    manifest.pop("article_broker_evidence")
    atomic_dump_json(new_run[0], manifest)
    with pytest.raises(rc.RunContractError, match="ledger missing"):
        broker.evidence(request, "tech")


@pytest.mark.parametrize("frozen_run", [4], indirect=True)
def test_four_bound_v2_denied(new_run):
    with pytest.raises(rc.RunContractError, match="remaining URL"):
        setup(new_run, verify_bound_candidates=True)


def test_candidate_tamper_denied(new_run, monkeypatch):
    request, packet = setup(new_run)
    network(monkeypatch)
    search(request)
    broker.operate(request, "tech", "http", url=URL)
    data = broker.operate(request, "tech", "seal")
    for field, value in (
        ("published_at_source", "observed_at"),
        ("broker_body_proof_sha256", "fake"),
        ("retrieved_at", data["started_at"]),
    ):
        draft = dynamic(data)
        draft["candidates"][0][field] = value
        with pytest.raises(rc.RunContractError, match="broker"):
            assemble_result(request, "tech", draft)
    draft = dynamic(data)
    draft["access_log"] = []
    with pytest.raises(rc.RunContractError, match="authoritative"):
        assemble_result(request, "tech", draft)


def test_snippet_and_portal_not_article(new_run, monkeypatch):
    request, _ = setup(new_run)
    network(
        monkeypatch,
        body=b'<html><meta property="article:published_time" content="2026-09-08">snippet only</html>',
    )
    search(request)
    data = broker.operate(request, "tech", "http", url=URL)
    assert data["access_log"][0]["status"] == "blocked"
    assert not data["proofs"][0]["metadata"]["article"]


@pytest.mark.parametrize("frozen_run", [1], indirect=True)
def test_bound_before_query_retains_clock(new_run, monkeypatch):
    request, _ = setup(new_run, verify_bound_candidates=True)
    calls = network(monkeypatch)
    checkpoint = broker.operate(request, "tech", "checkpoint")
    with pytest.raises(rc.RunContractError, match="required bound"):
        broker.operate(request, "tech", "reserve-query", query="release")
    broker.operate(request, "tech", "http", url="https://example.org/article-0")
    data = search(request)
    assert data["remaining_urls"] == 3
    assert data["started_at"] == checkpoint["started_at"]
    assert calls == ["https://example.org/article-0"]


def test_private_dns_blocked_before_connection(monkeypatch):
    import asyncio
    import socket

    async def private_address(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", private_address)
    final, code, body, content_type, hops, error = asyncio.run(
        broker._transport(URL, 1.0)
    )
    assert error and "private/local DNS" in error
    assert code is None and not hops and not body


def test_transport_body_limit(monkeypatch):
    import asyncio

    calls = network(monkeypatch, body=b"x" * (broker.MAX_BODY + 1))
    final, code, body, content_type, hops, error = asyncio.run(
        broker._transport(URL, 1.0)
    )
    assert error and "body byte limit" in error
    assert calls == [URL] and code == 200


def test_malformed_metadata_settles_http_and_seals(new_run, monkeypatch):
    request, _ = setup(new_run)
    raw = (
        b"<html><title>Untrusted title</title><article>"
        b'<meta property="article:published_time" content="2026-09-08">'
        + b"Article content. " * 30
        + b"<![bogus]></article></html>"
    )
    calls = network(monkeypatch, body=raw)
    def parse_failure(self, text):
        raise AssertionError("injected unexpected parser failure")
    monkeypatch.setattr(broker._ArticleMetadata, "feed", parse_failure)
    search(request)
    data = broker.operate(request, "tech", "http", url=URL)
    proof = data["proofs"][0]
    assert proof["access"]["status"] == "blocked"
    assert "METADATA_PARSE_FAILED" in proof["access"]["error_code"]
    assert proof["metadata"] == {
        "recognizable_body": False,
        "article": False,
        "title": "",
        "dates": [],
        "parse_error": "METADATA_PARSE_FAILED:AssertionError",
    }
    assert base64.b64decode(proof["body_base64"]) == raw
    assert proof["body_sha256"] == hashlib.sha256(raw).hexdigest()
    manifest = rc.load_manifest(new_run[0])
    assert (
        manifest["article_broker_evidence"]["tech"]["events"][-1]["kind"]
        == "http_recorded"
    )
    search(request, "empty", query="alternative agency original filing")
    sealed = broker.operate(request, "tech", "seal")
    assert sealed["completed_at"] and sealed["remaining_urls"] == 3
    assert sealed["proofs"] == data["proofs"] and calls == [URL]


@pytest.mark.parametrize("unit", ["界😀", '\\"\\\\\\n\\t\\x00'])
def test_broker_cli_four_max_bodies_bounded_and_local_proofs_unchanged(
    new_run, monkeypatch, capsys, unit
):
    import supplement_agent

    request, _ = setup(new_run)
    prefix = ("<html><title>" + unit * 2000 + "</title><article>").encode("utf-8")
    repeated = (unit * broker.MAX_BODY).encode("utf-8")
    raw = prefix + repeated[: broker.MAX_BODY - len(prefix)]
    assert len(raw) == broker.MAX_BODY
    calls = network(monkeypatch, body=raw, code=503)
    search(request, proof_subset={"text": "receipt" * 8000})
    for _ in range(4):
        broker.operate(request, "tech", "http", url=URL)
    internal = broker.operate(request, "tech", "seal")
    paths = [new_run[0], request, *new_run[1].glob("broker_tech_body_*.json")]
    before = {p: p.read_bytes() for p in paths}
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "supplement_agent.py",
            "broker-evidence",
            "--parent",
            "--request",
            str(request),
            "--gap-id",
            "tech",
        ],
    )
    assert supplement_agent.main() == 0
    output = capsys.readouterr().out
    assert len(output.encode("utf-8")) <= 40000
    delivered = json.loads(output)
    assert "body_base64" not in output and "proof_subset" not in output
    assert delivered["broker_evidence_sha256"] == internal["broker_evidence_sha256"]
    assert delivered["access_log"] == internal["access_log"]
    assert delivered["executed_queries"] == internal["executed_queries"]
    assert delivered["ledger_path"] == str(new_run[0].resolve())
    assert delivered["query_receipts"][0]["receipt_sha256"] == broker.digest(
        internal["query_receipts"][0]
    )
    for index, proof in enumerate(delivered["proofs"]):
        assert proof["body_text_truncated"] is True
        assert internal["proofs"][index]["body_text"].startswith(proof["body_text"])
        assert (
            len(json.dumps(proof["body_text"], ensure_ascii=False).encode("utf-8"))
            <= 4000
        )
        assert proof["body_sha256"] == hashlib.sha256(raw).hexdigest()
        assert proof["body_bytes"] == broker.MAX_BODY
        assert rc.file_sha256(Path(proof["proof_path"])) == proof["proof_sha256"]
        assert proof["metadata"]["omitted"] is True
    assert {p: p.read_bytes() for p in paths} == before
    assert broker.evidence(request, "tech") == internal
    assert len(calls) == 4


@pytest.mark.parametrize(
    "command",
    [
        "broker-checkpoint",
        "broker-reserve-query",
        "broker-record-query",
        "broker-http",
        "broker-seal",
        "broker-evidence",
    ],
)
def test_broker_cli_every_broker_command_compacts_payload_before_print(
    new_run, monkeypatch, capsys, command
):
    import supplement_agent

    request, _ = setup(new_run)
    unit = "SECRET_BODY_TOKEN界😀"
    prefix = ("<html><title>" + unit * 300 + "</title><article>").encode("utf-8")
    repeated = (unit * broker.MAX_BODY).encode("utf-8")
    raw = prefix + repeated[: broker.MAX_BODY - len(prefix)]
    receipt_secret = "SECRET_PROOF_SUBSET" * 2500
    calls = network(monkeypatch, body=raw, code=503)

    def receipt_for(data):
        reserved = data["query_reservations"][-1]
        return {
            "request_sha256": data["request_sha256"],
            "gap_id": "tech",
            "reservation_id": reserved["id"],
            "tool": "web_search",
            "query": reserved["query"],
            "responseId": "response-" + reserved["query"],
            "outcome": "matched",
            "error": None,
            "results": [{"url": URL, "title": "Original release"}],
            "proof_subset": {"text": receipt_secret},
            "parent_attestation": "actual_public_tool_receipt",
        }

    argv = [
        "supplement_agent.py",
        command,
        "--parent",
        "--request",
        str(request),
        "--gap-id",
        "tech",
    ]
    if command == "broker-reserve-query":
        argv += ["--query", "release"]
    elif command == "broker-record-query":
        receipt_path = new_run[1] / "cli-record-query-receipt.json"
        atomic_dump_json(
            receipt_path,
            receipt_for(broker.operate(request, "tech", "reserve-query", query="release")),
        )
        argv += ["--receipt", str(receipt_path)]
    elif command == "broker-http":
        search(request, proof_subset={"text": receipt_secret})
        argv += ["--url", URL]
    elif command in {"broker-seal", "broker-evidence"}:
        search(request, proof_subset={"text": receipt_secret})
        broker.operate(request, "tech", "http", url=URL)
        if command == "broker-seal":
            search(request, "empty", query="alternative original source", proof_subset={"text": receipt_secret})

    monkeypatch.setattr(sys, "argv", argv)
    assert supplement_agent.main() == 0
    output = capsys.readouterr().out
    delivered = json.loads(output)
    internal = broker.evidence(request, "tech")

    assert len(output.encode("utf-8")) <= 40000
    assert "proof_subset" not in output
    assert "body_base64" not in output
    assert receipt_secret not in output
    assert delivered["broker_evidence_sha256"] == internal["broker_evidence_sha256"]
    assert delivered["access_log"] == internal["access_log"]
    assert delivered["executed_queries"] == internal["executed_queries"]
    assert delivered["ledger_path"] == str(new_run[0].resolve())

    for index, receipt in enumerate(internal["query_receipts"]):
        assert receipt["proof_subset"] == {"text": receipt_secret}
        assert delivered["query_receipts"][index]["receipt_sha256"] == broker.digest(receipt)
        assert "proof_subset" not in delivered["query_receipts"][index]

    for index, proof in enumerate(internal["proofs"]):
        assert base64.b64decode(proof["body_base64"]) == raw
        delivered_proof = delivered["proofs"][index]
        assert "body_base64" not in delivered_proof
        assert delivered_proof["body_text_truncated"] is True
        assert proof["body_text"].startswith(delivered_proof["body_text"])
        assert (
            len(
                json.dumps(delivered_proof["body_text"], ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            <= 4000
        )
        assert delivered_proof["body_sha256"] == hashlib.sha256(raw).hexdigest()
        assert delivered_proof["body_bytes"] == broker.MAX_BODY
        assert rc.file_sha256(Path(delivered_proof["proof_path"])) == delivered_proof["proof_sha256"]

    if command in {"broker-http", "broker-seal", "broker-evidence"}:
        assert calls == [URL]
    else:
        assert calls == []


def test_source_checked_fingerprint_blocks_io(new_run, monkeypatch):
    request, packet = setup(new_run)
    assert str(request.resolve()) in packet["task_message"]
    assert '--gap-id "tech"' in packet["task_message"]
    calls = network(monkeypatch)
    search(request)
    atomic_dump_json(
        Path(packet["progress"]["state_path"]),
        {"progress_id": "tech", "previous_fingerprint": {"milestone_seq": 2}},
    )
    with pytest.raises(rc.RunContractError, match="source_checked"):
        broker.operate(request, "tech", "http", url=URL)
    assert not calls


@pytest.fixture
def dns_connection_boundary(monkeypatch):
    """Exercise real aiohttp DNS/pinning but stop before any socket connection."""
    import asyncio
    import socket

    dns_calls = []
    connections = []

    async def stop(self, *args, **kwargs):
        assert self._use_dns_cache is False
        connections.extend(kwargs["addr_infos"])
        raise OSError("OFFLINE_CONNECTION_BOUNDARY")

    monkeypatch.setattr(aiohttp.TCPConnector, "_wrap_create_connection", stop)

    def run(answers):
        async def resolve(self, host, port, **kwargs):
            dns_calls.append((host, port))
            return [
                (
                    socket.AF_INET6 if ":" in address else socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (address, port, 0, 0) if ":" in address else (address, port),
                )
                for address in answers
            ]

        monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
        result = asyncio.run(broker._transport(URL, 1.0))
        return result, dns_calls, connections

    return run


@pytest.mark.parametrize("address", [
    "198.18.0.0", "198.18.0.21", "198.18.255.255", "198.19.0.0", "198.19.255.255",
    "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8",
    # Adjacent addresses are global already, not part of the Fake-IP exception.
    "198.17.255.255", "198.20.0.0",
])
def test_transport_domain_dns_allowed_addresses_pinned_unchanged(
    dns_connection_boundary, address
):
    result, dns_calls, connections = dns_connection_boundary([address])
    assert result[-1] and "OFFLINE_CONNECTION_BOUNDARY" in result[-1]
    assert dns_calls == [("example.org", 443)]
    assert [entry[4][0] for entry in connections] == [address]
    assert all(entry[4][1] == 443 for entry in connections)
    assert result[1] is None and result[2] == b"" and result[4] == []


def test_clash_fake_ip_network_exact_edges():
    import ipaddress

    assert str(broker.CLASH_FAKE_IP_NETWORK) == "198.18.0.0/15"
    for address in ("198.18.0.0", "198.19.255.255"):
        assert ipaddress.ip_address(address) in broker.CLASH_FAKE_IP_NETWORK
    for address in ("198.17.255.255", "198.20.0.0", "::ffff:198.18.0.21"):
        assert ipaddress.ip_address(address) not in broker.CLASH_FAKE_IP_NETWORK


@pytest.mark.parametrize("address", [
    "10.0.0.0", "10.255.255.255", "172.16.0.0", "172.31.255.255",
    "192.168.0.0", "192.168.255.255", "127.0.0.1", "127.255.255.255",
    "169.254.0.0", "169.254.169.254", "169.254.255.255", "0.0.0.0", "0.255.255.255",
    "100.64.0.1", "192.0.2.1", "198.51.100.1", "203.0.113.1", "240.0.0.1",
    "fc00::1", "fd00::1", "fe80::1", "::1", "::",
    "::ffff:10.0.0.1", "::ffff:172.16.0.1", "::ffff:192.168.0.1",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:0.0.0.0",
    "::ffff:198.18.0.0", "::ffff:198.18.0.21", "::ffff:198.19.255.255",
])
def test_transport_domain_dns_non_global_outside_exception_blocked(
    dns_connection_boundary, address
):
    result, dns_calls, connections = dns_connection_boundary([address])
    assert result[-1] and "private/local DNS destination" in result[-1]
    assert dns_calls == [("example.org", 443)] and connections == []
    assert result[1] is None and result[2] == b"" and result[4] == []


@pytest.mark.parametrize("answers", [
    [],
    ["198.18.0.21", "10.0.0.1"],
    ["10.0.0.1", "198.18.0.21"],
    ["8.8.8.8", "198.18.0.21", "fd00::1"],
    ["198.18.0.21", "::ffff:198.18.0.21"],
    ["8.8.8.8", "169.254.169.254"],
])
def test_transport_domain_dns_empty_or_mixed_private_rejected_entirely(
    dns_connection_boundary, answers
):
    result, _, connections = dns_connection_boundary(answers)
    assert result[-1] and "private/local DNS destination" in result[-1]
    assert connections == []


def test_transport_domain_dns_mixed_allowed_answers_pinned(dns_connection_boundary):
    answers = ["198.18.0.21", "8.8.8.8", "2606:4700:4700::1111"]
    result, _, connections = dns_connection_boundary(answers)
    assert result[-1] and "OFFLINE_CONNECTION_BOUNDARY" in result[-1]
    assert [entry[4][0] for entry in connections] == answers


@pytest.mark.parametrize("target", [
    "http://198.18.0.0/secret", "http://198.19.255.255/secret",
    "http://10.0.0.1/secret", "http://172.16.0.1/secret", "http://192.168.0.1/secret",
    "http://169.254.169.254/secret", "http://[fd00::1]/secret",
    "http://[::ffff:198.18.0.21]/secret", "http://localhost/secret",
    "https://user:pass@example.org/secret",
])
def test_transport_nonpublic_redirect_still_blocked(monkeypatch, target):
    import asyncio

    calls = network(monkeypatch, code=302, redirect=target)
    result = asyncio.run(broker._transport(URL, 1.0))
    assert result[-1] and "unsafe public URL" in result[-1]
    assert calls == [URL]


def test_transport_redirect_domain_private_dns_revalidated(
    monkeypatch, dns_connection_boundary
):
    from yarl import URL as CanonicalURL

    original_get = aiohttp.ClientSession.get

    class Redirect:
        url = CanonicalURL(URL)
        status = 302
        headers = {"Location": "https://redirect.example/secret"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    def get(session, url, **kwargs):
        assert kwargs == {"allow_redirects": False}
        assert session.trust_env is False
        return Redirect() if url == URL else original_get(session, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "get", get)
    result, dns_calls, connections = dns_connection_boundary(["198.18.0.21", "10.0.0.1"])
    assert result[-1] and "private/local DNS destination" in result[-1]
    assert dns_calls == [("redirect.example", 443)] and connections == []
    assert result[1] is None
    assert result[4] == [{"url": URL, "status": 302}]


def _bounded_article(size):
    prefix = b'<html><title>Bounded release</title><meta name="PubDate" content="2026-09-09 08:00"><article>'
    suffix = b'</article></html>'
    return prefix + b'a' * (size - len(prefix) - len(suffix)) + suffix


@pytest.mark.parametrize('size', [broker.MAX_BODY - 1, broker.MAX_BODY, broker.MAX_BODY + 1])
def test_transport_cap_edges_complete_or_no_retained_prefix(monkeypatch, size):
    import asyncio

    network(monkeypatch, body=_bounded_article(size))
    result = asyncio.run(broker._transport(URL, 1.0))
    if size > broker.MAX_BODY:
        assert result[-1] and 'body byte limit' in result[-1]
        assert result[2] == b''
    else:
        assert result[-1] is None
        assert len(result[2]) == size


@pytest.mark.parametrize('encoding', ['gzip', 'br', 'deflate', 'identity, gzip'])
def test_transport_unexpected_compression_rejected_without_body(monkeypatch, encoding):
    import asyncio

    calls = network(monkeypatch, body=_bounded_article(500), content_encoding=encoding)
    result = asyncio.run(broker._transport(URL, 1.0))
    assert result[-1] and 'Content-Encoding' in result[-1]
    assert result[2] == b'' and calls == [URL]


@pytest.mark.parametrize('encodings, accepted', [
    ([], True), (['identity'], True), (['IdEnTiTy'], True),
    (['identity', 'gzip'], False), (['IdEnTiTy', 'GZiP'], False),
    (['gzip', 'identity'], False), (['identity', 'identity'], False),
    (['identity, gzip'], False), (['identity, identity'], False), ([''], False),
])
def test_p1_transport_all_content_encoding_headers(monkeypatch, encodings, accepted):
    import asyncio

    from multidict import CIMultiDict, CIMultiDictProxy

    headers = CIMultiDict([('Content-Type', 'text/html')])
    for index, value in enumerate(encodings):
        headers.add('Content-Encoding' if index == 0 else 'cOnTeNt-EnCoDiNg', value)
    read_limits = []
    calls = network(monkeypatch, body=_bounded_article(500),
                    response_headers=CIMultiDictProxy(headers), read_limits=read_limits)
    result = asyncio.run(broker._transport(URL, 1.0))
    assert calls == [URL]
    if accepted:
        assert result[-1] is None and read_limits
    else:
        assert result[-1] and 'Content-Encoding' in result[-1]
        assert result[2] == b'' and read_limits == []


def test_overflow_settles_blocked_proof_and_cannot_verify(new_run, monkeypatch):
    request, _ = setup(new_run)
    calls = network(monkeypatch, body=_bounded_article(broker.MAX_BODY + 1))
    search(request)
    data = broker.operate(request, 'tech', 'http', url=URL)
    assert data['remaining_urls'] == 3 and calls == [URL]
    proof = data['proofs'][0]
    assert proof['access']['status'] == 'blocked'
    assert proof['body_base64'] == ''
    assert proof['body_text_truncated'] is True
    assert not proof['metadata']['recognizable_body'] and not proof['metadata']['dates']
    search(request, "empty", query="alternative original source")
    assert broker.operate(request, 'tech', 'seal')['completed_at']


NHSA_URL = 'https://www.nhsa.gov.cn/art/2026/9/9/art_14_22050.html'


def _nhsa_body(meta='<meta content="2026-09-09 08:00" name="PubDate"/>', title='国家医保局立项指南编制工作', extra=''):
    return ('<!DOCTYPE html><!--[if lt IE 9]><script>hidden</script><![endif]-->'
            '<![if !IE]><div>普通条件声明</div><![endif]><html><head><title>' + title +
            '</title>' + meta + '</head><body><div class="article-content">' +
            '全国医疗服务收费迈入统一新阶段。' * 50 + extra + '</div></body></html>')


@pytest.mark.parametrize('charset', ['utf-8', 'gb18030', 'gb2312'])
def test_nhsa_conditional_declarations_pubdate_charset_fixture(charset):
    from supplement_agent import _document_body_evidence

    body = _nhsa_body().encode(charset)
    meta = broker.body_metadata(body, 'text/html; charset=' + charset, NHSA_URL)
    assert meta['article'] and meta['recognizable_body'] and 'parse_error' not in meta
    assert meta['title'] == '国家医保局立项指南编制工作'
    assert meta['dates'] == [{'field': 'pubdate', 'raw': '2026-09-09 08:00',
                              'published_at': '2026-09-09', 'published_at_source': 'body_meta:pubdate'}]
    evidence = _document_body_evidence(body, 'text/html; charset=' + charset, truncated=False)
    assert '全国医疗服务收费' in evidence['text'] and 'hidden' not in evidence['text']
    assert evidence['publication_metadata'][0]['field'] == 'pubdate'


@pytest.mark.parametrize('raw', ['2026-09-09 08:00:59', '2026年9月9日'])
def test_explicit_pubdate_source_local_calendar_day(raw):
    meta = broker.body_metadata(_nhsa_body(f'<meta name="PubDate" content="{raw}">').encode(), 'text/html', NHSA_URL)
    assert meta['article'] and meta['dates'][0]['published_at'] == '2026-09-09'
    assert meta['dates'][0]['raw'] == raw


@pytest.mark.parametrize('meta', [
    '', '<meta name="dateModified" content="2026-09-09">',
    '<meta name="retrieved_at" content="2026-09-09">',
    '<meta name="PubDate" content="2026-02-30 08:00">',
    '<meta name="PubDate" content="2026-09-09 25:00">',
    '<meta name="PubDate" content="2026-09-09 08:00:60">',
    '<meta name="PubDate" content="2026-09-09 08:00"><meta itemprop="datePublished" content="2026-09-08">',
])
def test_nhsa_missing_invalid_conflicting_publication_never_article(meta):
    result = broker.body_metadata(_nhsa_body(meta).encode(), 'text/html', NHSA_URL)
    assert not result['article'] and not result['dates']


@pytest.mark.parametrize('invalid_meta', [
    '<meta name="PubDate" content="2026-02-30 08:00">',
    '<meta itemprop="datePublished" content="2026-02-30">',
    '<meta property="article:published_time" content="not-a-date">',
    '<meta name="PubDate" content="">', '<meta itemprop="datePublished">',
])
def test_p1_nhsa_valid_plus_malformed_publication_blocks_only_fallback(invalid_meta):
    valid = '<meta name="PubDate" content="2026-09-09 08:00">'
    for metadata in (valid + invalid_meta, invalid_meta + valid):
        body = _nhsa_body(metadata).encode()
        result = broker.body_metadata(body, 'text/html', NHSA_URL)
        assert result['recognizable_body'] and result['dates']
        assert not result['article']
        # Existing explicit article classification and valid date extraction are unchanged.
        result = broker.body_metadata(body + b'<article></article>', 'text/html', URL)
        assert result['article'] and result['dates']


@pytest.mark.parametrize('meta', [
    '<meta name="PubDate" content="2026-09-09 08:00">',
    '<meta itemprop="datePublished" content="2026-09-09">',
    '<meta property="article:published_time" content="2026-09-09">',
    '<meta name="PubDate" content="2026-09-09 08:00"><meta itemprop="datePublished" content="2026-09-09">',
])
def test_p1_nhsa_any_supported_valid_publication_requires_matching_url(meta):
    body = _nhsa_body(meta).encode()
    assert broker.body_metadata(body, 'text/html', NHSA_URL)['article']
    assert not broker.body_metadata(body, 'text/html', NHSA_URL.replace('/9/9/', '/9/8/'))['article']


def test_p1_nhsa_conflicting_valid_publication_blocks_fallback():
    body = _nhsa_body('<meta name="PubDate" content="2026-09-09 08:00">'
                      '<meta itemprop="datePublished" content="2026-09-08">').encode()
    result = broker.body_metadata(body, 'text/html', NHSA_URL)
    assert not result['article'] and not result['dates']


@pytest.mark.parametrize('url', [
    NHSA_URL.replace('/2026/9/9/', '/2026/9/8/'),
    NHSA_URL.replace('www.nhsa.gov.cn', 'nhsa.gov.cn'),
    NHSA_URL.replace('www.nhsa.gov.cn', 'www.nhsa.gov.cn.evil.example'),
    NHSA_URL.replace('www.nhsa.gov.cn', 'other.gov.cn'),
    NHSA_URL.replace('www.nhsa.gov.cn', 'evil.www.nhsa.gov.cn'),
    'https://www.nhsa.gov.cn/search', 'https://www.nhsa.gov.cn/',
    NHSA_URL + '/', NHSA_URL.replace('/art/', '/ART/'),
])
def test_nhsa_layout_exception_exact_host_path_and_date_only(url):
    assert not broker.body_metadata(_nhsa_body().encode(), 'text/html', url)['article']


@pytest.mark.parametrize('change', [{'title': ''}, {'extra': 'Access Denied'}, {'extra': '<title>Just a moment</title>'}])
def test_nhsa_layout_no_title_or_softchallenge_rejected(change):
    assert not broker.body_metadata(_nhsa_body(**change).encode(), 'text/html', NHSA_URL)['article']


@pytest.mark.parametrize('declaration', ['<![bogus]>', '<![if !IE]>', '<![endif]>', '<!--[if IE]>stuff<![endif]-->'])
def test_ordinary_declarations_not_parse_fault(declaration):
    result = broker.body_metadata(_bounded_article(700) + declaration.encode(), 'text/html', URL)
    assert 'parse_error' not in result and result['article'] and result['dates']


def test_itemprop_datepublished_not_datemodified():
    body = ('<title>Original release</title><article>' + 'Visible release. ' * 30 +
            '<meta itemprop="datePublished" content="2026-09-09">' +
            '<meta itemprop="dateModified" content="2026-09-10"></article>').encode()
    result = broker.body_metadata(body, 'text/html', URL)
    assert result['dates'] == [{'field': 'datePublished', 'raw': '2026-09-09',
                               'published_at': '2026-09-09', 'published_at_source': 'body_meta:datePublished'}]


@pytest.mark.parametrize('unit', ['界😀', '\\"\n\t\x00'])
def test_broker_visible_excerpt_hash_and_both_projection_bounds(new_run, monkeypatch, unit):
    from supplement_agent import _compact_broker_cli_evidence

    raw = ('<html><article><script>SECRET_HIDDEN</script>' + unit * 5000 + '</article></html>').encode()
    request, _ = setup(new_run)
    calls = network(monkeypatch, body=raw)
    search(request)
    data = broker.operate(request, 'tech', 'http', url=URL)
    internal = data['proofs'][0]
    cli = _compact_broker_cli_evidence(request, 'tech', data)['proofs'][0]
    for proof, cap in [(internal, 6000), (cli, 4000)]:
        assert len(json.dumps(proof['body_text'], ensure_ascii=False).encode()) <= cap
        assert proof['body_text_truncated']
        assert 'SECRET_HIDDEN' not in proof['body_text']
        assert proof['body_text_sha256'] == hashlib.sha256(proof['body_text'].encode()).hexdigest()
        assert proof['body_sha256'] == hashlib.sha256(raw).hexdigest()
    assert len(calls) == 1 and 'body_base64' not in cli
    assert base64.b64decode(internal['body_base64']) == raw


def test_slow_synchronous_metadata_cannot_return_late_verified(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    network(monkeypatch, body=_bounded_article(700))
    clock = [100.0]
    original = broker.body_metadata
    def slow_metadata(*args):
        metadata = original(*args)
        clock[0] = 108.01
        return metadata
    monkeypatch.setattr(broker, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(broker, 'body_metadata', slow_metadata)
    result = asyncio.run(broker._transport(URL, 8.0))
    assert result[1] == 200 and result[2] == _bounded_article(700)
    assert result[-1] and 'HTTP deadline exceeded' in result[-1]


def test_oversized_raw_proof_denied_by_same_transport_cap(new_run, monkeypatch):
    request, _ = setup(new_run)
    network(monkeypatch)
    search(request)
    broker.operate(request, 'tech', 'http', url=URL)
    manifest = rc.load_manifest(new_run[0])
    event = manifest['article_broker_evidence']['tech']['events'][-1]
    path = Path(event['proof_path'])
    proof = rc.load_json(path, {})
    raw = _bounded_article(broker.MAX_BODY + 1)
    proof['body_base64'] = base64.b64encode(raw).decode()
    proof['body_sha256'] = hashlib.sha256(raw).hexdigest()
    atomic_dump_json(path, proof)
    event['proof_sha256'] = rc.file_sha256(path)
    atomic_dump_json(new_run[0], manifest)
    with pytest.raises(rc.RunContractError, match='body hash invalid'):
        broker.evidence(request, 'tech')


# Stage C continuation: real ledger/registration gates, offline HTTP and parent receipts.
def test_stage_c_first_failure_alternative_then_good(new_run, monkeypatch):
    request, _ = setup(new_run, lane="Sentinel", max_queries=2)
    alternative = "https://other.example/original-release"
    data = search(request, results=[{"url": URL, "title": "Blocked lead"},
                                    {"url": alternative, "title": "Alternative original"}])
    assert len(data["query_receipts"][0]["results"]) == 2
    calls = network(monkeypatch, code=403)
    data = broker.operate(request, "tech", "http", url=URL)
    assert data["next_action"]["action"] == "http_discovered"
    assert data["next_action"]["available_discovered_urls"] == [alternative]
    before = new_run[0].read_bytes()
    with pytest.raises(rc.RunContractError, match="seal not eligible"):
        broker.operate(request, "tech", "seal")
    assert new_run[0].read_bytes() == before
    good_calls = network(monkeypatch)
    data = broker.operate(request, "tech", "http", url=alternative)
    assert data["next_action"]["stop_reason"] == "candidate_supply_threshold"
    assert data["next_action"]["usable_article_count"] == 1
    sealed = broker.operate(request, "tech", "seal")
    assert sealed["completed_at"] and len(sealed["access_log"]) == 2
    assert calls == [URL] and good_calls == [alternative]


def test_stage_c_first_empty_and_query_error_do_not_seal(new_run):
    request, _ = setup(new_run, max_queries=2)
    data = search(request, "empty")
    assert not data["next_action"]["stop_eligible"]
    assert data["next_action"]["action"] == "search_different"
    with pytest.raises(rc.RunContractError, match="seal not eligible"):
        broker.operate(request, "tech", "seal")
    data = search(request, "error", query="alternative agency announcement")
    assert data["next_action"]["action"] == "terminal_failure"
    assert data["next_action"]["stop_reason"] == "error_search_proof"
    with pytest.raises(rc.RunContractError, match="search proof"):
        broker.operate(request, "tech", "seal")


def test_stage_c_blocked_alternatives_second_search(new_run, monkeypatch):
    request, _ = setup(new_run, max_queries=2)
    alternative = "https://other.example/original-release"
    search(request, results=[{"url": URL, "title": "First"}, {"url": alternative, "title": "Other"}])
    network(monkeypatch, code=403)
    broker.operate(request, "tech", "http", url=URL)
    data = broker.operate(request, "tech", "http", url=alternative)
    assert data["next_action"]["action"] == "search_different"
    data = search(request, "empty", query="regulator original filing")
    assert data["next_action"]["stop_reason"] == "no_useful_alternatives"
    assert broker.operate(request, "tech", "seal")["completed_at"]


@pytest.mark.parametrize("frozen_run", [1], indirect=True)
def test_stage_c_bound_only_no_query_registration(new_run, monkeypatch):
    request, packet = setup(new_run, verify_bound_candidates=True, max_queries=2)
    url = "https://example.org/article-0"
    network(monkeypatch)
    data = broker.operate(request, "tech", "http", url=url)
    assert data["next_action"]["bound_only_complete"]
    data = broker.operate(request, "tech", "seal")
    draft = dynamic(data)
    draft["candidates"][0].update(url=url, candidate_id=rc.candidate_ref(url))
    draft["bound_candidate_decisions"] = [{"candidate_id": rc.candidate_ref(url),
                                           "decision": "registered", "reason": "Body/date evidence read"}]
    atomic_dump_json(Path(packet["output_paths"]["draft"]), draft)
    ready, _ = finalize_parent_draft(request, "tech")
    _, aggregate = rc.register_supplement_results(new_run[0], request, [ready], publish_drafts=True)
    assert aggregate["results"][0]["executed_queries"] == []
    assert aggregate["results"][0]["coverage"]["attempted"] == 1


def test_stage_c_supply_one_good_does_not_meet_target(new_run, monkeypatch):
    focus = new_run[1] / "focus.json"
    atomic_dump_json(focus, {"filters": {"max_top10": 10}})
    rc.record_run_artifact(new_run[0], "focus_config", focus)
    request, _ = setup(new_run, max_queries=2)
    network(monkeypatch)
    search(request)
    data = broker.operate(request, "tech", "http", url=URL)
    assert data["next_action"]["candidate_supply_threshold"] > 1
    assert not data["next_action"]["stop_eligible"]
    with pytest.raises(rc.RunContractError, match="seal not eligible"):
        broker.operate(request, "tech", "seal")


def test_stage_c_pending_zero_work_and_expired_advice_no_io(new_run, monkeypatch):
    request, _ = setup(new_run, max_queries=2)
    calls = network(monkeypatch)
    data = broker.operate(request, "tech", "checkpoint")
    assert not data["next_action"]["stop_eligible"]
    with pytest.raises(rc.RunContractError):
        broker.operate(request, "tech", "seal")
    data = broker.operate(request, "tech", "reserve-query", query="original regulator filing")
    assert data["next_action"]["unsettled_reservations"] == ["query-1"]
    before = new_run[0].read_bytes()
    class LateClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(seconds=500)
    monkeypatch.setattr(broker, "datetime", LateClock)
    data = broker.evidence(request, "tech")
    assert data["next_action"]["action"] == "terminal_failure"
    assert data["next_action"]["stop_reason"] == "source_clock_expired"
    assert data["next_action"]["remaining_time_seconds"] == 0
    assert data["completed_at"] is None
    with pytest.raises(rc.RunContractError, match="expired"):
        broker.operate(request, "tech", "seal")
    assert calls == [] and new_run[0].read_bytes() == before


def test_stage_c_budget_stop_and_postseal_reject(new_run, monkeypatch):
    request, _ = setup(new_run, max_queries=2)
    network(monkeypatch, code=503)
    search(request)
    data = None
    for _ in range(4):
        data = broker.operate(request, "tech", "http", url=URL)
    assert data is not None
    assert data["next_action"]["stop_reason"] == "url_budget_exhausted"
    sealed = broker.operate(request, "tech", "seal")
    before = new_run[0].read_bytes()
    for operation, kwargs in [("http", {"url": URL}), ("reserve-query", {"query": "other agency"}), ("seal", {})]:
        with pytest.raises(rc.RunContractError, match="sealed"):
            broker.operate(request, "tech", operation, **kwargs)
    assert broker.evidence(request, "tech")["next_action"] == sealed["next_action"]
    assert new_run[0].read_bytes() == before


def test_stage_c_advisory_bounded_no_truncated_urls(new_run):
    from supplement_agent import _compact_broker_cli_evidence
    request, _ = setup(new_run, max_queries=2)
    urls = ["https://example.org/" + str(i) + "x" * 1800 for i in range(5)]
    data = search(request, results=[{"url": u, "title": "lead"} for u in urls])
    cli = _compact_broker_cli_evidence(request, "tech", data)
    assert len(cli["query_receipts"][0]["results"]) == 5
    assert cli["next_action"]["url_lists_omitted"]
    assert cli["next_action"]["available_discovered_urls_count"] == 5
    assert cli["next_action"]["available_discovered_urls"] == []
    assert len(json.dumps(cli["next_action"], ensure_ascii=False).encode("utf-8")) < 6000
    assert "proof_subset" not in json.dumps(cli)


def test_stage_c_query_whitespace_case_is_not_different(new_run):
    request, _ = setup(new_run, max_queries=2)
    search(request, "empty", query="Agency original filing")
    before = new_run[0].read_bytes()
    with pytest.raises(rc.RunContractError, match="duplicate"):
        broker.operate(request, "tech", "reserve-query", query=" agency   ORIGINAL filing ")
    assert new_run[0].read_bytes() == before


@pytest.fixture
def six_source_receipt():
    """Receipt validation needs no frozen bundle, subprocess, or network."""
    ledger = {"request_sha256": "a" * 64, "gap_id": "tech"}
    reservation = {
        "id": "query-1",
        "query": "release",
        "arguments": {
            "query": "release", "numResults": 5,
            "workflow": "none", "includeContent": False,
        },
    }
    receipt = {
        **ledger,
        "reservation_id": reservation["id"],
        "tool": "web_search",
        "query": reservation["query"],
        "responseId": "six-source-response",
        "outcome": "matched",
        "error": None,
        "results": [
            {"url": f"https://example.org/release-{n}", "title": f"Release {n}"}
            for n in range(6)
        ],
        "proof_subset": {"text": "actual public tool response fixture"},
        "parent_attestation": "actual_public_tool_receipt",
    }
    return receipt, ledger, reservation


@pytest.mark.parametrize("requested", [1, 5])
def test_validate_receipt_six_sources_exceed_request_hint_intact(six_source_receipt, requested):
    receipt, ledger, reservation = six_source_receipt
    reservation["arguments"]["numResults"] = requested
    before = deepcopy((receipt, ledger, reservation))
    broker.validate_receipt(receipt, ledger, reservation)
    assert (receipt, ledger, reservation) == before
    assert len(receipt["results"]) == 6


@pytest.mark.parametrize("mutation, message", [
    ({"results": {}}, "query results invalid"),
    ({"request_sha256": "foreign"}, "foreign or invalid"),
    ({"gap_id": "foreign"}, "foreign or invalid"),
    ({"reservation_id": "query-2"}, "foreign or invalid"),
    ({"query": "foreign"}, "foreign or invalid"),
    ({"tool": "foreign"}, "foreign or invalid"),
    ({"parent_attestation": "foreign"}, "foreign or invalid"),
    ({"extra": True}, "foreign or invalid"),
    ({"proof_subset": {}}, "public proof subset"),
    ({"proof_subset": {"text": "x" * 65536}}, "public proof subset"),
    ({"outcome": "error", "error": "provider failed"}, "error outcome"),
    ({"outcome": "error", "error": "", "results": []}, "error outcome"),
    ({"outcome": "empty"}, "search outcome is ambiguous"),
    ({"outcome": "unknown"}, "search outcome required"),
    ({"error": "provider failed"}, "search outcome is ambiguous"),
    ({"responseId": ""}, "search outcome is ambiguous"),
])
def test_validate_receipt_six_sources_invalid_envelope_rejected(six_source_receipt, mutation, message):
    receipt, ledger, reservation = six_source_receipt
    receipt.update(mutation)
    with pytest.raises(rc.RunContractError, match=message):
        broker.validate_receipt(receipt, ledger, reservation)


@pytest.mark.parametrize("last_result, message", [
    (None, "result subset"),
    ({"url": URL}, "result subset"),
    ({"url": URL, "title": 42}, "result subset"),
    ({"url": URL, "title": "release", "extra": True}, "result subset"),
    ({"url": "http://127.0.0.1/release", "title": "private"}, "unsafe public URL"),
    ({"url": "https://user:secret@example.org/release", "title": "credentials"}, "unsafe public URL"),
])
def test_validate_receipt_sixth_source_still_validated(six_source_receipt, last_result, message):
    receipt, ledger, reservation = six_source_receipt
    receipt["results"][-1] = last_result
    with pytest.raises(rc.RunContractError, match=message):
        broker.validate_receipt(receipt, ledger, reservation)


def test_validate_receipt_serialized_size_boundary_unchanged(six_source_receipt):
    receipt, ledger, reservation = six_source_receipt
    receipt["proof_subset"] = {"text": ""}
    receipt["proof_subset"]["text"] = "x" * (65536 - len(json.dumps(receipt)))
    assert len(json.dumps(receipt)) == 65536
    broker.validate_receipt(receipt, ledger, reservation)
    receipt["proof_subset"]["text"] += "x"
    with pytest.raises(rc.RunContractError, match="public proof subset required and bounded"):
        broker.validate_receipt(receipt, ledger, reservation)


def test_validate_receipt_valid_error_preserved(six_source_receipt):
    receipt, ledger, reservation = six_source_receipt
    receipt.update(outcome="error", error="provider failed", results=[])
    before = deepcopy(receipt)
    broker.validate_receipt(receipt, ledger, reservation)
    assert receipt == before


def test_six_source_receipt_registration_replay_discovery(new_run, six_source_receipt):
    request_path, _ = setup(new_run, max_queries=2)
    receipt, _, _ = six_source_receipt
    data = broker.operate(request_path, "tech", "reserve-query", query=receipt["query"])
    receipt["request_sha256"] = data["request_sha256"]
    before = rc.load_manifest(new_run[0])
    original = deepcopy(receipt)
    data = broker.operate(request_path, "tech", "record-query", receipt=receipt)
    manifest = rc.load_manifest(new_run[0])
    ledger = manifest["article_broker_evidence"]["tech"]
    assert receipt == original
    assert ledger["events"][-1]["receipt"] == original
    assert ledger["events"][:-1] == before["article_broker_evidence"]["tech"]["events"]
    broker.validate_append(before, manifest)
    request = rc.load_json(request_path, {})
    broker.validate_ledgers(manifest, request)
    assert data["next_action"]["available_discovered_urls"] == sorted(r["url"] for r in original["results"])
    assert data["next_action"]["remaining_queries"] == 1
    assert data["next_action"]["remaining_urls"] == 4
    assert data["query_reservations"][-1]["arguments"]["numResults"] == 5
    with pytest.raises(rc.RunContractError, match="duplicate receipt"):
        broker.operate(request_path, "tech", "record-query", receipt=receipt)
    assert rc.load_manifest(new_run[0]) == manifest
