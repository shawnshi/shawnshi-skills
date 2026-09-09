"""AB-SSRF01 / AB-PARENT01 / AB-RETRY01: real gates, frozen runs, offline I/O."""
import asyncio
import json
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import aiohttp
import article_broker as broker
import pytest
import run_contract as rc
import supplement_agent as helper
from hub_utils import atomic_dump_json
from test_article_broker_contract import new_run as frozen_run  # noqa: F401
from test_article_broker_evidence import URL, dynamic, network, search, setup
from yarl import URL as CanonicalURL


@pytest.fixture
def run(frozen_run):  # noqa: F811 - real frozen-run fixture dependency
    return frozen_run


def connection_stop(monkeypatch):
    """Intercept the actual aiohttp connection boundary, not its URL/resolver gates."""
    connections = []
    dns = []
    async def resolve(self, host, port, **kwargs):
        dns.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]
    async def stop(self, *args, **kwargs):
        connections.extend(a[4][0] for a in kwargs["addr_infos"])
        raise OSError("OFFLINE_CONNECTION_BOUNDARY")
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(aiohttp.TCPConnector, "_wrap_create_connection", stop)
    return connections, dns


@pytest.mark.parametrize("host", ["１２７.０.０.１", "127.1", "2130706433", "0177.0.0.1", "0x7f.0.0.1", "0x7f000001", "127.0.0.1."])
def test_ssrf_host(monkeypatch, host):
    connections, dns = connection_stop(monkeypatch)
    result = asyncio.run(broker._transport("http://" + host + "/", 1))
    assert result[-1] and "unsafe public URL" in result[-1]
    assert connections == dns == []
    assert CanonicalURL("http://１２７.０.０.１/").raw_host == "127.0.0.1"


@pytest.mark.parametrize("url,host,dns_expected", [
    ("http://8.8.8.8/story", "8.8.8.8", []),
    ("https://example.org/story", "8.8.8.8", ["example.org"]),
    ("https://bücher.example/story", "8.8.8.8", ["xn--bcher-kva.example"]),
])
def test_public_control(monkeypatch, url, host, dns_expected):
    connections, dns = connection_stop(monkeypatch)
    result = asyncio.run(broker._transport(url, 1))
    assert result[-1] and "OFFLINE_CONNECTION_BOUNDARY" in result[-1]
    assert connections == [host] and dns == dns_expected


@pytest.mark.parametrize("target", ["http://１２７.０.０.１/", "http://127.1/", "http://0177.0.0.1/"])
def test_ssrf_redirect(monkeypatch, target):
    connections, dns = connection_stop(monkeypatch)
    original_get = aiohttp.ClientSession.get
    public_responses = []
    class Redirect:
        url = CanonicalURL(URL)
        status = 302
        headers = {"Location": target}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    def get(session, url, **kwargs):
        if url == URL:
            public_responses.append(url)
            return Redirect()
        return original_get(session, url, **kwargs)
    monkeypatch.setattr(aiohttp.ClientSession, "get", get)
    result = asyncio.run(broker._transport(URL, 1))
    assert result[-1] and "unsafe public URL" in result[-1]
    assert public_responses == [URL] and connections == dns == []
    assert result[0] == URL and result[1] == 302


def frozen_cli(run, request, *args, late=False, daily=False, elapsed_seconds=None):
    snapshot = Path(rc.load_manifest(run[0])["skill_path"]).parent
    # Use short scratch directory names; keep the actual frozen CLI identity unchanged.
    scripts = str(snapshot / "scripts")
    bootstrap = "import sys; sys.path.insert(0, sys.argv.pop(1)); import supplement_agent as h; "
    if late or elapsed_seconds is not None:
        packet = json.loads(Path(request).read_bytes())["execution_packets"][0]
        if late:
            elapsed_seconds = packet["finalization"]["grace_seconds"] + 1
        evidence_path = Path(packet["output_paths"]["draft"])
        if not evidence_path.exists():
            evidence_path = Path(packet["output_paths"]["result"])
        completed = json.loads(evidence_path.read_bytes())["completed_at"]
        bootstrap += ("from datetime import datetime,timedelta; "
            f"clock=datetime.fromisoformat({completed!r})+timedelta(seconds={elapsed_seconds}); "
            "h.datetime=type('HandoffClock',(datetime,),{'now':classmethod(lambda cls,tz=None: clock)}); ")
    if daily:
        bootstrap += "import run_daily; run_daily.main()"
    else:
        bootstrap += "raise SystemExit(h.main())"
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", bootstrap, scripts, *args],
        cwd=snapshot, capture_output=True, text=True, encoding='utf-8')


def sealed_draft(run, monkeypatch, positive, **gap):
    request, packet = setup(run, **gap)
    search(request, "matched" if positive else "empty")
    if not positive:
        search(request, "empty", query="alternative original agency source")
    if positive:
        network(monkeypatch)
        broker.operate(request, "tech", "http", url=URL)
    sealed = broker.operate(request, "tech", "seal")
    draft = Path(packet["output_paths"]["draft"])
    atomic_dump_json(draft, dynamic(sealed, positive))
    return request, packet, sealed, draft


@pytest.mark.parametrize("positive", [False, True])
@pytest.mark.parametrize("assembled", [False, True])
@pytest.mark.parametrize("elapsed_seconds", [110, 300, 301])
def test_configured_handoff_grace_frozen_cli(run, monkeypatch, positive, assembled, elapsed_seconds):
    request, packet, sealed, draft = sealed_draft(
        run, monkeypatch, positive, max_duration_seconds=150)
    payload = json.loads(request.read_bytes())
    worker = payload["launch_plan"][0]["workers"][0]
    assert packet["finalization"]["grace_seconds"] == 300
    assert packet["execution_budget"] == {"max_queries": 3, "max_urls": 4, "max_duration_seconds": 150}
    assert worker["timeout_ms"] == 450000
    assert worker["tool_budget"] == packet["tool_budget"] == {"soft": 8, "hard": 12, "block": "*"}
    assert worker["token_budget"] == packet["usage_budget"]["tokens"] == 150000
    assert worker["cost_budget_usd"] == packet["usage_budget"]["cost_usd"]
    context = frozen_cli(run, request, "context", "--request", str(request), "--gap-id", "tech")
    assert context.returncode == 0, context.stderr
    assert json.loads(context.stdout)["execution_budget"] == packet["execution_budget"]
    if assembled:
        ready = frozen_cli(run, request, "finalize", "--parent", "--request", str(request), "--gap-id", "tech")
        assert ready.returncode == 0, ready.stderr
    before = draft.read_bytes(), run[0].read_bytes()
    finalized = frozen_cli(run, request, "finalize", "--parent", "--request", str(request),
        "--gap-id", "tech", elapsed_seconds=elapsed_seconds)
    final = Path(packet["output_paths"]["result"])
    if elapsed_seconds > 300:
        assert finalized.returncode != 0 and "grace expired" in finalized.stderr
        assert (draft.read_bytes(), run[0].read_bytes()) == before
        assert not final.exists() and not (run[1] / "supplement_results.json").exists()
        return
    assert finalized.returncode == 0, finalized.stderr
    assert json.loads(finalized.stdout)["assembly"] == ("already_assembled" if assembled else "assembled")
    if assembled:
        assert draft.read_bytes() == before[0]
    assembled_bytes = draft.read_bytes()
    publish = frozen_cli(run, request, "finalize-supplement", "--manifest", str(run[0]),
        "--request", str(request), "--draft", str(draft), daily=True, elapsed_seconds=elapsed_seconds)
    assert publish.returncode == 0, publish.stderr
    result = json.loads(final.read_bytes())
    assert final.read_bytes() == assembled_bytes
    for key in ("started_at", "completed_at", "executed_queries", "access_log", "broker_evidence_sha256"):
        assert result[key] == sealed[key]
    assert rc.load_manifest(run[0])["telemetry"]["summary"]["reserved_tokens"] == 150000


@pytest.mark.parametrize("invalid", ["changed_bytes", "source_duration", "source_reverse", "source_future"])
def test_extended_handoff_preserves_byte_and_source_time_guards(run, monkeypatch, invalid):
    from datetime import datetime, timedelta

    request, packet, sealed, draft = sealed_draft(run, monkeypatch, False, max_duration_seconds=150)
    raw = draft.read_bytes()
    data = json.loads(raw)
    completed = datetime.fromisoformat(sealed["completed_at"])
    clock = completed + timedelta(seconds=110)

    class HandoffClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock

    monkeypatch.setattr(helper, "datetime", HandoffClock)
    if invalid == "changed_bytes":
        draft.write_bytes(raw + b" ")  # Bytes changed after the parent read them.
    else:
        if invalid == "source_duration":
            data["started_at"] = (completed - timedelta(seconds=151)).isoformat()
        elif invalid == "source_reverse":
            data["started_at"] = (completed + timedelta(seconds=1)).isoformat()
        else:
            data["completed_at"] = (clock + timedelta(seconds=1)).isoformat()
        atomic_dump_json(draft, data)
        raw = draft.read_bytes()
    before = draft.read_bytes(), run[0].read_bytes()
    error = "draft changed" if invalid == "changed_bytes" else "source time is invalid"
    with pytest.raises(rc.RunContractError, match=error):
        helper._guard_parent_finalization(request, "tech", data, raw)
    assert (draft.read_bytes(), run[0].read_bytes()) == before
    assert not Path(packet["output_paths"]["result"]).exists()
    assert not (run[1] / "supplement_results.json").exists()


@pytest.mark.parametrize("positive", [False, True])
@pytest.mark.parametrize("loss", ["terminal", "expired"])
def test_parent_gate(run, monkeypatch, positive, loss):
    request, packet, sealed, draft = sealed_draft(run, monkeypatch, positive)
    original = draft.read_bytes()
    # A valid external assembler cannot grant permission to publish after later loss.
    ready = frozen_cli(run, request, "finalize", "--parent", "--request", str(request), "--gap-id", "tech")
    assert ready.returncode == 0, ready.stderr
    assembled = draft.read_bytes()
    if loss == "terminal":
        atomic_dump_json(Path(packet["progress"]["state_path"]), {"progress_id": "tech", "terminal_status": "declare_lost"})
    before_manifest = run[0].read_bytes()
    draft.write_bytes(original)
    unguarded = frozen_cli(run, request, "finalize", "--request", str(request), "--gap-id", "tech", late=loss == "expired")
    assert unguarded.returncode != 0 and "--parent guard" in unguarded.stderr
    assert draft.read_bytes() == original and run[0].read_bytes() == before_manifest
    draft.write_bytes(assembled)
    publish = frozen_cli(run, request, "finalize-supplement", "--manifest", str(run[0]), "--request", str(request), "--draft", str(draft), daily=True, late=loss == "expired")
    assert publish.returncode != 0 and ("terminal progress" if loss == "terminal" else "grace expired") in publish.stderr
    assert draft.read_bytes() == assembled and run[0].read_bytes() == before_manifest
    assert not Path(packet["output_paths"]["result"]).exists()
    assert not (run[1] / "supplement_results.json").exists()
    assert json.loads(assembled)["completed_at"] == sealed["completed_at"]


@pytest.mark.parametrize("positive", [False, True])
def test_late_read(run, monkeypatch, positive):
    request, packet, _, draft = sealed_draft(run, monkeypatch, positive)
    helper.finalize_parent_draft(request, "tech")
    _, aggregate = rc.register_supplement_results(run[0], request, [draft], publish_drafts=True)
    final = Path(packet["output_paths"]["result"])
    before = run[0].read_bytes(), final.read_bytes()
    late = frozen_cli(run, request, "register-supplement", "--manifest", str(run[0]), "--request", str(request), "--result", str(final), daily=True, late=True)
    assert late.returncode == 0, late.stderr
    assert (run[0].read_bytes(), final.read_bytes()) == before
    manifest = rc.load_manifest(run[0])
    if positive:
        candidate = aggregate["results"][0]["candidates"][0]
        assert rc.registered_candidate_lineage(manifest)[candidate["candidate_id"]]["eligible_hashes"]
    assert manifest["telemetry"]["summary"]["reserved_tokens"] == 150000


def test_parent_first_final(run, monkeypatch):
    request, packet, _, draft = sealed_draft(run, monkeypatch, False)
    helper.finalize_parent_draft(request, "tech")
    final = Path(packet["output_paths"]["result"])
    final.write_bytes(draft.read_bytes())  # adversarial unregistered externally published bytes
    before = run[0].read_bytes(), final.read_bytes()
    denied = frozen_cli(run, request, "register-supplement", "--manifest", str(run[0]), "--request", str(request), "--result", str(final), daily=True, late=True)
    assert denied.returncode != 0 and "grace expired" in denied.stderr
    assert (run[0].read_bytes(), final.read_bytes()) == before


def test_403_admission(run, monkeypatch):
    request, packet = setup(run)
    search(request)
    calls = network(monkeypatch, code=403)
    first = broker.operate(request, "tech", "http", url=URL)
    before = run[0].read_bytes()
    with pytest.raises(rc.RunContractError, match="permanent failure"):
        broker.operate(request, "tech", "http", url=URL)
    assert calls == [URL] and run[0].read_bytes() == before
    assert broker.evidence(request, "tech")["access_log"] == first["access_log"]
    with pytest.raises(rc.RunContractError, match="seal not eligible"):
        broker.operate(request, "tech", "seal")
    search(request, "empty", query="alternative regulator original filing")
    sealed = broker.operate(request, "tech", "seal")
    result = dynamic(sealed, False)
    result.update(status="degraded", failure_kind="source_access", failure_reason="403 retained; no retry")
    draft = Path(packet["output_paths"]["draft"])
    atomic_dump_json(draft, result)
    helper.finalize_parent_draft(request, "tech")
    _, aggregate = rc.register_supplement_results(run[0], request, [draft], publish_drafts=True)
    assert aggregate["coverage"] == {"attempted": 1, "succeeded": 0, "failed": 1}


def test_503_retry(run, monkeypatch):
    request, packet = setup(run)
    search(request)
    calls = network(monkeypatch, code=503)
    broker.operate(request, "tech", "http", url=URL)
    broker.operate(request, "tech", "http", url=URL)
    assert calls == [URL, URL]
    data = broker.evidence(request, "tech")
    assert [a["http_status"] for a in data["access_log"]] == [503, 503]
    assert data["remaining_urls"] == 2


def test_cross_gap_403(run, monkeypatch):
    request, payload = rc.build_supplement_request(run[0], [
        {"gap_id": gap, "lane": lane, "query_scope": "release", "article_broker": True, "max_urls": 4}
        for gap, lane in [("tech", "TechRadar"), ("health", "HealthcareRadar")]], article_broker_version=2, now=run[2])
    search(request)
    reserved = broker.operate(request, "health", "reserve-query", query="health release")
    receipt = {"request_sha256": reserved["request_sha256"], "gap_id": "health", "reservation_id": "query-1",
        "query": "health release", "tool": "web_search", "responseId": "other", "outcome": "matched", "error": None,
        "results": [{"url": URL, "title": "Original"}], "proof_subset": {"text": "Offline search response"}, "parent_attestation": "actual_public_tool_receipt"}
    broker.operate(request, "health", "record-query", receipt=receipt)
    calls = network(monkeypatch, code=403)
    broker.operate(request, "tech", "http", url=URL)
    before = run[0].read_bytes()
    with pytest.raises(rc.RunContractError, match="permanent failure"):
        broker.operate(request, "health", "http", url=URL)
    assert calls == [URL] and run[0].read_bytes() == before
    advice = broker.evidence(request, "health")["next_action"]
    assert advice["remaining_urls"] == 4
    assert advice["available_discovered_urls"] == []
    assert advice["globally_permanent_discovered_urls"] == [URL]
    assert advice["action"] == "search_different"


def test_retry_preflight_tls():
    access = {"requested_url": URL, "status": "blocked", "method": "browser", "failure_class": "permanent",
              "http_status": None, "error_code": "TLS_CERTIFICATE_ERROR"}
    history = [("2026-09-08T01:00:00+00:00", "one", 0, access)]
    lanes = {"one": "TechRadar", "two": "HealthcareRadar"}
    original = deepcopy(history)
    recovery = rc._validate_cross_lane_access_retry_policy(history, lanes, next_attempt=("two", URL, "http_get"))
    assert len(recovery) == 1 and history == original
    for gap, method in [("one", "http_get"), ("two", "browser")]:
        with pytest.raises(rc.RunContractError, match="permanent failure"):
            rc._validate_cross_lane_access_retry_policy(history, lanes, next_attempt=(gap, URL, method))
    history.append(("2026-09-08T01:00:01+00:00", "two", 0, {"requested_url": URL, "status": "verified", "method": "http_get"}))
    with pytest.raises(rc.RunContractError, match="repeats a coordinated recovery"):
        rc._validate_cross_lane_access_retry_policy(history, lanes, next_attempt=("two", URL, "http_get"))


def test_retry_host_limit():
    history = [(f"2026-09-08T01:00:0{i}+00:00", "one", i, {"requested_url": f"https://example.org/{i}", "status": "blocked", "failure_class": "permanent", "http_status": 403, "method": "http_get"}) for i in range(2)]
    with pytest.raises(rc.RunContractError, match="host limit"):
        rc._validate_cross_lane_access_retry_policy(history, {"one": "TechRadar"}, next_attempt=("one", URL, "http_get"))
    rc._validate_cross_lane_access_retry_policy(history, {"one": "TechRadar"}, next_attempt=("one", "https://other.example/release", "http_get"))
