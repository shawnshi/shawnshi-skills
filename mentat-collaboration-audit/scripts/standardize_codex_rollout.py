"""Convert an explicit Codex rollout snapshot into redacted audit events.

The converter never discovers session files. Callers must pass a frozen JSONL
snapshot. Raw tool inputs and outputs are inspected in memory, then discarded;
only hashes, bounded metadata, and source-line pointers reach the event stream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WRITE_TOOL_NAME = re.compile(r"(?:^|__)(?:apply_patch|create|delete|merge|publish|send|update|write)(?:_|$)", re.I)
SHELL_WRITE_COMMAND = re.compile(
    r"(?i)(?:^|[;&|]\s*)(?:Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|"
    r"New-Item|git\s+(?:commit|push)|python(?:\.exe)?\s+[^\r\n]*diary_ops\.py\s+replace-date)\b"
)
MANIFEST_WRITE = re.compile(r"(?i)generate_resource_manifests\.ps1[^\r\n]*(?:-IncludeSkills|-Root)")
PATCH_HEADER = re.compile(r"(?m)^\*\*\*\s+(?:Add|Update|Delete)\s+File:\s*(.+?)\s*$")
SKILL_PATH = re.compile(r"['\"]([^'\"\r\n]*?SKILL\.md)['\"]", re.I)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SHA256_VALUE = re.compile(r"^[0-9a-f]{64}$", re.I)
AUTHORIZATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
OUTPUT_MARKER = re.compile(r"(?m)^Output:\s*$")
DIARY_RECEIPT_SCHEMA = "diary-write-scope-v1"
SKILL_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "timestamp",
        "root_task_id",
        "actor_id",
        "actor_type",
        "event_type",
        "component",
        "operation",
        "status",
        "context_epoch",
        "skill_name",
        "skill_path_sha256",
        "skill_version",
        "skill_sha256",
        "skill_tokens",
        "tokenizer",
    }
)
CONTEXT_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "timestamp",
        "root_task_id",
        "actor_id",
        "actor_type",
        "event_type",
        "component",
        "operation",
        "status",
        "context_epoch",
        "recovery_artifact_present",
        "required_fields_verified",
        "state_sha256",
        "completed_step_count",
        "output_path_count",
    }
)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def output_segments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item.get("text", "")) for item in value if isinstance(item, dict) and "text" in item]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    return []


def flatten_output(value: Any) -> str:
    return "\n".join(output_segments(value))


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text).replace("\r\n", "\n")


def execution_payload_segments(value: Any) -> list[str]:
    """Return only the payload behind each wrapper's final Output marker."""

    payloads: list[str] = []
    for raw_segment in output_segments(value):
        segment = strip_ansi(raw_segment)
        markers = list(OUTPUT_MARKER.finditer(segment))
        payload = segment[markers[-1].end() :] if markers else segment
        lines = payload.strip().splitlines()
        while lines and re.fullmatch(
            r"(?:Script (?:completed|failed|error):?|Wall time(?::|\s).*|Exit code:\s*\d+)",
            lines[0].strip(),
            re.I,
        ):
            lines.pop(0)
        payloads.append("\n".join(lines).strip())
    return payloads


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def decode_js_string(literal: str) -> str | None:
    """Decode the double-quoted JavaScript strings emitted by Codex traces."""

    try:
        if literal.startswith('"'):
            return json.loads(literal)
    except json.JSONDecodeError:
        return None
    return None


def extract_js_value(source: str, variable: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(variable)}\s*(?::|=)\s*(\"(?:\\.|[^\"\\])*\")",
        source,
        re.S,
    )
    return decode_js_string(match.group(1)) if match else None


def extract_shell_command(source: str) -> str:
    return extract_js_value(source, "cmd") or extract_js_value(source, "command") or ""


def diary_operation(command: str) -> str | None:
    direct = re.search(r"(?i)diary_ops\.py['\"]?\s+(scope|replace-date)\b", command)
    if direct:
        return direct.group(1).replace("-", "_").lower()
    assignments = re.findall(
        r"(?im)^\s*\$([A-Za-z_][\w]*)\s*=\s*['\"][^'\"\r\n]*diary_ops\.py['\"]",
        command,
    )
    for variable in assignments:
        invocation = re.search(rf"(?i)\${re.escape(variable)}\s+(scope|replace-date)\b", command)
        if invocation:
            return invocation.group(1).replace("-", "_").lower()
    return None


def extract_apply_patch(source: str) -> str | None:
    direct = re.search(r"\btools\.apply_patch\s*\(\s*(\"(?:\\.|[^\"\\])*\")", source, re.S)
    if direct:
        return decode_js_string(direct.group(1))
    variable = re.search(r"\btools\.apply_patch\s*\(\s*([A-Za-z_$][\w$]*)\s*\)", source)
    return extract_js_value(source, variable.group(1)) if variable else None


def normalize_targets(targets: list[str]) -> list[str]:
    return sorted({target.strip().replace("\\", "/").lower() for target in targets if target.strip()})


def write_intent(tool_name: str, source: str) -> dict[str, Any] | None:
    patch = extract_apply_patch(source)
    if patch is not None:
        targets = normalize_targets(PATCH_HEADER.findall(patch))
        return {
            "operation": "apply_patch",
            "target_count": len(targets),
            "target_set_sha256": sha256_text("\n".join(targets)),
            "payload_sha256": sha256_text(patch),
        }

    command = extract_shell_command(source)
    if diary_operation(command) == "replace_date":
        return {
            "operation": "replace_date",
            "target_count": None,
            "target_set_sha256": None,
            "payload_sha256": sha256_text(command),
        }
    if command and (SHELL_WRITE_COMMAND.search(command) or MANIFEST_WRITE.search(command)):
        return {
            "operation": "exec_write",
            "target_count": None,
            "target_set_sha256": None,
            "payload_sha256": sha256_text(command),
        }

    if WRITE_TOOL_NAME.search(tool_name) and tool_name.lower() != "exec":
        return {
            "operation": "tool_write",
            "target_count": None,
            "target_set_sha256": None,
            "payload_sha256": sha256_text(source),
        }
    return None


def write_scope_sha256(component: str, intent: dict[str, Any]) -> str:
    payload = {
        "component": component,
        "operation": intent["operation"],
        "payload_sha256": intent["payload_sha256"],
        "target_set_sha256": intent.get("target_set_sha256"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def tool_outer_status(value: Any) -> str:
    return "error" if any(strip_ansi(segment).lstrip().startswith("Script failed") for segment in output_segments(value)) else "ok"


def command_families(source: str) -> list[str]:
    command = extract_shell_command(source)
    matches: list[tuple[int, str]] = []
    patterns = (
        ("python", r"(?i)\bpython(?:\.exe)?\b"),
        ("rg", r"(?i)(?<![\w.-])rg(?:\.exe)?\b"),
        ("git", r"(?i)(?<![\w.-])git\s+(?:status|diff|rev-parse|commit|push)\b"),
        ("manifest_validation", r"(?i)generate_resource_manifests\.ps1\b"),
        ("powershell", r"(?i)(?<![\w.-])(?:pwsh|powershell)(?:\.exe)?\b"),
    )
    for family, pattern in patterns:
        matches.extend((match.start(), family) for match in re.finditer(pattern, command))
    return [family for _, family in sorted(matches)]


def _classification(category: str, signature: str, executor_failure: bool) -> dict[str, Any]:
    return {
        "error_category": category,
        "error_signature": signature,
        "outcome": signature,
        "executor_failure": executor_failure,
    }


def classify_tool_output(value: Any, source: str, structured_receipt: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Classify the actual execution payload without scanning printed source text."""

    outer_error = tool_outer_status(value) == "error"
    flattened = strip_ansi(flatten_output(value))
    payloads = execution_payload_segments(value)
    body = payloads[-1] if payloads else ""
    probe = body[:16384]
    command = extract_shell_command(source)
    passive_read = bool(re.search(r"(?i)(?:^|[;&\r\n]\s*)(?:Get-Content|gc|type)\b", command))
    families = command_families(source)
    nonzero = bool(re.search(r"(?i)\b(?:Process )?Exit code:\s*[1-9]\d*", flattened))
    if structured_receipt and structured_receipt.get("receipt_type") == "write_rejected":
        return _classification("validation", "validation_guard", False)
    if not outer_error and passive_read:
        return None
    if re.search(r"TypeError:\s*tools\.(?:shell_command|exec_command)\s+is not a function", probe, re.I):
        return _classification("dependency", "tool_interface", True)
    if re.search(r"(?m)^\s*ParserError\s*:", probe, re.I):
        return _classification("syntax", "powershell_parser", True)
    if re.search(r"apply_patch verification failed", probe, re.I):
        return _classification("validation", "patch_context", True)
    if re.search(r"(?:fatal:\s*)?not a git repository", probe, re.I):
        return _classification("path", "not_git_repo", True)
    if re.search(r"(?m)^\s*rg:\s+", probe, re.I):
        return _classification("path", "search_path", True)
    guard_signal = re.search(r"VALIDATION_FAILED|Skill audit gate failed", probe, re.I)
    guard_at_payload_start = re.match(r"(?is)^\s*(?:\{|VALIDATION_FAILED|Skill audit gate failed)", probe)
    if guard_signal and (outer_error or nonzero or guard_at_payload_start):
        return _classification("validation", "validation_guard", False)
    if re.search(r"UnicodeDecodeError", probe):
        return _classification("data", "unicode_decode", True)
    if re.search(r"(?m)^Traceback \(most recent call last\):", probe):
        return _classification("unknown", "python_exception", True)
    if re.search(r"tool call error:", probe, re.I):
        return _classification("transport", "nested_tool_error", True)

    trailing_header = bool(re.search(r"(?m)^---[^\r\n]+---\s*\Z", probe))
    if families and families[-1] == "rg" and (outer_error or nonzero) and (not probe.strip() or trailing_header):
        return _classification("data", "no_match", False)
    if outer_error or nonzero:
        return _classification("unknown", "script_failed", True)
    return None


def nested_failure(text: str) -> tuple[str, str] | None:
    """Compatibility wrapper for callers that only need true nested failures."""

    classified = classify_tool_output(text, "")
    if classified and classified["executor_failure"]:
        return classified["error_category"], classified["error_signature"]
    return None


def _json_objects(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    cursor = 0
    bounded = text[-131072:]
    while True:
        start = bounded.find("{", cursor)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(bounded[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        cursor = start + max(length, 1)
        if isinstance(value, dict):
            objects.append(value)
    return objects


def _safe_hash(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) and SHA256_VALUE.fullmatch(value) else None


def _safe_authorization_id(value: Any) -> str | None:
    return value if isinstance(value, str) and AUTHORIZATION_ID.fullmatch(value) else None


def _allowlisted_diary_receipt(value: dict[str, Any], operation: str) -> dict[str, Any] | None:
    schema_valid = value.get("schema") == DIARY_RECEIPT_SCHEMA or (
        value.get("schema") is None
        and value.get("schema_version") == 2
        and value.get("component") == "diary_ops"
    )
    if not schema_valid or operation not in {"scope", "replace_date"}:
        return None
    action = str(value.get("action") or value.get("operation") or "").replace("-", "_").lower()
    if action != "replace_date":
        return None
    if value.get("task_mode") not in {None, "write"}:
        return None
    status = value.get("status")
    event_type = value.get("event_type")
    if event_type == "approval_request" and status == "ready_for_confirmation" and operation == "scope":
        receipt_type = "approval_request"
    elif event_type == "write_commit" and status == "success" and operation == "replace_date":
        receipt_type = "write_commit"
    elif status == "error" and value.get("error_code") == "VALIDATION_FAILED" and operation == "replace_date":
        receipt_type = "write_rejected"
    else:
        return None

    authorization_id = _safe_authorization_id(value.get("authorization_id"))
    authorization_scope = _safe_hash(value.get("authorization_scope_sha256"))
    write_scope = _safe_hash(value.get("write_scope_sha256"))
    payload_hash = _safe_hash(value.get("payload_sha256"))
    supplied_hashes = {
        key: value.get(key)
        for key in ("authorization_scope_sha256", "write_scope_sha256", "payload_sha256")
        if value.get(key) is not None
    }
    if any(_safe_hash(raw) is None for raw in supplied_hashes.values()):
        return None
    if not authorization_id or not authorization_scope:
        return None
    if receipt_type == "write_commit" and not write_scope:
        return None

    safe = {
        "receipt_type": receipt_type,
        "receipt_status": status,
        "operation": "replace_date",
        "action": "replace_date",
        "task_mode": "write",
        "authorization_id": authorization_id,
        "authorization_scope_sha256": authorization_scope,
    }
    if write_scope:
        safe["write_scope_sha256"] = write_scope
    if payload_hash:
        safe["payload_sha256"] = payload_hash
    target = value.get("target")
    if isinstance(target, str) and target:
        safe["target_sha256"] = sha256_text(target.strip().replace("\\", "/").lower())
    return safe


def extract_diary_receipt(value: Any, source: str) -> dict[str, Any] | None:
    operation = diary_operation(extract_shell_command(source))
    if not operation:
        return None
    for payload in reversed(execution_payload_segments(value)):
        for candidate in _json_objects(payload):
            receipt = _allowlisted_diary_receipt(candidate, operation)
            if receipt:
                return receipt
    return None


def bind_authorization(
    event: dict[str, Any],
    external: dict[str, Any] | None,
    embedded: dict[str, Any] | None,
) -> None:
    external_id = _safe_authorization_id(external.get("authorization_id")) if external else None
    external_scope = _safe_hash(external.get("authorization_scope_sha256")) if external else None
    embedded_id = _safe_authorization_id(embedded.get("authorization_id")) if embedded else None
    embedded_scope = _safe_hash(embedded.get("authorization_scope_sha256")) if embedded else None
    conflict = bool(
        external
        and embedded
        and (
            (external_id and embedded_id and external_id != embedded_id)
            or (external_scope and embedded_scope and external_scope != embedded_scope)
        )
    )
    event.pop("authorization_id", None)
    event.pop("authorization_scope_sha256", None)
    event.pop("authorization_conflict", None)
    if conflict:
        event["authorization_conflict"] = True
        if external_id:
            event["external_authorization_id"] = external_id
        if external_scope:
            event["external_authorization_scope_sha256"] = external_scope
        if embedded_id:
            event["embedded_authorization_id"] = embedded_id
        if embedded_scope:
            event["embedded_authorization_scope_sha256"] = embedded_scope
        return
    chosen_id = embedded_id or external_id
    chosen_scope = embedded_scope or external_scope
    if chosen_id:
        event["authorization_id"] = chosen_id
    if chosen_scope:
        event["authorization_scope_sha256"] = chosen_scope


def receipt_metadata(event: dict[str, Any], receipt: dict[str, Any]) -> None:
    for key in ("action", "task_mode", "payload_sha256", "target_sha256", "write_scope_sha256"):
        if receipt.get(key) is not None:
            event[key] = receipt[key]


def classified_substeps(source: str, classification: dict[str, Any] | None, status: str) -> list[dict[str, Any]]:
    families = command_families(source)
    if len(families) < 2:
        return []
    substeps = [{"index": index, "operation": family, "status": "unknown"} for index, family in enumerate(families, start=1)]
    substeps[-1]["status"] = status
    if classification:
        substeps[-1]["outcome"] = classification["outcome"]
        substeps[-1]["executor_failure"] = classification["executor_failure"]
    return substeps


def skill_paths(command: str) -> list[str]:
    if "skill.md" not in command.lower() or "get-content" not in command.lower():
        return []
    found: list[str] = []
    for match in SKILL_PATH.finditer(command):
        raw = match.group(1).replace("\\\\", "\\")
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            found.append(raw)
    return list(dict.fromkeys(found))


def skill_identity(path_text: str) -> tuple[str, str | None]:
    path = Path(path_text)
    name = path.parent.name
    digest = None
    if path.is_file():
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        match = re.search(r"(?m)^name:\s*([^\r\n]+)", raw.decode("utf-8", errors="replace"))
        if match:
            name = match.group(1).strip().strip("'\"")
    return name, digest


def day_key(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def allowlisted_receipt(
    value: Any,
    *,
    allowed_fields: frozenset[str],
    event_type: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{event_type} receipt must be a JSON object")
    if set(value) - allowed_fields:
        raise ValueError(f"{event_type} receipt contains unexpected fields")
    supplied_event_type = value.get("event_type")
    if supplied_event_type not in {None, event_type}:
        raise ValueError(f"{event_type} receipt has a conflicting event_type")
    safe = {field: value[field] for field in allowed_fields if field in value}
    safe["event_type"] = event_type
    return safe


def main() -> int:
    parser = argparse.ArgumentParser(description="Standardize one frozen Codex rollout snapshot.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end")
    parser.add_argument("--skill-receipts")
    parser.add_argument("--authorization-receipts")
    parser.add_argument("--context-receipts")
    args = parser.parse_args()

    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    summary_path = Path(args.summary).resolve()
    if output.exists() or summary_path.exists():
        raise FileExistsError("output already exists")

    authorization_receipts: dict[str, dict[str, Any]] = {}
    if args.authorization_receipts:
        for receipt in read_jsonl(Path(args.authorization_receipts).resolve()):
            call_id = receipt.get("call_id")
            if isinstance(call_id, str) and call_id:
                authorization_receipts[call_id] = receipt

    start = parse_ts(args.start)
    end = parse_ts(args.end) if args.end else None
    current_root: str | None = None
    context_epoch = 0
    calls: dict[str, dict[str, Any]] = {}
    wait_calls: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    task_durations: list[float] = []
    tool_durations: list[float] = []
    daily: defaultdict[str, Counter[str]] = defaultdict(Counter)
    wrapper_failures: Counter[str] = Counter()
    wrapper_outcomes: Counter[str] = Counter()
    source_records = window_records = unmatched_outputs = 0
    token_observations = token_input_delta = token_output_delta = 0
    previous_total_usage: dict[str, int] | None = None
    first_observed: datetime | None = None
    last_observed: datetime | None = None
    write_attempts = write_commits = nested_failures = 0
    pending_recovery: tuple[str | None, str, int] | None = None

    def in_window(ts: datetime) -> bool:
        return ts >= start and (end is None or ts <= end)

    def base_event(
        event_id: str,
        ts: datetime,
        root: str | None,
        event_type: str,
        component: str,
        operation: str,
        status: str = "ok",
    ) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "event_id": event_id,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "root_task_id": root or "unbound-root",
            "actor_id": "root",
            "actor_type": "root",
            "event_type": event_type,
            "component": component,
            "operation": operation,
            "status": status,
        }

    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source_records += 1
            record = json.loads(line)
            ts = parse_ts(record["timestamp"])
            payload = record.get("payload") or {}
            record_type = record.get("type")
            payload_type = payload.get("type") if isinstance(payload, dict) else None

            if record_type == "event_msg" and payload_type == "task_started":
                current_root = payload.get("turn_id") or current_root
            elif record_type == "turn_context":
                current_root = payload.get("turn_id") or current_root

            if record_type == "event_msg" and payload_type == "context_compacted":
                context_epoch += 1

            if record_type == "event_msg" and payload_type == "token_count":
                info = payload.get("info") or {}
                total = info.get("total_token_usage") or {}
                current_usage = {"input_tokens": total.get("input_tokens"), "output_tokens": total.get("output_tokens")}
                if in_window(ts) and all(isinstance(value, int) for value in current_usage.values()):
                    if previous_total_usage and all(current_usage[key] >= previous_total_usage[key] for key in current_usage):
                        input_delta = current_usage["input_tokens"] - previous_total_usage["input_tokens"]
                        output_delta = current_usage["output_tokens"] - previous_total_usage["output_tokens"]
                    else:
                        last = info.get("last_token_usage") or {}
                        input_delta = int(last.get("input_tokens") or 0)
                        output_delta = int(last.get("output_tokens") or 0)
                    event = base_event(f"token-{line_number}", ts, current_root, "token_usage", "runtime", "model_usage")
                    event.update({"input_tokens": input_delta, "output_tokens": output_delta, "source_line": line_number})
                    events.append(event)
                    token_observations += 1
                    token_input_delta += input_delta
                    token_output_delta += output_delta
                if all(isinstance(value, int) for value in current_usage.values()):
                    previous_total_usage = current_usage  # type: ignore[assignment]

            if not in_window(ts):
                continue
            window_records += 1
            first_observed = first_observed or ts
            last_observed = ts
            day = day_key(ts)

            recovery_artifact_present = (
                (record_type == "response_item" and payload_type == "reasoning" and bool(payload.get("summary") or payload.get("encrypted_content")))
                or (record_type == "turn_context" and bool(payload.get("summary")))
            )
            if pending_recovery and recovery_artifact_present:
                recovery_root, recovery_epoch, compact_line = pending_recovery
                recovery = base_event(
                    f"context-recovery-{line_number}",
                    ts,
                    recovery_root,
                    "context_recovered",
                    "runtime",
                    "restore_context",
                )
                recovery.update({
                    "context_epoch": recovery_epoch,
                    "required_fields_verified": False,
                    "recovery_artifact_present": True,
                    "compaction_source_line": compact_line,
                    "source_line": line_number,
                })
                events.append(recovery)
                pending_recovery = None

            if record_type == "event_msg" and payload_type in {"task_started", "task_complete"}:
                root = payload.get("turn_id") or current_root
                operation = "start" if payload_type == "task_started" else "complete"
                event = base_event(f"task-{operation}-{line_number}", ts, root, payload_type, "runtime", "turn")
                duration = payload.get("duration_ms")
                if payload_type == "task_complete" and isinstance(duration, (int, float)):
                    event["duration_ms"] = duration
                    task_durations.append(duration / 1000)
                event["source_line"] = line_number
                events.append(event)
                daily[day]["tasks_started" if payload_type == "task_started" else "tasks_completed"] += 1
                continue

            if record_type == "event_msg" and payload_type == "context_compacted":
                event = base_event(f"context-{line_number}", ts, current_root, "context_compacted", "runtime", "compact")
                event.update({"context_epoch": str(context_epoch), "source_line": line_number})
                events.append(event)
                pending_recovery = (current_root, str(context_epoch), line_number)
                daily[day]["context_compacted"] += 1
                continue

            if record_type == "response_item" and payload_type == "custom_tool_call":
                call_id = payload.get("call_id") or f"line-{line_number}"
                source_input = payload.get("input") if isinstance(payload.get("input"), str) else ""
                intent = write_intent(payload.get("name") or "tool", source_input)
                calls[call_id] = {
                    "timestamp": ts,
                    "root": current_root,
                    "name": payload.get("name") or "tool",
                    "line": line_number,
                    "input": source_input,
                    "context_epoch": str(context_epoch),
                    "write_intent": intent,
                    "attempt_event": None,
                    "commit_event": None,
                    "approval_event": None,
                }
                if intent:
                    scope_hash = write_scope_sha256(calls[call_id]["name"], intent)
                    attempt = base_event(
                        f"write-attempt-{call_id}", ts, current_root, "write_attempt", calls[call_id]["name"], intent["operation"]
                    )
                    attempt.update({
                        "call_id": call_id,
                        "write_scope_sha256": scope_hash,
                        "target_count": intent.get("target_count"),
                        "target_set_sha256": intent.get("target_set_sha256"),
                        "payload_sha256": intent["payload_sha256"],
                        "source_line": line_number,
                    })
                    bind_authorization(attempt, authorization_receipts.get(call_id), None)
                    events.append(attempt)
                    calls[call_id]["attempt_event"] = attempt
                    write_attempts += 1
                continue

            if record_type == "response_item" and payload_type == "custom_tool_call_output":
                call_id = payload.get("call_id")
                call = calls.get(call_id)
                if not call:
                    unmatched_outputs += 1
                    continue
                output_value = payload.get("output")
                outer_status = tool_outer_status(output_value)
                diary_receipt = extract_diary_receipt(output_value, call["input"])
                classification = classify_tool_output(output_value, call["input"], diary_receipt)
                executor_failure = bool(classification and classification["executor_failure"])
                status = "error" if executor_failure else "ok"
                duration_ms = max(0, (ts - call["timestamp"]).total_seconds() * 1000)
                event = base_event(
                    f"tool-{call_id}", call["timestamp"], call["root"], "tool_call", call["name"], "execute", status
                )
                event.update({
                    "call_id": call_id,
                    "duration_ms": round(duration_ms, 3),
                    "outer_status": outer_status,
                    "nested_status": "error" if executor_failure else "expected" if classification else "ok",
                    "executor_failure": executor_failure,
                    "source_line": call["line"],
                    "result_source_line": line_number,
                })
                if classification:
                    event.update(classification)
                    wrapper_outcomes[classification["error_signature"]] += 1
                    if executor_failure:
                        nested_failures += 1
                        wrapper_failures[classification["error_signature"]] += 1
                substeps = classified_substeps(call["input"], classification, status)
                if substeps:
                    event["substeps"] = substeps
                events.append(event)
                tool_durations.append(duration_ms / 1000)
                call_day = day_key(call["timestamp"])
                daily[call_day]["tool_calls"] += 1
                if executor_failure:
                    daily[call_day]["tool_failures"] += 1

                intent = call.get("write_intent")
                external_receipt = authorization_receipts.get(call_id)
                structured_write_handled = bool(
                    diary_receipt and diary_receipt["receipt_type"] in {"write_commit", "write_rejected"}
                )
                if diary_receipt and diary_receipt["receipt_type"] == "approval_request" and not call["approval_event"]:
                    approval = base_event(
                        f"approval-{call_id}",
                        ts,
                        call["root"],
                        "approval_request",
                        "diary_ops",
                        diary_receipt["operation"],
                        diary_receipt["receipt_status"],
                    )
                    approval.update({
                        "call_id": call_id,
                        "source_line": call["line"],
                        "result_source_line": line_number,
                    })
                    receipt_metadata(approval, diary_receipt)
                    bind_authorization(approval, external_receipt, diary_receipt)
                    events.append(approval)
                    call["approval_event"] = approval

                if structured_write_handled:
                    if not intent:
                        intent = {
                            "operation": "replace_date",
                            "target_count": None,
                            "target_set_sha256": None,
                            "payload_sha256": diary_receipt.get("payload_sha256") or sha256_text(call["input"]),
                        }
                        call["write_intent"] = intent
                    attempt = call.get("attempt_event")
                    if not attempt:
                        attempt = base_event(
                            f"write-attempt-{call_id}",
                            call["timestamp"],
                            call["root"],
                            "write_attempt",
                            call["name"],
                            intent["operation"],
                        )
                        attempt.update({
                            "call_id": call_id,
                            "write_scope_sha256": write_scope_sha256(call["name"], intent),
                            "target_count": intent.get("target_count"),
                            "target_set_sha256": intent.get("target_set_sha256"),
                            "payload_sha256": intent["payload_sha256"],
                            "source_line": call["line"],
                        })
                        events.append(attempt)
                        call["attempt_event"] = attempt
                        write_attempts += 1
                    receipt_metadata(attempt, diary_receipt)
                    bind_authorization(attempt, external_receipt, diary_receipt)

                    if diary_receipt["receipt_type"] == "write_commit" and not executor_failure and not call["commit_event"]:
                        commit = base_event(
                            f"write-commit-{call_id}",
                            ts,
                            call["root"],
                            "write_commit",
                            call["name"],
                            intent["operation"],
                        )
                        commit.update({
                            "call_id": call_id,
                            "write_scope_sha256": diary_receipt["write_scope_sha256"],
                            "target_count": intent.get("target_count"),
                            "target_set_sha256": intent.get("target_set_sha256"),
                            "payload_sha256": diary_receipt.get("payload_sha256") or intent["payload_sha256"],
                            "source_line": call["line"],
                            "result_source_line": line_number,
                        })
                        receipt_metadata(commit, diary_receipt)
                        bind_authorization(commit, external_receipt, diary_receipt)
                        events.append(commit)
                        call["commit_event"] = commit
                        write_commits += 1

                if intent and status == "ok" and not classification and not structured_write_handled and not call["commit_event"]:
                    scope_hash = write_scope_sha256(call["name"], intent)
                    commit = base_event(
                        f"write-commit-{call_id}", ts, call["root"], "write_commit", call["name"], intent["operation"]
                    )
                    commit.update({
                        "call_id": call_id,
                        "write_scope_sha256": scope_hash,
                        "target_count": intent.get("target_count"),
                        "target_set_sha256": intent.get("target_set_sha256"),
                        "payload_sha256": intent["payload_sha256"],
                        "source_line": call["line"],
                        "result_source_line": line_number,
                    })
                    bind_authorization(commit, external_receipt, None)
                    events.append(commit)
                    call["commit_event"] = commit
                    write_commits += 1

                for path_text in skill_paths(call["input"]):
                    skill_name, digest = skill_identity(path_text)
                    candidate = base_event(
                        f"skill-candidate-{call_id}-{sha256_text(path_text)[:8]}",
                        call["timestamp"],
                        call["root"],
                        "skill_load_candidate",
                        "skill_loader",
                        "read_candidate",
                    )
                    candidate.update({
                        "context_epoch": call["context_epoch"],
                        "skill_name": skill_name,
                        "skill_path_sha256": sha256_text(path_text.lower().replace("\\", "/")),
                        "source_line": call["line"],
                    })
                    if digest:
                        candidate["skill_sha256"] = digest
                    events.append(candidate)
                continue

            if record_type == "response_item" and payload_type == "function_call" and payload.get("name") == "wait":
                call_id = payload.get("call_id") or f"line-{line_number}"
                wait_calls[call_id] = {"timestamp": ts, "root": current_root, "line": line_number}
                continue

            if record_type == "response_item" and payload_type == "function_call_output":
                call_id = payload.get("call_id")
                call = wait_calls.get(call_id)
                if not call:
                    continue
                text = flatten_output(payload.get("output"))
                status = "timeout" if "Script running with cell ID" in text else "ok"
                duration_ms = max(0, (ts - call["timestamp"]).total_seconds() * 1000)
                event = base_event(f"wait-{call_id}", call["timestamp"], call["root"], "wait", "executor", "wait", status)
                event.update({
                    "duration_ms": round(duration_ms, 3),
                    "state_version": sha256_text(text)[:16],
                    "source_line": call["line"],
                    "result_source_line": line_number,
                })
                events.append(event)
                tool_durations.append(duration_ms / 1000)
                wait_day = day_key(call["timestamp"])
                daily[wait_day]["waits"] += 1
                if status == "timeout":
                    daily[wait_day]["wait_timeouts"] += 1

    if args.skill_receipts:
        for receipt in read_jsonl(Path(args.skill_receipts).resolve()):
            events.append(
                allowlisted_receipt(
                    receipt,
                    allowed_fields=SKILL_RECEIPT_FIELDS,
                    event_type="skill_load",
                )
            )

    if args.context_receipts:
        for receipt in read_jsonl(Path(args.context_receipts).resolve()):
            events.append(
                allowlisted_receipt(
                    receipt,
                    allowed_fields=CONTEXT_RECEIPT_FIELDS,
                    event_type="context_recovered",
                )
            )

    events.sort(key=lambda item: (item.get("timestamp", ""), item.get("event_id", "")))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "schema_version": 2,
        "source_records": source_records,
        "window_records": window_records,
        "standardized_events": len(events),
        "start": start.isoformat(),
        "end": end.isoformat() if end else None,
        "first_observed": first_observed.isoformat() if first_observed else None,
        "last_observed": last_observed.isoformat() if last_observed else None,
        "task_started": sum(row["tasks_started"] for row in daily.values()),
        "task_completed": sum(row["tasks_completed"] for row in daily.values()),
        "tool_calls": sum(row["tool_calls"] for row in daily.values()),
        "tool_failures": sum(row["tool_failures"] for row in daily.values()),
        "nested_failure_count": nested_failures,
        "wrapper_failure_signatures": dict(wrapper_failures),
        "wrapper_outcome_signatures": dict(wrapper_outcomes),
        "write_attempt_count": write_attempts,
        "write_commit_count": write_commits,
        "waits": sum(row["waits"] for row in daily.values()),
        "wait_timeouts": sum(row["wait_timeouts"] for row in daily.values()),
        "context_compacted": sum(row["context_compacted"] for row in daily.values()),
        "token_observations": token_observations,
        "token_input_delta": token_input_delta,
        "token_output_delta": token_output_delta,
        "token_total_delta": token_input_delta + token_output_delta,
        "task_duration_median_sec": round(statistics.median(task_durations), 3) if task_durations else None,
        "task_duration_p95_sec": nearest_rank(task_durations, 0.95),
        "tool_duration_p95_sec": nearest_rank(tool_durations, 0.95),
        "unmatched_tool_outputs": unmatched_outputs,
        "daily": {key: dict(value) for key, value in sorted(daily.items())},
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
