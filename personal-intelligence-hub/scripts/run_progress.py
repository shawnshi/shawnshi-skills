"""Read-only recovery projection over a frozen run; no launches or registrations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import math

import run_contract as rc

_HANDOFF_PREFLIGHTS = {"semantic_review": "review_handoff.preflight", "red_team": "review_handoff.preflight_red_team"}


def _time(value: Any, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise rc.RunContractError(f"invalid diagnostic timestamp: {field}") from exc
    if result.utcoffset() is None:
        raise rc.RunContractError(f"diagnostic timestamp requires timezone: {field}")
    return result


def _elapsed(start: datetime | None, end: datetime | None, field: str) -> float | None:
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        raise rc.RunContractError(f"diagnostic timestamp regressed: {field}")
    return round(seconds, 3)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise rc.RunContractError(f"diagnostic counter is not numeric: {field}")
    if not math.isfinite(value) or value < 0:
        raise rc.RunContractError(f"diagnostic counter is invalid: {field}")
    return float(value)


def _verify_file(path: Any, digest: Any, field: str) -> None:
    if not isinstance(path, str) or not path or not isinstance(digest, str) or not digest:
        raise rc.RunContractError(f"registered diagnostic artifact is incomplete: {field}")
    file = Path(path)
    if not file.is_file() or rc.file_sha256(file) != digest:
        raise rc.RunContractError(f"registered diagnostic artifact changed: {field}")


def _verify_registered(manifest: dict[str, Any]) -> None:
    for section in ("artifacts", "stages"):
        for name, record in manifest.get(section, {}).items():
            if "artifact_path" in record and record["artifact_path"] is not None:
                _verify_file(record["artifact_path"], record.get("artifact_sha256"), name)
    for key, record in manifest.get("telemetry", {}).get("executions", {}).items():
        _verify_file(record.get("artifact_path"), record.get("artifact_sha256"), key)
    archive = manifest["stages"]["archive"]
    if archive["status"] == "completed":
        metadata = archive.get("metadata", {})
        for kind in ("json", "markdown"):
            _verify_file(metadata.get(f"{kind}_path"), metadata.get(f"{kind}_sha256"), kind)


def timing_projection(manifest: dict[str, Any], now: datetime) -> dict[str, Any]:
    now = _time(now.isoformat(), "now")
    created = _time(manifest.get("created_at"), "created_at")
    stages = manifest["stages"]
    rows = []
    predecessor_end = None
    for stage in rc.STAGE_ORDER:
        record = stages[stage]
        metadata = record.get("metadata", {})
        terminal = record["status"] in rc.STAGE_FINAL
        observed = _time(record.get("recorded_at"), f"{stage}.recorded_at")
        if observed:
            _elapsed(observed, now, f"{stage}.recorded_clock")
        registered = observed if terminal else None
        request_key = {"semantic_review": "semantic_review_request", "red_team": "red_team_request", "supplemental": "supplement_request"}.get(stage)
        request = manifest.get("artifacts", {}).get(request_key, {})
        started = _time(request.get("recorded_at"), f"{stage}.request.recorded_at")
        commit_started = None
        if stage == "archive":
            started = _time(metadata.get("forge_started_at"), "archive.forge_started_at")
            commit_started = _time(metadata.get("commit_started_at"), "archive.commit_started_at")
        row = {"stage": stage, "status": record["status"], "started_at": started.isoformat() if started else None,
               "registered_at": registered.isoformat() if registered else None,
               "handoff_seconds": _elapsed(predecessor_end, started, f"{stage}.handoff"),
               "request_to_registration_seconds": _elapsed(started, registered, f"{stage}.registration"),
               "unobserved_transition_seconds": _elapsed(predecessor_end, registered or now, f"{stage}.unobserved") if predecessor_end and not started else None}
        row["assembly_seconds"] = _elapsed(started, commit_started, f"{stage}.assembly")
        row["commit_to_registration_seconds"] = _elapsed(commit_started, registered, f"{stage}.commit")
        if commit_started:
            _elapsed(commit_started, now, f"{stage}.commit_clock")
        for key in ("request_to_receipt_seconds", "receipt_to_registration_seconds"):
            row[key] = _number(metadata[key], f"{stage}.{key}") if key in metadata else None
        if started:
            _elapsed(started, now, f"{stage}.clock")
        if registered:
            _elapsed(registered, now, f"{stage}.clock")
        rows.append(row)
        predecessor_end = registered
    return {"run_elapsed_seconds": _elapsed(created, now, "run"), "stages": rows,
            "note": "Unobserved transitions include work and host delay; they are not measured idle time. Summed invocation durations are not wall time."}


def cost_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(manifest)
    rc._refresh_telemetry_summary(snapshot)
    telemetry = snapshot.get("telemetry", {})
    executions = telemetry.get("executions", {})
    reservations = telemetry.get("reservations", {})
    groups: dict[str, dict[str, Any]] = {}
    for key, record in executions.items():
        usage = record["usage"]
        stage = record["stage"]
        row = groups.setdefault(stage, {"registered_invocations": 0, "reported_total_tokens": 0,
                                       "budget_tokens": 0, "reported_cost_usd": 0.0,
                                       "summed_duration_seconds": 0.0, "incomplete_invocations": []})
        row["registered_invocations"] += 1
        row["budget_tokens"] += rc._usage_budget_tokens(usage)
        row["reported_total_tokens"] += usage["total_tokens"]
        row["reported_cost_usd"] += _number(usage["cost_usd"], f"{key}.cost")
        row["summed_duration_seconds"] += _number(record["duration_seconds"], f"{key}.duration")
        if usage.get("measurement_status") != "measured" or record.get("usage_scope") == "observed_worker_only_combined_unmeasured":
            row["incomplete_invocations"].append(key)
    for row in groups.values():
        row["reported_cost_usd"] = round(row["reported_cost_usd"], 6)
        row["summed_duration_seconds"] = round(row["summed_duration_seconds"], 3)
    incomplete = any(row["incomplete_invocations"] for row in groups.values()) or bool(set(reservations) - set(executions))
    return {"coverage": ("partial" if incomplete else "registered_invocations_only") if executions else "unmeasured",
            "complete_run_cost_usd": None,
            "reported_cost_usd": round(sum(row["reported_cost_usd"] for row in groups.values()), 6) if executions else None,
            "by_stage": groups, "budget_summary": telemetry.get("summary", {}),
            "missing_telemetry_keys": sorted(set(reservations) - set(executions)),
            "held_reservation_keys": sorted(key for key, value in reservations.items() if value.get("status") in {"reserved", "held_broker_unmetered", "held_unmetered"}),
            "note": "Reported usage is not complete-run cost. Parent/orchestrator and combined broker usage remain unknown unless independently registered; missing telemetry does not release reservations."}


def _archive_safety(manifest: dict[str, Any]) -> tuple[Path, str | None]:
    """Inspect bound destination metadata only; never recover or reclaim a lock."""
    from archive_transaction import _target_paths
    from forge import _bound_archive_paths

    record = manifest.get("artifacts", {}).get("history_snapshot", {})
    metadata = record.get("metadata", {})
    bound = metadata.get("news_dir")
    if not isinstance(bound, str) or not bound:
        raise rc.RunContractError("recovery archive destination binding is missing")
    news, _ = _bound_archive_paths(manifest, bound, None)
    if (news / ".pih-archive.lock").exists() or any(news.glob(".pih-stage-*")):
        return news, "archive destination has a lock or transaction residue; explicit reconciliation required"
    targets = _target_paths(news, manifest["report_date"])
    expected = metadata.get("archive_target_state")
    if not isinstance(expected, dict) or set(expected) != {p.name for p in targets.ordered()}:
        raise rc.RunContractError("recovery archive target precondition is missing")
    current = {p.name: rc.file_sha256(p) if p.is_file() else None for p in targets.ordered()}
    if current != expected:
        return news, "archive target changed since prepare; reconcile a possible partial or completed commit"
    return news, None


def _semantic_outputs(manifest: dict[str, Any], manifest_path: Path) -> tuple[Path, Path]:
    request, _ = rc._registered_review_request(manifest, "semantic")
    paths = request["execution_packet"]["output_paths"]
    refined, receipt = Path(paths["refined_core"]), Path(paths["review_receipt"])
    stage = manifest["stages"]["semantic_review"]
    if receipt.resolve() != Path(stage["artifact_path"]).resolve() or rc.file_sha256(refined) != stage["input_sha256"]:
        raise rc.RunContractError("registered semantic output binding changed")
    rc._validate_review_execution_paths(manifest, "semantic", refined, receipt, allow_draft_paths=False)
    rc.validate_semantic_draft(manifest_path, refined, receipt)
    return refined, receipt


def _next_action(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    stages = manifest["stages"]
    for stage in rc.STAGE_ORDER:
        if stages[stage]["status"] == "failed":
            return {"kind": "blocked", "stage": stage, "reason": "failed stage requires explicit reconciliation; no automatic retry"}
    if stages["archive"]["status"] == "completed":
        return {"kind": "done", "stage": "archive"}
    stage = next((key for key in rc.STAGE_ORDER if stages[key]["status"] not in rc.STAGE_TERMINAL), "archive")
    rc._validate_predecessors(manifest, stage)
    cli = manifest.get("bundle_snapshot", {}).get("execution_cli_path")
    prefix = ["python", "-B", "-X", "utf8", str(cli), "--manifest", str(manifest_path)]
    def command(name: str, *options: str) -> list[str]:
        if not isinstance(cli, str) or not Path(cli).is_file():
            raise rc.RunContractError("recovery action requires a frozen execution CLI")
        return [*prefix[:5], name, *prefix[5:], *options]
    if stage == "baseline":
        return {"kind": "blocked", "stage": stage, "reason": "baseline is not registered; do not rebuild a frozen run"}
    if stage == "supplemental":
        request = manifest.get("artifacts", {}).get("supplement_request")
        return {"kind": "host_state_required", "stage": stage,
                "request_path": request.get("artifact_path") if request else None,
                "reason": "Use exact native completion/progress evidence and the original request. Pending status does not prove unstarted work or permit a retry; preserve canary and source/grace gates."}
    if stage == "semantic_review":
        request = manifest.get("artifacts", {}).get("semantic_review_request")
        if not request:
            return {"kind": "prepare_review", "stage": stage, "argv": command("prepare-review", "--kind", "semantic")}
        rc._registered_review_request(manifest, "semantic")
        return {"kind": "handoff_existing_review", "stage": stage, "request_path": request["artifact_path"],
                "helper": _HANDOFF_PREFLIGHTS["semantic_review"], "requires_host_state": True}
    archive_dir = None
    if stage == "archive":
        archive_dir, reason = _archive_safety(manifest)
        if reason:
            return {"kind": "blocked", "stage": "archive", "reason": reason}
    if stages["semantic_review"]["status"] != "completed":
        raise rc.RunContractError("recovery requires completed semantic review")
    refined, semantic = _semantic_outputs(manifest, manifest_path)
    if stage == "red_team":
        request = manifest.get("artifacts", {}).get("red_team_request")
        if not request:
            return {"kind": "prepare_review", "stage": stage, "argv": command("prepare-review", "--kind", "red_team", "--refined", str(refined), "--semantic-receipt", str(semantic))}
        rc._registered_review_request(manifest, "red_team")
        return {"kind": "handoff_existing_review", "stage": stage, "request_path": request["artifact_path"],
                "helper": _HANDOFF_PREFLIGHTS["red_team"], "requires_host_state": True}
    from forge import assemble_final_payload
    assemble_final_payload(manifest_path, refined)
    return {"kind": "forge", "stage": "archive", "argv": command("forge", "--refined", str(refined), "--news-dir", str(archive_dir), "--no-runtime-state"),
            "requires_archive_authorization": True}


def inspect_run(manifest_path: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate registered bytes and project diagnostics without changing clocks or files."""
    path = Path(manifest_path).resolve()
    manifest = rc.load_manifest(path)
    _verify_registered(manifest)
    current = now if now is not None else datetime.now(timezone.utc)
    return {"contract_version": "run-resume/1.0", "mode": "read_only", "run_id": manifest["run_id"],
            "observed_at": current.isoformat(), "next_action": _next_action(manifest, path),
            "timing": timing_projection(manifest, current), "cost": cost_projection(manifest),
            "guard": "Suggestions still require existing command gates, native host state and scoped authorization; this observer neither launches nor mutates."}
