"""LIVE-ACCESS-01: real frozen helper/parent CLI chain; only HTTP transport is stubbed."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import run_contract as rc


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf8")


def cli(snapshot, script, *args):
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(snapshot / "scripts" / script), *map(str, args)],
        cwd=snapshot, capture_output=True, text=True, encoding="utf8", timeout=30,
    )


@pytest.mark.parametrize("mode", ["register", "reconcile", "tampered_access"])
def test_verify_bound_exact_access_survives_parent_registration(tmp_path, mode):
    now = datetime.now(timezone.utc)
    started = now - timedelta(seconds=120)
    manifest_path, manifest = rc.create_run(
        runtime_dir=tmp_path, skill_path=Path(__file__).resolve().parents[1] / "SKILL.md", now=started,
    )
    root = Path(manifest["run_dir"])
    snapshot = Path(manifest["skill_path"]).parent
    baseline = root / "baseline.json"
    dump(baseline, {"items": []})
    rc.record_stage(manifest_path, "baseline", "completed", artifact_path=baseline, now=started)
    pool_path = root / "candidate_pool.json"
    items = [{
        "url": f"https://example.org/release-{index}", "title": f"Registered release {index}",
        "source": "Example", "source_type": "primary", "published_at": now.date().isoformat(),
        "published_at_source": "rss_published", "provisional_domain": "technology",
        "summary_hint": "Complete registered source metadata for an accessed publication.",
    } for index in range(3)]
    dump(pool_path, {"items": items})
    rc.record_run_artifact(manifest_path, "candidate_pool", pool_path, now=started)
    gaps = [{"gap_id": "technology", "lane": "TechRadar", "query_scope": "release",
             "verify_bound_candidates": True, "max_urls": 4}]
    if mode == "reconcile":
        gaps += [{"gap_id": gap, "lane": lane, "query_scope": "original sources",
                  "article_broker": True} for gap, lane in [
                      ("healthcare", "HealthcareRadar"), ("policy", "Sentinel"), ("risk", "Ranger")]]
    request_path, request = rc.build_supplement_request(manifest_path, gaps, now=started)
    packet = next(p for p in request["execution_packets"] if p["assigned_gap_ids"] == ["technology"])
    draft = Path(packet["output_paths"]["draft"])
    final = Path(packet["output_paths"]["result"])
    # Exercise the real verify-bound --write-draft entrypoint in the fresh frozen bundle.
    # Stub only urlopen; the real bounded fetch, parser and CLI must deliver initial body evidence.
    transport_only = (
        "import sys, io; sys.path.insert(0, 'scripts'); import supplement_agent as s\n"
        "def urlopen(request, timeout):\n"
        "    response = io.BytesIO(b'<article>' + b'Initial publication body evidence. ' * 20 + b'</article>')\n"
        "    response.status = 200\n"
        "    response.headers = {'Content-Type': 'text/html; charset=utf-8'}\n"
        "    response.geturl = lambda: request.full_url\n"
        "    return response\n"
        "s.urllib.request.urlopen = urlopen\n"
        "sys.exit(s.main())"
    )
    verified = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", transport_only, "verify-bound",
         "--request", str(request_path), "--gap-id", "technology", "--write-draft"],
        cwd=snapshot, capture_output=True, text=True, encoding="utf8", timeout=30,
    )
    assert verified.returncode == 0, verified.stderr
    helper_output = json.loads(verified.stdout)
    dynamic = json.loads(draft.read_text(encoding="utf8"))
    assert "body_evidence" not in dynamic
    assert helper_output["access_log_count"] == 3
    assert len(helper_output["body_evidence"]) == 3
    for index, body in enumerate(helper_output["body_evidence"]):
        assert "Initial publication body evidence." in body["text"]
        assert body["access_log_index"] == index
        assert body["access_check"] == dynamic["access_log"][index]
        assert body["text_sha256"] == hashlib.sha256(body["text"].encode()).hexdigest()
    assert len(dynamic["candidates"]) == 3
    assert all(c["published_at"] == now.date().isoformat() for c in dynamic["candidates"])
    ordinary = cli(snapshot, "supplement_agent.py", "finalize", "--request", request_path,
                   "--gap-id", "technology")
    assert ordinary.returncode == 0, ordinary.stderr
    assembled_bytes = draft.read_bytes()
    parent = cli(snapshot, "supplement_agent.py", "finalize", "--request", request_path,
                 "--gap-id", "technology", "--parent")
    assert parent.returncode == 0, parent.stderr
    assert draft.read_bytes() == assembled_bytes
    assembled = json.loads(assembled_bytes)
    assert all(rc.candidate_date_owned(c) for c in assembled["candidates"])
    if mode == "tampered_access":
        assembled["candidates"][0]["access_check"]["http_status"] = 201
        candidate = assembled["candidates"][0]
        candidate["candidate_object_sha256"] = rc.candidate_object_hash(candidate)
        dump(draft, assembled)
    args = ["--manifest", manifest_path, "--request", request_path]
    if mode == "reconcile":
        for other in request["execution_packets"]:
            if other is packet:
                continue
            state = Path(other["progress"]["state_path"])
            dump(state, {"progress_id": other["assigned_gap_ids"][0], "terminal_status": "declare_lost"})
            args += ["--progress-state", state]
        command = "reconcile-supplement"
        args += ["--result", draft]
    else:
        command = "finalize-supplement"
        args += ["--draft", draft]
    manifest_before = manifest_path.read_bytes()
    draft_before = draft.read_bytes()
    registered = cli(snapshot, "run_daily.py", command, *args)
    if mode == "tampered_access":
        assert registered.returncode != 0
        assert "access" in registered.stderr
        assert manifest_path.read_bytes() == manifest_before
        assert draft.read_bytes() == draft_before
        assert not final.exists()
        assert not (root / "supplement_results.json").exists()
        return
    # Pre-fix this assertion fails at build_candidate_date_evidence's exact ownership gate.
    assert registered.returncode == 0, registered.stderr
    assert final.read_bytes() == assembled_bytes
    aggregate = json.loads((root / "supplement_results.json").read_text(encoding="utf8"))
    result = next(r for r in aggregate["results"] if r["gap_id"] == "technology")
    assert result == assembled
    assert aggregate["coverage"] == {"attempted": 3, "succeeded": 3, "failed": 0}
    assert aggregate["status"] == ("degraded" if mode == "reconcile" else "completed")
    if mode == "reconcile":
        failures = [r for r in aggregate["results"] if r["gap_id"] != "technology"]
        assert len(failures) == 3
        assert all(r["failure_kind"] == "infrastructure" and not r["candidates"] for r in failures)
    assert result["data_provenance"]["access_log_sha256"] == hashlib.sha256(
        rc.canonical_json_bytes(dynamic["access_log"])).hexdigest()
    pool = rc.load_json(pool_path, {})
    assert aggregate["candidate_date_evidence"] == rc.build_candidate_date_evidence(
        request, rc.file_sha256(request_path), pool, aggregate["results"])
    ownership = rc.candidate_date_ownership(rc.load_manifest(manifest_path), pool, aggregate)
    for candidate, access in zip(result["candidates"], result["access_log"], strict=True):
        assert candidate["access_check"] == access
        assert "error_code" not in access
        assert candidate["candidate_object_sha256"] == rc.candidate_object_hash(candidate)
        assert rc.candidate_date_owned(candidate, ownership)
        assert candidate["published_at_source"] == "rss_published"
