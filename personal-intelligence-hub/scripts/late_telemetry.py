"""Append-only late telemetry/1.0; never settle or reopen an expired reservation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat

from recovery_lifecycle import load, require, sha
from session_telemetry import MAX_SESSION_BYTES, USAGE_FIELDS, summarize_sessions

VERSION = "pih-late-telemetry/1.0"


def session_metadata(path, expected_id):
    path = Path(path).resolve()
    require(path.stat().st_size <= MAX_SESSION_BYTES, "session too large")
    before = sha(path)
    ids = set()
    header = None
    assistant_stop = None
    complete = True
    assistant_count = 0
    known_budget_tokens = 0
    known_cost_usd = 0.0
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            require(isinstance(record, dict), "malformed session record")
            if record.get("type") == "session":
                require(header is None, "duplicate session header")
                header = record.get("id")
            identity = record.get("id")
            require(isinstance(identity, str) and identity not in ids, "duplicate or missing session record id")
            ids.add(identity)
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            assistant_count += 1
            assistant_stop = message.get("stopReason")
            usage = message.get("usage")
            if not isinstance(usage, dict):
                complete = False
                continue
            for key in USAGE_FIELDS:
                if key == "reasoning" and key not in usage:
                    continue  # Optional Pi counter; never contributes separately to budget.
                value = usage.get(key)
                if value is None:
                    complete = False
                else:
                    require(type(value) is int and value >= 0, "invalid actual usage counter")
            counters = [usage.get(k) for k in ("totalTokens", "cacheRead", "cacheWrite")]
            if all(value is not None for value in counters):
                budget_tokens = counters[0] - counters[1] - counters[2]
                require(budget_tokens >= 0, "inconsistent actual usage counters")
                known_budget_tokens += budget_tokens
            cost = usage.get("cost", {}).get("total") if isinstance(usage.get("cost"), dict) else None
            if cost is None:
                complete = False
            else:
                require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0, "invalid actual cost")
                known_cost_usd += cost
    require(header == expected_id, "wrong Pi session header")
    require(assistant_count > 0, "session has no actual usage messages")
    # Missing counters are unknown, not zeros fed to the strict legacy reducer.
    # Only complete per-message budget triples contribute an observed lower bound.
    summary = (summarize_sessions([path]) if complete else {
        "usage": {"budget_tokens": known_budget_tokens, "cost_usd": round(known_cost_usd, 6)},
        "counter_scope": "observed_lower_bounds_only",
    })
    require(sha(path) == before, "session changed during usage read")
    return {"session_id": header, "session_sha256": before, "assistant_stop_reason": assistant_stop,
            "usage_completeness": "reported" if complete else "unknown",
            "summary": summary}


def budget_view(manifest, records):
    """Separate conservative source total. Native broker holds never disappear."""
    telemetry = manifest.get("telemetry", {})
    executions = telemetry.get("executions", {})
    reservations = telemetry.get("reservations", {})
    tokens = sum(value["usage"]["total_tokens"] - value["usage"].get("cache_read_tokens", 0)
                 - value["usage"].get("cache_write_tokens", 0) for value in executions.values())
    cost = sum(value["usage"]["cost_usd"] for value in executions.values())
    unknown = []
    for key, reservation in reservations.items():
        status = reservation["status"]
        record = records.get(key)
        require(not (record and key in executions), "late telemetry would double count registered execution")
        if status == "expired" and key not in executions:
            if record and record["usage_completeness"] == "reported":
                tokens += record["summary"]["usage"]["budget_tokens"]
                cost += record["summary"]["usage"]["cost_usd"]
            else:
                observed = record["summary"]["usage"] if record else {}
                tokens += max(reservation["tokens"], observed.get("budget_tokens", 0))
                cost += max(reservation["cost_usd"], observed.get("cost_usd", 0))
                unknown.append(key)
        elif status in {"reserved", "held_broker_unmetered", "held_unmetered"}:
            tokens += reservation["tokens"]
            cost += reservation["cost_usd"]
            if status == "held_unmetered":
                unknown.append(key)
    return {"accounted_tokens": tokens, "accounted_cost_usd": round(cost, 6),
            "unknown_usage_reservations": unknown, "headroom_transfer_allowed": False,
            "native_broker_holds": [k for k, r in reservations.items() if r["status"] == "held_broker_unmetered"]}


def append_target(root, invocation):
    root = Path(root).resolve()
    directory = root / "late-telemetry"
    if directory.exists() or directory.is_symlink():
        info = directory.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0)
                         & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)),
                "late telemetry directory link or reparse point refused")
        require(stat.S_ISDIR(info.st_mode), "late telemetry target is not a directory")
    require(directory.resolve().parent == root, "late telemetry path escapes source run")
    output = directory / (invocation + ".json")
    require(output.resolve().parent == directory, "late telemetry output escapes source run")
    return output


def preview(manifest_path, association_path, expected_association_sha256):
    manifest_path = Path(manifest_path).resolve()
    manifest_sha = sha(manifest_path)
    manifest = load(manifest_path)
    root = manifest_path.parent
    require(root == Path(manifest["run_dir"]).resolve() and root.name == manifest["run_id"], "foreign manifest ownership")
    require(sha(association_path) == expected_association_sha256, "association declaration changed")
    association = load(association_path)
    require(association.get("source_manifest_sha256") == manifest_sha, "frozen source manifest changed")
    require(association.get("contract_version") == "pih-runtime-association/1.0"
            and association.get("authority") == "owner_supplied_parent_verified_not_runtime_signed",
            "explicit parent association declaration required")
    invocation = association["invocation_id"]
    require(re.fullmatch(r"[a-f0-9]{32}", invocation), "invalid invocation")
    key = "semantic_review:" + invocation
    reservation = manifest["telemetry"]["reservations"][key]
    stage = manifest["stages"]["semantic_review"]
    request_record = manifest["artifacts"]["semantic_review_request"]
    request_path = Path(request_record["artifact_path"]).resolve()
    require(request_path == root / "semantic_review_request.json"
            and sha(request_path) == request_record["artifact_sha256"] == association["request_sha256"],
            "original request binding mismatch")
    request = load(request_path)
    require(association["run_id"] == request["run_id"] == manifest["run_id"]
            and request["invocation_id"] == invocation
            and reservation["status"] == "expired"
            and reservation["request_sha256"] == association["request_sha256"]
            and stage["status"] == "degraded_timeout"
            and stage["metadata"]["invocation_id"] == invocation, "not the original expired semantic invocation")
    require(key not in manifest["telemetry"].get("executions", {}), "already registered execution")
    runtime_path = Path(association["runtime_status_path"]).resolve()
    require(sha(runtime_path) == association["runtime_status_sha256"], "runtime evidence changed")
    runtime = load(runtime_path)
    session_path = Path(association["session_path"]).resolve()
    require(runtime["runId"] == association["runtime_run_id"] and runtime["state"] == "failed"
            and runtime["timedOut"] is True and runtime["timeoutMs"] == request["execution_packet"]["timeout_ms"],
            "runtime outcome/identity does not match declared timeout")
    require(Path(runtime["sessionFile"]).resolve() == session_path
            and len(runtime["steps"]) == 1
            and runtime["steps"][0]["status"] == "failed"
            and runtime["steps"][0]["timedOut"] is True
            and Path(runtime["steps"][0]["sessionFile"]).resolve() == session_path, "runtime session path mismatch")
    terminal = runtime.get("processTerminal", {})
    require(terminal.get("state") == "observed" and terminal.get("runId") == runtime["runId"],
            "runtime process is not observed settled")
    clocks = [runtime.get(k) for k in ("startedAt", "deadlineAt", "endedAt")]
    require(all(type(value) is int for value in clocks)
            and clocks[0] <= clocks[1] <= clocks[0] + runtime["timeoutMs"]
            and clocks[2] >= clocks[1], "runtime deadline evidence invalid")
    require(runtime.get("error") == f"Subagent timed out after {runtime['timeoutMs']}ms.",
            "runtime error is not the declared timeout")
    metadata = session_metadata(session_path, association["session_id"])
    require(metadata["session_sha256"] == association["session_sha256"], "session bytes changed after association")
    sources = {h for r in manifest["telemetry"].get("executions", {}).values() for h in r.get("source_sha256s", [])}
    require(metadata["session_sha256"] not in sources, "session usage already counted")
    output = append_target(root, invocation)
    require(not output.exists(), "late telemetry already reconciled; no duplicate append")
    # One source runs registry; compare stable session identity as well as byte hash.
    for path in root.parent.glob("*/late-telemetry/*.json"):
        existing = load(path)
        require(existing["session_id"] != metadata["session_id"]
                and existing["session_sha256"] != metadata["session_sha256"]
                and existing["runtime_run_id"] != association["runtime_run_id"], "session/runtime reuse refused")
    result = {"contract_version": VERSION, "run_id": manifest["run_id"], "stage": "semantic_review",
              "invocation_id": invocation, "request_sha256": association["request_sha256"],
              "original_manifest_sha256": manifest_sha, "reservation_status": "expired",
              "stage_status": "degraded_timeout", "runtime_outcome": "timed_out",
              "runtime_run_id": association["runtime_run_id"], "runtime_status_sha256": association["runtime_status_sha256"],
              "association_sha256": expected_association_sha256, "association_authority": association["authority"],
              **metadata}
    result["source_budget_view"] = budget_view(manifest, {key: result})
    require(sha(manifest_path) == manifest_sha, "original manifest changed during preview")
    return output, result


def apply(manifest_path, association_path, expected_association_sha256):
    # Reuse the machine-wide process mutex; Windows creates no lock file.
    # Other platforms need a separately declared add-only guard write-set.
    require(os.name == "nt", "late telemetry apply currently requires Windows process mutex")
    from archive_transaction import _archive_process_guard
    registry = Path(manifest_path).resolve().parent.parent
    with _archive_process_guard(registry):
        return _append(manifest_path, association_path, expected_association_sha256)


def _append(manifest_path, association_path, expected_association_sha256):
    output, record = preview(manifest_path, association_path, expected_association_sha256)
    record["reconciled_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(exist_ok=True)
    require(append_target(Path(manifest_path).resolve().parent, record["invocation_id"]) == output,
            "late telemetry target changed before append")
    # Exclusive create: same invocation cannot overwrite, reopen, or double settle.
    # Interrupted/partial JSON is a blocker, never automatically overwritten.
    raw = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with output.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    require(sha(manifest_path) == record["original_manifest_sha256"], "original manifest changed during reconciliation")
    return {"status": "appended", "path": str(output), "sha256": sha(output),
            "runtime_outcome": record["runtime_outcome"], "source_budget_view": record["source_budget_view"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--association", type=Path, required=True)
    parser.add_argument("--expected-association-sha256", required=True)
    args = parser.parse_args()
    if args.operation == "apply":
        result = apply(args.manifest, args.association, args.expected_association_sha256)
    else:
        path, record = preview(args.manifest, args.association, args.expected_association_sha256)
        result = {"status": "preview", "add_only_path": str(path), "record": record}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
