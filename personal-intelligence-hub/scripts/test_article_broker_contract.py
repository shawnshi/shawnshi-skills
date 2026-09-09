"""Offline protected broker slice: real new frozen runs, no public/network mocks."""
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import run_contract as rc
from hub_utils import atomic_dump_json
from supplement_agent import build_agent_context


@pytest.fixture
def new_run(tmp_path, request):
    now = datetime.now(timezone.utc) - timedelta(seconds=10)
    path, manifest = rc.create_run(runtime_dir=tmp_path,
        skill_path=Path(__file__).resolve().parents[1] / "SKILL.md", now=now)
    root = Path(manifest["run_dir"])
    baseline = root / "baseline.json"
    atomic_dump_json(baseline, {"items": []})
    rc.record_stage(path, "baseline", "completed", artifact_path=baseline, now=now)
    pool = root / "pool.json"
    atomic_dump_json(pool, {"items": [{"url": f"https://example.org/article-{n}",
        "title": f"Original {n}", "source_type": "primary", "provisional_domain": "technology"}
        for n in range(getattr(request, "param", 0))]})
    rc.record_run_artifact(path, "candidate_pool", pool, now=now)
    return path, root, now


def request(new_run, broker=True, **extra):
    path, _, now = new_run
    return rc.build_supplement_request(path, [{"gap_id": "tech", "lane": "TechRadar",
        "query_scope": "original release", "max_urls": 4, "article_broker": broker, **extra}], now=now)


def telemetry(new_run):
    path, root, now = new_run
    artifact = root / "worker-telemetry.json"
    atomic_dump_json(artifact, {"contract_version": "pih-execution-telemetry/1.0",
        "run_id": rc.load_manifest(path)["run_id"], "stage": "supplemental", "invocation_id": "tech",
        "status": "completed", "usage": {"input_tokens": 100, "output_tokens": 20,
            "reasoning_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
            "total_tokens": 120, "cost_usd": 0.01, "assistant_messages": 1,
            "tool_results": 0, "tool_errors": 0}, "duration_seconds": 2,
        "sources": [{"path": "worker.jsonl", "sha256": "a" * 64}]})
    return artifact


def test_worker_only_settlement_and_expiry_hold_original_reservation(new_run):
    request_path, _ = request(new_run)
    path, _, now = new_run
    before = rc.load_manifest(path)["telemetry"]["reservations"]["supplemental:tech"]
    assert before["status"] == "held_broker_unmetered"
    assert before["article_broker"]["request_sha256"] == rc.file_sha256(request_path)
    artifact = telemetry(new_run)
    rc.record_execution_telemetry(path, artifact, now=now)
    rc.expire_execution_reservation(path, "supplemental", "tech", reason="terminal", now=now)
    manifest = rc.load_manifest(path)
    held = manifest["telemetry"]["reservations"]["supplemental:tech"]
    assert held["status"] == "held_broker_unmetered"
    assert held["tokens"] == before["tokens"] and held["cost_usd"] == before["cost_usd"]
    assert held["article_broker"] == before["article_broker"]
    assert "actual_tokens" not in held
    summary = manifest["telemetry"]["summary"]
    assert summary["reserved_tokens"] == before["tokens"]
    assert summary["budget_tokens"] == 120
    assert summary["accounted_total_tokens"] == before["tokens"] + 120
    assert summary["combined_usage_status"] == "unmeasured_broker"
    assert summary["combined_tokens"] is None
    assert summary["combined_cost_usd"] is None
    assert summary["budget_status"] == "incomplete_combined_telemetry"
    assert summary["reserved_cost_usd"] == before["cost_usd"]
    rc.record_execution_telemetry(path, artifact, now=now)  # idempotent observation
    rc.expire_execution_reservation(path, "supplemental", "tech", reason="terminal", now=now)
    assert rc.load_manifest(path)["telemetry"]["summary"] == summary


def test_expiry_before_telemetry_still_allows_known_observation(new_run):
    request(new_run)
    path, _, now = new_run
    rc.expire_execution_reservation(path, "supplemental", "tech", reason="lost", now=now)
    rc.record_execution_telemetry(path, telemetry(new_run), now=now)
    state = rc._execution_budget_state(rc.load_manifest(path))
    assert state["reserved_tokens"] == 150000
    assert state["actual_tokens"] == 120


def test_normal_settlement_unchanged(new_run):
    request(new_run, False)
    path, _, now = new_run
    rc.record_execution_telemetry(path, telemetry(new_run), now=now)
    manifest = rc.load_manifest(path)
    assert manifest["telemetry"]["reservations"]["supplemental:tech"]["status"] == "settled"
    assert manifest["telemetry"]["summary"]["reserved_tokens"] == 0
    assert manifest["telemetry"]["summary"]["budget_status"] == "within_budget"
    assert "combined_usage_status" not in manifest["telemetry"]["summary"]


@pytest.mark.parametrize("mutation", ["remove", "false", "foreign_request", "foreign_gap", "amount", "settled", "remove_reservation"])
def test_marker_cannot_be_removed_or_changed_through_commit(new_run, mutation):
    request(new_run)
    path, _, _ = new_run
    original = path.read_bytes()
    with pytest.raises(rc.RunContractError, match="broker"), rc.locked_manifest(path) as (manifest, sha):
        held = manifest["telemetry"]["reservations"]["supplemental:tech"]
        if mutation == "remove":
            held.pop("article_broker")
        elif mutation == "false":
            held["article_broker"] = False
        elif mutation == "foreign_request":
            held["article_broker"]["request_sha256"] = "f" * 64
        elif mutation == "foreign_gap":
            held["article_broker"]["gap_id"] = "foreign"
        elif mutation == "amount":
            held["tokens"] = 1
        elif mutation == "settled":
            held["status"] = "settled"
        else:
            manifest["telemetry"]["reservations"].pop("supplemental:tech")
        rc.commit_manifest(path, manifest, sha)
    assert path.read_bytes() == original


def test_accounting_and_load_fail_closed_on_missing_marker(new_run):
    request(new_run)
    path, _, _ = new_run
    corrupt = rc.load_manifest(path)
    corrupt["telemetry"]["reservations"]["supplemental:tech"].pop("article_broker")
    with pytest.raises(rc.RunContractError, match="broker"):
        rc._execution_budget_state(corrupt)
    atomic_dump_json(path, corrupt)  # adversarial fixture only
    with pytest.raises(rc.RunContractError, match="broker"):
        rc.load_manifest(path)


@pytest.mark.parametrize("value", [None, 1, "true", {}])
def test_invalid_opt_in_is_not_silently_normalized(new_run, value):
    with pytest.raises(rc.RunContractError, match="article_broker"):
        request(new_run, value)
    assert not (new_run[1] / "supplement_request.json").exists()


def test_no_setter_or_old_request_upgrade(new_run):
    request_path, _ = request(new_run, False)
    original = request_path.read_bytes()
    with pytest.raises(rc.RunContractError, match="immutable"):
        request(new_run)
    assert request_path.read_bytes() == original


@pytest.mark.parametrize("new_run", [4], indirect=True)
def test_exhausted_required_attempts_reject_opt_in_before_helper(new_run):
    _, root, _ = new_run
    with pytest.raises(rc.RunContractError, match="broker.*URL"):
        request(new_run, verify_bound_candidates=True)
    assert not (root / "supplement_request.json").exists()


def test_capability_explicitly_blocks_unimplemented_public_integration(new_run):
    request_path, payload = request(new_run)
    context = build_agent_context(request_path, "tech")
    capability = context["article_broker"]
    assert capability["state"] == "blocked_pending_evidence_contract"
    assert capability["worker_tools"] == ["contact_supervisor"]
    assert capability["public_calls_allowed"] is False
    packet = payload["execution_packets"][0]
    assert "BLOCKED" in packet["task_message"]
    snapshot = Path(rc.load_manifest(new_run[0])["skill_path"]).parent
    result = subprocess.run([sys.executable, "-B", "-X", "utf8",
        str(snapshot / "scripts/supplement_agent.py"), "verify-bound", "--request",
        str(request_path), "--gap-id", "tech", "--write-draft"],
        cwd=snapshot, capture_output=True, text=True)
    assert result.returncode != 0
    assert "broker" in result.stderr.lower()
    assert not Path(packet["output_paths"]["draft"]).exists()


def test_frozen_cli_terminal_reconcile_and_expiry_preserve_hold(new_run):
    request_path, payload = request(new_run)
    path, root, now = new_run
    state_path = Path(payload["execution_packets"][0]["progress"]["state_path"])
    atomic_dump_json(state_path, {"progress_id": "tech", "terminal_status": "declare_lost"})
    snapshot = Path(rc.load_manifest(path)["skill_path"]).parent
    command = [sys.executable, "-B", "-X", "utf8", str(snapshot / "scripts/run_daily.py"),
        "reconcile-supplement", "--manifest", str(path), "--request", str(request_path),
        "--progress-state", str(state_path)]
    result = subprocess.run(command, cwd=snapshot, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    aggregate = rc.load_json(root / "supplement_results.json", {})
    assert aggregate["status"] == "degraded"
    assert aggregate["results"][0]["failure_kind"] == "infrastructure"
    rc.expire_execution_reservation(path, "supplemental", "tech", reason="terminal", now=now+timedelta(seconds=2))
    manifest = rc.load_manifest(path)
    assert manifest["telemetry"]["reservations"]["supplemental:tech"]["status"] == "held_broker_unmetered"
    assert manifest["telemetry"]["summary"]["reserved_tokens"] == 150000


def test_broker_bypass_registration_is_blocked_before_draft_acceptance(new_run):
    request_path, _ = request(new_run)
    with pytest.raises(rc.RunContractError, match="broker.*BLOCKED"):
        rc.register_supplement_results(new_run[0], request_path, [])


@pytest.mark.parametrize("mutation", ["remove_envelope", "invalid_version", "remove_capability", "foreign_packet", "request_sha"])
def test_malformed_broker_request_never_falls_back(new_run, mutation):
    request_path, payload = request(new_run)
    manifest = rc.load_manifest(new_run[0])
    if mutation == "remove_envelope":
        payload.pop("article_broker_version")
    elif mutation == "invalid_version":
        payload["article_broker_version"] = True
    elif mutation == "remove_capability":
        payload["execution_packets"][0].pop("article_broker")
    elif mutation == "foreign_packet":
        payload["execution_packets"][0]["assigned_gap_ids"] = ["foreign"]
    else:
        manifest["artifacts"]["supplement_request"]["artifact_sha256"] = "f" * 64
    if mutation != "request_sha":
        atomic_dump_json(request_path, payload)  # new adversarial fixture, never an old run
        # Rebind bytes only to exercise inner schema checks, not just hash mismatch.
        sha = rc.file_sha256(request_path)
        manifest["artifacts"]["supplement_request"]["artifact_sha256"] = sha
        held = manifest["telemetry"]["reservations"]["supplemental:tech"]
        held["request_sha256"] = sha
        held["article_broker"]["request_sha256"] = sha
    with pytest.raises(rc.RunContractError, match="broker"):
        rc._execution_budget_state(manifest)


def test_held_amount_still_blocks_new_launch_after_worker_settlement(new_run):
    request(new_run)
    path, _, now = new_run
    rc.record_execution_telemetry(path, telemetry(new_run), now=now)
    manifest = rc.load_manifest(path)
    with pytest.raises(rc.RunContractError, match="budget exceeded"):
        rc._assert_execution_budget_allows_launch(manifest, reserved_tokens=1, reserved_cost_usd=1.0)
    assert manifest["telemetry"]["summary"]["reserved_cost_usd"] == 2.0


def test_normal_gap_cannot_claim_broker_result(new_run):
    request_path, payload = request(new_run, False)
    draft = Path(payload["execution_packets"][0]["output_paths"]["draft"])
    atomic_dump_json(draft, {"article_broker": True})
    with pytest.raises(rc.RunContractError, match="broker.*BLOCKED"):
        rc.register_supplement_results(new_run[0], request_path, [draft], publish_drafts=True)


def test_commit_cannot_forget_entire_broker_registry_and_request(new_run):
    request(new_run)
    path, _, _ = new_run
    before = path.read_bytes()
    with pytest.raises(rc.RunContractError, match="broker.*immutable"), rc.locked_manifest(path) as (manifest, sha):
        manifest.pop("telemetry")
        manifest["artifacts"].pop("supplement_request")
        rc.commit_manifest(path, manifest, sha)
    assert path.read_bytes() == before
