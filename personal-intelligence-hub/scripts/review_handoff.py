"""Review handoff/1.0: exact argv, original deadline, canonical completion.

No Pi launcher or sandbox. Execute only this run's hash-bound helper; publication
ends review, while parent consumption and runtime settlement remain separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPAIR_ROOT = Path(__file__).resolve().parent


class Refusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), "JSON object required")
    return value, digest(raw)


def aware(value):
    clock = datetime.fromisoformat(value)
    require(clock.utcoffset() is not None, "timezone-aware clock required")
    return clock


def utcnow():
    return datetime.now(timezone.utc)


def same_path(left, right):
    return Path(left).resolve() == Path(right).resolve()


def bound(record):
    require(isinstance(record, dict), "missing binding")
    require(digest(Path(record["path"]).read_bytes()) == record["sha256"],
            "bound artifact changed: " + record["path"])


def registered(request_path):
    request, sha = load(request_path)
    require(request.get("contract_version") == "review-request/1.1"
            and request.get("review_kind") == "semantic"
            and request.get("reviewer_id") == "SemanticEvaluator"
            and request.get("reviewer_kind") == "semantic_model", "unsupported review request")
    packet = request["execution_packet"]
    require(packet.get("contract_version") == "review-execution-packet/1.0", "unsupported packet")
    manifest, _ = load(packet["run_manifest_path"])
    record = manifest["artifacts"]["semantic_review_request"]
    require(same_path(record["artifact_path"], request_path)
            and record["artifact_sha256"] == sha
            and manifest["run_id"] == request["run_id"], "stale/unregistered request")
    require(same_path(packet["run_manifest_path"], Path(manifest["run_dir"]) / "run_manifest.json")
            and same_path(request_path, Path(manifest["run_dir"]) / "semantic_review_request.json"),
            "noncanonical request/manifest path")
    return request, packet, manifest, sha


def deadline(request, packet):
    timeout = packet["timeout_ms"]
    require(type(timeout) is int and timeout > 0, "invalid registered timeout")
    return aware(request["created_at"]) + timedelta(milliseconds=timeout)


def live(request, packet, manifest, sha, now):
    end = deadline(request, packet)
    # Fail closed at the boundary; never reset to a full timeout at child start.
    require(aware(request["created_at"]) <= now < end, "request expired or clock precedes registration")
    stage = manifest["stages"]["semantic_review"]
    require(stage["status"] == "running", "review stage is not live")
    metadata = stage["metadata"]
    require(metadata.get("invocation_id") == request["invocation_id"]
            and metadata.get("request_sha256") == sha, "stale review stage")
    reservation = manifest["telemetry"]["reservations"].get("semantic_review:" + request["invocation_id"], {})
    require(reservation.get("status") == "reserved"
            and reservation.get("stage") == "semantic_review"
            and reservation.get("invocation_id") == request["invocation_id"]
            and reservation.get("request_sha256") == sha
            and reservation.get("tokens") == packet["usage_budget"]["tokens"]
            and reservation.get("cost_usd") == packet["usage_budget"]["cost_usd"],
            "matching live reservation required")
    return (end - now).total_seconds()


def bindings(request, packet, manifest):
    helper = packet["agent_helper"]
    root = Path(packet["skill_root"]).resolve()
    require(same_path(helper["path"], root / "scripts" / "semantic_agent.py")
            and same_path(packet["prompt_config"]["path"], root / "references" / "subagent_prompts.json")
            and same_path(manifest["skill_path"], root / "SKILL.md")
            and same_path(manifest["bundle_snapshot"]["snapshot_root"], root), "bundle paths changed")
    bound(helper)
    bound(packet["prompt_config"])
    require({"baseline", "candidate_pool", "history_snapshot", "supplement"}
            <= request["bound_artifacts"].keys(), "required bound inputs missing")
    for record in request["bound_artifacts"].values():
        bound(record)
    cli = root / "scripts" / "run_daily.py"
    require(same_path(manifest["bundle_snapshot"]["execution_cli_path"], cli), "run CLI binding changed")
    # Same raw-byte bundle algorithm as run_contract.skill_bundle_sha256.
    files = [root / n for n in ("SKILL.md", "requirements.txt", "resource-manifest.json") if (root / n).is_file()]
    for name in ("agents", "references", "scripts"):
        files.extend(p for p in (root / name).rglob("*") if p.is_file()
                     and not {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}.intersection(p.parts)
                     and p.suffix.lower() not in {".pyc", ".pyo"})
    records = [{"path": p.relative_to(root).as_posix(), "sha256": digest(p.read_bytes())}
               for p in sorted(set(files), key=lambda p: p.relative_to(root).as_posix())]
    raw = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(digest(raw) == manifest["skill_bundle_sha256"], "frozen bundle changed")
    require(cli.is_file(), "run CLI missing")
    run = Path(manifest["run_dir"])
    expected_outputs = {"refined_core": str(run / "refined_core.json"),
                        "review_receipt": str(run / "semantic_receipt.json")}
    require(packet["output_paths"] == expected_outputs, "noncanonical outputs")
    for stage in ("context", "finalize"):
        command = helper[stage + "_command"]
        expected = ["python", "-X", "utf8", helper["path"], stage, "--request",
                    str(run / "semantic_review_request.json")]
        require(type(command) is list and command == expected, "registered argv shape changed")
    require(packet["validation_command"] == helper["finalize_command"], "finalizer binding changed")


def preflight_red_team(request_path):
    from run_contract import load_manifest, validate_semantic_draft, file_sha256
    request, request_sha = load(request_path)
    require(request.get("review_kind") == "red_team" and request.get("reviewer_id") == "RedTeam"
            and request.get("deterministic_fast_path") is False, "independent red-team request required")
    packet = request["execution_packet"]
    manifest = load_manifest(packet["run_manifest_path"])
    run = Path(manifest["run_dir"]).resolve()
    record = manifest["artifacts"]["red_team_request"]
    require(same_path(request_path, run / "red_team_review_request.json")
            and same_path(record["artifact_path"], request_path)
            and record["artifact_sha256"] == request_sha
            and manifest["run_id"] == request["run_id"], "red-team registered ownership mismatch")
    bound(packet["prompt_config"])
    require(file_sha256(packet["bound_refined_path"]) == request["refined_sha256"], "red-team input changed")
    validate_semantic_draft(packet["run_manifest_path"], packet["bound_refined_path"], packet["bound_semantic_receipt_path"])
    stage = manifest["stages"]["red_team"]
    reservation = manifest["telemetry"]["reservations"]["red_team:" + request["invocation_id"]]
    require(stage["status"] == "running" and stage["metadata"]["invocation_id"] == request["invocation_id"]
            and stage["metadata"]["request_sha256"] == request_sha
            and reservation["status"] == "reserved" and reservation["request_sha256"] == request_sha
            and reservation["tokens"] == packet["usage_budget"]["tokens"]
            and reservation["cost_usd"] == packet["usage_budget"]["cost_usd"], "red-team reservation not live")
    remaining = (deadline(request, packet) - utcnow()).total_seconds()
    require(remaining > 0 and aware(request["created_at"]) <= utcnow(), "red-team deadline expired")
    return {"stage": "red_team", "status": "preflight_valid", "run_id": request["run_id"],
            "invocation_id": request["invocation_id"], "request_sha256": request_sha,
            "remaining_seconds": remaining, "registered_timeout_ms": packet["timeout_ms"],
            "usage_budget": packet["usage_budget"], "launch_performed": False}


def preflight(request_path):
    if load(request_path)[0].get("review_kind") == "red_team":
        return preflight_red_team(request_path)
    request, packet, manifest, sha = registered(request_path)
    live(request, packet, manifest, sha, utcnow())
    bindings(request, packet, manifest)
    # Binding reads consume the same registered clock. No launch approval token
    # is persisted: the caller must repeat this immediately before execution.
    remaining = live(request, packet, manifest, sha, utcnow())
    return {"stage": "semantic_review", "status": "preflight_valid",
            "run_id": request["run_id"], "invocation_id": request["invocation_id"],
            "request_sha256": sha, "deadline": deadline(request, packet).isoformat(),
            "remaining_seconds": remaining, "registered_timeout_ms": packet["timeout_ms"],
            "usage_budget": packet["usage_budget"], "tool_budget": packet["tool_budget"],
            "launch_performed": False}


def run_json(argv, timeout):
    require(type(argv) is list and all(type(v) is str for v in argv), "argv array required; shell strings forbidden")
    require(timeout > 0, "no execution time remaining")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(argv, shell=False, check=True, capture_output=True,
                            text=True, encoding="utf-8", env=env, timeout=timeout)
    value = json.loads(result.stdout)
    require(isinstance(value, dict), "helper output must be one JSON object")
    return value


def published(request_path):
    request, packet, manifest, sha = registered(request_path)
    stage = manifest["stages"]["semantic_review"]
    require(stage["status"] == "completed", "canonical semantic stage not completed")
    outputs = packet["output_paths"]
    core, core_sha = load(outputs["refined_core"])
    receipt, receipt_sha = load(outputs["review_receipt"])
    require(receipt.get("contract_version") == "review-receipt/1.0"
            and receipt.get("review_kind") == "semantic"
            and receipt.get("status") == "passed"
            and receipt.get("run_id") == request["run_id"] == core.get("run_id")
            and receipt.get("invocation_id") == request["invocation_id"]
            and receipt.get("challenge") == request["challenge"]
            and receipt.get("request_sha256") == sha
            and receipt.get("output_sha256") == core_sha, "canonical receipt binding failed")
    require(aware(request["created_at"]) <= aware(receipt["completed_at"]) <= deadline(request, packet),
            "receipt completed outside registered clock")
    require(same_path(stage["artifact_path"], outputs["review_receipt"])
            and stage["artifact_sha256"] == receipt_sha
            and stage["input_sha256"] == core_sha, "canonical stage registration mismatch")
    reservation = manifest["telemetry"]["reservations"].get("semantic_review:" + request["invocation_id"], {})
    require(reservation.get("status") in {"reserved", "settled"}
            and reservation.get("request_sha256") == sha, "closed/absent review reservation")
    return {"stage": "semantic_review", "status": "published",
            "run_id": request["run_id"], "invocation_id": request["invocation_id"],
            "request_sha256": sha,
            "artifacts": {"refined_core": {"path": outputs["refined_core"], "sha256": core_sha},
                          "review_receipt": {"path": outputs["review_receipt"], "sha256": receipt_sha}}}


def consume(request_path):
    """Parent re-reads canonical state, never child prose or next descriptors."""
    before = published(request_path)
    request, packet, manifest, _ = registered(request_path)
    bindings(request, packet, manifest)
    argv = ["python", "-X", "utf8", manifest["bundle_snapshot"]["execution_cli_path"],
            "validate-semantic-draft", "--manifest", packet["run_manifest_path"],
            "--refined", packet["output_paths"]["refined_core"],
            "--semantic-receipt", packet["output_paths"]["review_receipt"]]
    # This read-only gate is not a new review invocation or deadline extension.
    result = run_json(argv, packet["timeout_ms"] / 1000)
    require(result.get("status") == "valid", "parent semantic gate failed")
    require(published(request_path) == before, "canonical artifacts changed during gate")
    return dict(before, status="parent_gate_valid")


def execute_bound(request_path, operation):
    """Execute exact registered argv, confined to its run-scoped helper."""
    require(operation in {"context", "finalize"}, "unsupported helper operation")
    preflight(request_path)
    request, packet, manifest, sha = registered(request_path)
    paths = [request_path, packet["run_manifest_path"], packet["skill_root"],
             *packet["draft_paths"].values(), *packet["output_paths"].values(),
             *packet["write_scope"], *packet["finalizer_owned_paths"]]
    run_root = Path(manifest["run_dir"]).resolve()
    require(all(Path(p).resolve().is_relative_to(run_root) for p in paths), "helper write scope escapes run")
    require(Path(__file__).resolve().parent.parent == Path(packet["skill_root"]).resolve(),
            "execute context/finalize with the run-scoped handoff helper")
    if operation == "finalize":
        # Never rerun helper assembly over old drafts/core/receipts. Recoverable
        # published pairs use consume, not a destructive helper replay.
        require(all(not Path(p).exists() for p in packet["finalizer_owned_paths"]),
                "existing finalizer bytes preserved; use consume or controlled recovery")
        require(Path(packet["draft_paths"]["dynamic"]).is_file(), "dynamic draft absent")
    remaining = live(request, packet, manifest, sha, utcnow())
    result = run_json(packet["agent_helper"][operation + "_command"], remaining)
    if operation == "context":
        require(result.get("contract_version") == "semantic-agent-context/1.0"
                and result.get("request_sha256") == sha, "context binding failed")
        require(result.get("finalize_command") == packet["agent_helper"]["finalize_command"],
                "context must preserve exact registered argv")
        return {"stage": "semantic_review", "status": "context_ready", "context": result,
                "helper_operation": "finalize", "routine_supervisor_wait": False}
    require(result.get("status") == "decision_ready", "helper did not publish")
    # Terminal return, not a blocking artifact-ready supervisor request. Parent
    # independently calls consume and schedules expansion/red-team/forge later.
    return published(request_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preflight", "consume", "context", "finalize"))
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "preflight":
            result = preflight(args.request)
        elif args.operation == "consume":
            result = consume(args.request)
        else:
            result = execute_bound(args.request, args.operation)
        print(json.dumps(result, ensure_ascii=False))  # Control channel only.
        print("semantic_review: " + result["status"], file=sys.stderr)  # Human diagnostic.
        return 0
    except (Refusal, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"stage": "semantic_review", "status": "refused",
                          "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False))
        print("semantic_review refused: " + str(exc), file=sys.stderr)
        # Native subprocess evidence stays stderr; errors are never no_data.
        if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
            diagnostic = exc.stderr
            if isinstance(diagnostic, bytes):
                diagnostic = diagnostic.decode("utf-8", errors="backslashreplace")
            if diagnostic:
                print(diagnostic, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
