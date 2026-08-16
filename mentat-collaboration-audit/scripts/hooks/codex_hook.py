"""Conservative Codex lifecycle gates for collaboration-audit controls.

The same executable handles PreToolUse, PostToolUse, PreCompact, and
SessionStart. It reads exactly one JSON object from stdin and emits exactly one
JSON object on stdout. Runtime state is deliberately redacted: identifiers and
observed results are represented only by SHA-256 digests.

Example configuration command:
    python -B scripts/hooks/codex_hook.py --mode PreToolUse

For context recovery, append ``--state-packet <path>`` (or set
``MENTAT_HOOK_STATE_PACKET``), or configure ``--state-packet-root <brain>``.
The root form resolves the current UUID session to
``<brain>/<session_id>/scratch/mentat-collaboration-audit/context-state.json``;
the packet therefore remains in session scratch rather than hook runtime state.
Tests may redirect runtime state with ``MENTAT_HOOK_STATE_DIR``.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_STATE_ROOT = Path(__file__).resolve().parent / "_runtime"
PACKET_RELATIVE_PATH = Path("scratch") / "mentat-collaboration-audit" / "context-state.json"
MAX_COVERAGE_RECEIPTS = 128
MAX_STATE_FILES = 256

MODE_NAMES = {
    "pretooluse": "PreToolUse",
    "posttooluse": "PostToolUse",
    "precompact": "PreCompact",
    "sessionstart": "SessionStart",
}

REPO_REQUIRED_GIT_COMMANDS = {
    "add",
    "am",
    "apply",
    "bisect",
    "branch",
    "checkout",
    "cherry-pick",
    "clean",
    "commit",
    "describe",
    "diff",
    "fetch",
    "format-patch",
    "fsck",
    "gc",
    "grep",
    "log",
    "merge",
    "merge-base",
    "mv",
    "notes",
    "pull",
    "push",
    "rebase",
    "reflog",
    "remote",
    "reset",
    "restore",
    "revert",
    "rev-list",
    "rev-parse",
    "rm",
    "show",
    "show-ref",
    "sparse-checkout",
    "stash",
    "status",
    "submodule",
    "switch",
    "tag",
    "worktree",
}

PATH_ORIENTED_COMMANDS = {
    "cat",
    "copy",
    "copy-item",
    "cp",
    "del",
    "dir",
    "erase",
    "findstr",
    "gc",
    "get-childitem",
    "get-content",
    "get-item",
    "grep",
    "ls",
    "move",
    "move-item",
    "mv",
    "remove-item",
    "ren",
    "rename-item",
    "rg",
    "rm",
    "test-path",
    "type",
}

GIT_PATH_COMMANDS = {
    "add",
    "apply",
    "checkout",
    "clean",
    "diff",
    "grep",
    "mv",
    "restore",
    "rm",
    "show",
}

REQUIRED_PACKET_FIELDS = {
    "objective",
    "authorization_scope",
    "completed_steps",
    "output_paths",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _identifier_hash(*parts: str) -> str:
    framed = "".join(f"{len(part)}:{part}" for part in parts)
    return hashlib.sha256(framed.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _prune_json_files(directory: Path, limit: int) -> None:
    try:
        files = sorted(
            directory.glob("*.json"),
            key=lambda candidate: candidate.stat().st_mtime_ns,
            reverse=True,
        )
        for stale in files[limit:]:
            stale.unlink(missing_ok=True)
    except OSError:
        # State retention must never turn an otherwise valid tool call into a
        # denial. A later invocation will retry bounded pruning.
        return


def _mode_name(mode: str) -> str | None:
    normalized = re.sub(r"[^a-z]", "", mode.lower())
    return MODE_NAMES.get(normalized)


def _tool_suffix(tool_name: Any) -> str:
    if not isinstance(tool_name, str):
        return ""
    normalized = tool_name.strip().lower()
    return re.split(r"[.:/\\]+", normalized)[-1]


def _tool_kind(tool_name: Any) -> str:
    suffix = _tool_suffix(tool_name)
    if suffix == "wait_agent":
        return "wait_agent"
    if suffix == "list_agents":
        return "list_agents"
    if suffix in {"bash", "exec_command"}:
        return "bash"
    if suffix == "apply_patch":
        return "apply_patch"
    return "other"


def _state_key(envelope: dict[str, Any], include_turn: bool) -> str | None:
    session_id = envelope.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    if not include_turn:
        return _identifier_hash("session", session_id)
    turn_id = envelope.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id:
        return None
    return _identifier_hash("session-turn", session_id, turn_id)


def _coverage_key(envelope: dict[str, Any], event: str, tool: str) -> str:
    session_id = envelope.get("session_id")
    turn_id = envelope.get("turn_id")
    safe_session = session_id if isinstance(session_id, str) else "<missing>"
    safe_turn = turn_id if isinstance(turn_id, str) else "<missing>"
    return _identifier_hash("coverage", safe_session, safe_turn, event, tool)


def _record_unknown(
    state_root: Path,
    envelope: dict[str, Any],
    event: str,
    tool: str,
    reason: str,
) -> None:
    """Write one bounded, redacted receipt and otherwise fail open."""

    safe_tool = tool if tool in {"wait_agent", "list_agents", "bash", "apply_patch"} else "other"
    safe_reason = reason if re.fullmatch(r"[a-z0-9_]{1,64}", reason) else "unclassified"
    directory = state_root / "coverage"
    path = directory / f"{_coverage_key(envelope, event, safe_tool)}.json"
    previous = _read_json_object(path) or {}
    previous_count = previous.get("occurrence_count")
    count = previous_count + 1 if isinstance(previous_count, int) else 1
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        "tool": safe_tool,
        "reason": safe_reason,
        "occurrence_count": min(count, 65535),
        "coverage": "unknown_fail_open",
    }
    try:
        _atomic_write_json(path, receipt)
        _prune_json_files(directory, MAX_COVERAGE_RECEIPTS)
    except OSError:
        return


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _wait_path(state_root: Path, key: str) -> Path:
    return state_root / "wait" / f"{key}.json"


def _default_wait_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": None,
        "fingerprint_kind": None,
        "identical_timeout_count": 0,
        "status_probe_used": False,
    }


def _load_wait_state(state_root: Path, key: str) -> dict[str, Any]:
    value = _read_json_object(_wait_path(state_root, key))
    if value is None:
        return _default_wait_state()
    fingerprint = value.get("fingerprint")
    kind = value.get("fingerprint_kind")
    count = value.get("identical_timeout_count")
    probe_used = value.get("status_probe_used")
    if (
        fingerprint is not None
        and (not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint))
    ):
        return _default_wait_state()
    if kind not in {None, "state_version", "response"}:
        return _default_wait_state()
    if not isinstance(count, int) or count < 0 or not isinstance(probe_used, bool):
        return _default_wait_state()
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "fingerprint_kind": kind,
        "identical_timeout_count": min(count, 2),
        "status_probe_used": probe_used,
    }


def _save_wait_state(state_root: Path, key: str, state: dict[str, Any]) -> None:
    directory = state_root / "wait"
    _atomic_write_json(_wait_path(state_root, key), state)
    _prune_json_files(directory, MAX_STATE_FILES)


def _find_state_version(value: Any) -> Any | None:
    if isinstance(value, dict):
        for name in ("state_version", "stateVersion"):
            candidate = value.get(name)
            if isinstance(candidate, (str, int, float, bool)) and str(candidate):
                return candidate
        for child in value.values():
            candidate = _find_state_version(child)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for child in value:
            candidate = _find_state_version(child)
            if candidate is not None:
                return candidate
    return None


def _is_explicit_timeout(value: Any) -> bool:
    if isinstance(value, dict):
        for name in ("status", "outcome", "stop_reason"):
            candidate = value.get(name)
            if isinstance(candidate, str) and candidate.strip().lower() in {
                "timeout",
                "timed_out",
                "timed out",
            }:
                return True
        return any(_is_explicit_timeout(child) for child in value.values())
    if isinstance(value, list):
        return any(_is_explicit_timeout(child) for child in value)
    if isinstance(value, str):
        normalized = " ".join(value.lower().split())
        return bool(
            re.search(r"\b(?:timeout|timed out)\b", normalized)
            or "no activity arrives before the deadline" in normalized
        )
    return False


def _observed_fingerprint(response: Any) -> tuple[str, str] | None:
    version = _find_state_version(response)
    if version is not None:
        return "state_version", _sha256({"state_version": version})
    if _is_explicit_timeout(response):
        # Hashing the full canonical response lets identical timeout results be
        # compared without retaining the raw response or its business payload.
        return "response", _sha256(response)
    return None


def _handle_wait_pre(
    tool: str,
    envelope: dict[str, Any],
    state_root: Path,
) -> dict[str, Any]:
    key = _state_key(envelope, include_turn=True)
    if key is None:
        _record_unknown(state_root, envelope, "PreToolUse", tool, "missing_wait_identity")
        return {}
    state = _load_wait_state(state_root, key)
    gated = state["identical_timeout_count"] >= 2
    if tool == "wait_agent" and gated:
        return _deny("Two identical timeout-state results already occurred; wait for an observed state change.")
    if tool == "list_agents" and gated:
        if state["status_probe_used"]:
            return _deny("The single status probe was already used; wait for an observed state change.")
        state["status_probe_used"] = True
        try:
            _save_wait_state(state_root, key, state)
        except OSError:
            _record_unknown(state_root, envelope, "PreToolUse", tool, "wait_state_write_failed")
        return {}
    return {}


def _handle_wait_post(
    tool: str,
    envelope: dict[str, Any],
    state_root: Path,
) -> dict[str, Any]:
    key = _state_key(envelope, include_turn=True)
    if key is None:
        _record_unknown(state_root, envelope, "PostToolUse", tool, "missing_wait_identity")
        return {}
    if "tool_response" not in envelope:
        _record_unknown(state_root, envelope, "PostToolUse", tool, "missing_tool_response")
        return {}

    response = envelope["tool_response"]
    observed = _observed_fingerprint(response)
    is_timeout = _is_explicit_timeout(response)
    if observed is None:
        _record_unknown(state_root, envelope, "PostToolUse", tool, "unclassified_tool_response")
        return {}

    kind, fingerprint = observed
    state = _load_wait_state(state_root, key)
    comparable = state["fingerprint_kind"] == kind and state["fingerprint"] is not None
    changed = comparable and state["fingerprint"] != fingerprint

    if tool == "wait_agent" and is_timeout:
        if comparable and not changed:
            state["identical_timeout_count"] = min(state["identical_timeout_count"] + 1, 2)
        else:
            state["identical_timeout_count"] = 1
            state["status_probe_used"] = False
        state["fingerprint_kind"] = kind
        state["fingerprint"] = fingerprint
    elif changed:
        # Only a comparable, observed fingerprint change resets the gate.
        state = _default_wait_state()
        state["fingerprint_kind"] = kind
        state["fingerprint"] = fingerprint
    elif not comparable:
        _record_unknown(state_root, envelope, "PostToolUse", tool, "incomparable_state_observation")
        return {}

    try:
        _save_wait_state(state_root, key, state)
    except OSError:
        _record_unknown(state_root, envelope, "PostToolUse", tool, "wait_state_write_failed")
    return {}


def _strip_token_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def _split_command(command: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(command, posix=False)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return [_strip_token_quotes(token) for token in lexer]
    except ValueError:
        return None


def _git_invocation(tokens: list[str], cwd: Path) -> tuple[str | None, Path | None, str | None]:
    """Return (subcommand, effective cwd, error-code) for a simple git call."""

    if not tokens or Path(tokens[0]).name.lower() not in {"git", "git.exe"}:
        return None, None, None
    current = cwd
    index = 1
    subcommand: str | None = None
    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if token == "-C":
            if index + 1 >= len(tokens) or not tokens[index + 1]:
                return None, None, "git_c_missing_path"
            candidate = Path(tokens[index + 1])
            current = candidate if candidate.is_absolute() else current / candidate
            index += 2
            continue
        if lowered == "-c":
            if index + 1 >= len(tokens):
                return None, None, "git_option_missing_value"
            index += 2
            continue
        if lowered.startswith("-c="):
            index += 1
            continue
        if lowered.startswith("--git-dir") or lowered.startswith("--work-tree"):
            # These forms can make a command valid outside cwd. Their combined
            # semantics are deliberately uncovered rather than falsely denied.
            return None, None, "git_alternate_layout_uncovered"
        if token.startswith("-"):
            index += 1
            continue
        subcommand = lowered
        break
    return subcommand, current, None


def _is_git_repository(directory: Path) -> bool | None:
    try:
        if not directory.is_dir():
            return False
    except OSError:
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--git-dir"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 128:
        return False
    return None


def _wildcard_result(token: str, cwd: Path) -> int | None:
    if not glob.has_magic(token):
        return None
    if any(marker in token for marker in ("$", "`", "%", "${", "$(")):
        return None
    candidate = Path(token)
    pattern = str(candidate if candidate.is_absolute() else cwd / candidate)
    try:
        matches = {str(Path(match).resolve()) for match in glob.glob(pattern)}
    except (OSError, re.error):
        return None
    return len(matches)


def _preflight_bash(
    envelope: dict[str, Any],
    state_root: Path,
) -> dict[str, Any]:
    tool_input = envelope.get("tool_input")
    tool_suffix = _tool_suffix(envelope.get("tool_name"))
    if tool_suffix == "exec_command":
        if not isinstance(tool_input, dict):
            return _deny("exec_command requires a non-empty string cmd field.")
        if "cmd" in tool_input:
            command = tool_input["cmd"]
            if "command" in tool_input and tool_input["command"] != command:
                return _deny("exec_command cmd and command fields conflict.")
        else:
            command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            return _deny("exec_command requires a non-empty string cmd field.")
    elif not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str):
        _record_unknown(state_root, envelope, "PreToolUse", "bash", "missing_bash_command")
        return {}
    else:
        command = tool_input["command"]
    tokens = _split_command(command)
    if not tokens:
        _record_unknown(state_root, envelope, "PreToolUse", "bash", "command_parse_uncovered")
        return {}
    if any(token in {"|", "||", "&&", ";"} for token in tokens):
        _record_unknown(state_root, envelope, "PreToolUse", "bash", "compound_command_uncovered")
        return {}

    cwd_value = envelope.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value:
        _record_unknown(state_root, envelope, "PreToolUse", "bash", "missing_cwd")
        return {}
    cwd = Path(cwd_value)

    subcommand, git_cwd, git_error = _git_invocation(tokens, cwd)
    if git_error:
        _record_unknown(state_root, envelope, "PreToolUse", "bash", git_error)
        return {}
    if subcommand in REPO_REQUIRED_GIT_COMMANDS and git_cwd is not None:
        repository = _is_git_repository(git_cwd)
        if repository is False:
            return _deny("This Git operation requires a repository, but cwd or explicit -C is not one.")
        if repository is None:
            _record_unknown(state_root, envelope, "PreToolUse", "bash", "git_repository_check_unknown")
            return {}

    executable = Path(tokens[0]).name.lower()
    path_oriented = executable in PATH_ORIENTED_COMMANDS
    if executable in {"git", "git.exe"} and subcommand in GIT_PATH_COMMANDS:
        path_oriented = True
    wildcard_tokens = [token for token in tokens[1:] if glob.has_magic(token)]
    if wildcard_tokens and not path_oriented:
        _record_unknown(state_root, envelope, "PreToolUse", "bash", "wildcard_command_uncovered")
        return {}
    for token in wildcard_tokens:
        match_count = _wildcard_result(token, cwd)
        if match_count == 0:
            return _deny("A literal wildcard path resolves to zero targets.")
        if match_count is not None and match_count > 1:
            return _deny("A literal wildcard path resolves ambiguously to multiple targets.")
        if match_count is None:
            _record_unknown(state_root, envelope, "PreToolUse", "bash", "wildcard_resolution_unknown")
            return {}
    return {}


def _patch_text(tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for name in ("patch", "command", "input"):
        value = tool_input.get(name)
        if isinstance(value, str):
            return value
    return None


def _preflight_apply_patch(
    envelope: dict[str, Any],
    state_root: Path,
) -> dict[str, Any]:
    patch = _patch_text(envelope.get("tool_input"))
    if patch is None:
        _record_unknown(state_root, envelope, "PreToolUse", "apply_patch", "missing_patch_text")
        return {}
    cwd_value = envelope.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value:
        _record_unknown(state_root, envelope, "PreToolUse", "apply_patch", "missing_cwd")
        return {}
    cwd = Path(cwd_value)
    directives = re.findall(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", patch, flags=re.MULTILINE)
    if not directives:
        _record_unknown(state_root, envelope, "PreToolUse", "apply_patch", "patch_directive_uncovered")
        return {}

    for operation, raw_path in directives:
        if operation == "Add":
            continue
        relative = raw_path.strip()
        if glob.has_magic(relative):
            match_count = _wildcard_result(relative, cwd)
            if match_count == 0:
                return _deny(f"The {operation.lower()} patch target does not exist.")
            if match_count is not None and match_count > 1:
                return _deny(f"The {operation.lower()} patch target is ambiguous.")
            if match_count is None:
                _record_unknown(state_root, envelope, "PreToolUse", "apply_patch", "patch_wildcard_unknown")
                return {}
            continue
        candidate = Path(relative)
        target = candidate if candidate.is_absolute() else cwd / candidate
        try:
            present_file = target.is_file()
        except OSError:
            _record_unknown(state_root, envelope, "PreToolUse", "apply_patch", "patch_target_check_unknown")
            return {}
        if not present_file:
            return _deny(f"The {operation.lower()} patch target does not exist.")
    return {}


def _validate_packet(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != REQUIRED_PACKET_FIELDS:
        return False
    objective = value.get("objective")
    authorization = value.get("authorization_scope")
    completed = value.get("completed_steps")
    outputs = value.get("output_paths")
    if not isinstance(objective, str) or not objective.strip():
        return False
    if not isinstance(authorization, (str, dict)):
        return False
    if isinstance(authorization, str) and not authorization.strip():
        return False
    if isinstance(authorization, dict) and not authorization:
        return False
    if not isinstance(completed, list) or any(
        not isinstance(item, str) or not item.strip() for item in completed
    ):
        return False
    if not isinstance(outputs, list) or any(
        not isinstance(item, str) or not item.strip() for item in outputs
    ):
        return False
    return True


def _packet_value(packet_path: Path | None) -> dict[str, Any] | None:
    if packet_path is None:
        return None
    value = _read_json_object(packet_path)
    return value if _validate_packet(value) else None


def _compaction_path(state_root: Path, key: str) -> Path:
    return state_root / "compaction" / f"{key}.json"


def _handle_precompact(
    envelope: dict[str, Any],
    state_root: Path,
    packet_path: Path | None,
) -> dict[str, Any]:
    key = _state_key(envelope, include_turn=False)
    if key is None:
        _record_unknown(state_root, envelope, "PreCompact", "other", "missing_compaction_identity")
        return {}
    receipt_path = _compaction_path(state_root, key)
    packet = _packet_value(packet_path)
    if packet is None:
        try:
            receipt_path.unlink(missing_ok=True)
        except OSError:
            pass
        _record_unknown(state_root, envelope, "PreCompact", "other", "invalid_or_missing_state_packet")
        return {}
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "state_sha256": _sha256(packet),
        "completed_step_count": len(packet["completed_steps"]),
        "output_path_count": len(packet["output_paths"]),
        "required_fields_verified": True,
    }
    try:
        _atomic_write_json(receipt_path, receipt)
        _prune_json_files(receipt_path.parent, MAX_STATE_FILES)
    except OSError:
        _record_unknown(state_root, envelope, "PreCompact", "other", "compaction_receipt_write_failed")
    return {}


def _handle_session_start(
    envelope: dict[str, Any],
    state_root: Path,
    packet_path: Path | None,
) -> dict[str, Any]:
    if str(envelope.get("source", "")).lower() != "compact":
        return {}
    key = _state_key(envelope, include_turn=False)
    if key is None:
        _record_unknown(state_root, envelope, "SessionStart", "other", "missing_compaction_identity")
        return {}
    packet = _packet_value(packet_path)
    receipt = _read_json_object(_compaction_path(state_root, key))
    if packet is None or receipt is None:
        _record_unknown(state_root, envelope, "SessionStart", "other", "missing_compaction_verification")
        return {}
    digest = _sha256(packet)
    receipt_valid = (
        receipt.get("required_fields_verified") is True
        and receipt.get("state_sha256") == digest
        and receipt.get("completed_step_count") == len(packet["completed_steps"])
        and receipt.get("output_path_count") == len(packet["output_paths"])
    )
    if not receipt_valid:
        _record_unknown(state_root, envelope, "SessionStart", "other", "changed_compaction_state")
        return {}
    recovery = {
        "context_recovery": {
            "required_fields_verified": True,
            "state_sha256": digest,
            "objective": packet["objective"],
            "authorization_scope": packet["authorization_scope"],
            "completed_steps": packet["completed_steps"],
            "output_paths": packet["output_paths"],
        }
    }
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": json.dumps(
                recovery,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    }


def handle_hook(
    mode: str,
    envelope: dict[str, Any],
    *,
    state_root: Path | None = None,
    packet_path: Path | None = None,
    packet_root: Path | None = None,
) -> dict[str, Any]:
    """Handle one official hook envelope and return a hook response object."""

    event = _mode_name(mode)
    root = (state_root or Path(os.environ.get("MENTAT_HOOK_STATE_DIR", DEFAULT_STATE_ROOT))).resolve()
    if event is None:
        _record_unknown(root, envelope, "Unknown", "other", "unknown_mode")
        return {}
    if envelope.get("hook_event_name") != event:
        _record_unknown(root, envelope, event, _tool_kind(envelope.get("tool_name")), "event_mode_mismatch")
        return {}

    tool = _tool_kind(envelope.get("tool_name"))
    if event == "PreToolUse":
        if tool in {"wait_agent", "list_agents"}:
            return _handle_wait_pre(tool, envelope, root)
        if tool == "bash":
            return _preflight_bash(envelope, root)
        if tool == "apply_patch":
            return _preflight_apply_patch(envelope, root)
        return {}
    if event == "PostToolUse":
        if tool in {"wait_agent", "list_agents"}:
            return _handle_wait_post(tool, envelope, root)
        return {}
    if event == "PreCompact":
        selected_packet = _selected_packet_path(envelope, packet_path, packet_root)
        return _handle_precompact(envelope, root, selected_packet)
    if event == "SessionStart":
        selected_packet = _selected_packet_path(envelope, packet_path, packet_root)
        return _handle_session_start(envelope, root, selected_packet)
    return {}


def _configured_packet_path(value: str | None = None) -> Path | None:
    selected = value if value is not None else os.environ.get("MENTAT_HOOK_STATE_PACKET")
    return Path(selected).resolve() if selected else None


def _configured_packet_root(value: str | None = None) -> Path | None:
    selected = value if value is not None else os.environ.get("MENTAT_HOOK_STATE_PACKET_ROOT")
    return Path(selected).resolve() if selected else None


def _session_packet_path(envelope: dict[str, Any], packet_root: Path | None) -> Path | None:
    if packet_root is None:
        return None
    session_id = envelope.get("session_id")
    if not isinstance(session_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        session_id,
    ):
        return None
    root = packet_root.resolve()
    candidate = (root / session_id / PACKET_RELATIVE_PATH).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _selected_packet_path(
    envelope: dict[str, Any],
    packet_path: Path | None,
    packet_root: Path | None,
) -> Path | None:
    return packet_path or _configured_packet_path() or _session_packet_path(
        envelope,
        packet_root or _configured_packet_root(),
    )


def _cli_options(arguments: list[str]) -> tuple[str | None, Path | None, Path | None]:
    mode: str | None = None
    packet: str | None = None
    packet_root: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--mode" and index + 1 < len(arguments):
            mode = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--mode="):
            mode = argument.split("=", 1)[1]
            index += 1
            continue
        if argument == "--state-packet" and index + 1 < len(arguments):
            packet = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--state-packet="):
            packet = argument.split("=", 1)[1]
            index += 1
            continue
        if argument == "--state-packet-root" and index + 1 < len(arguments):
            packet_root = arguments[index + 1]
            index += 2
            continue
        if argument.startswith("--state-packet-root="):
            packet_root = argument.split("=", 1)[1]
            index += 1
            continue
        index += 1
    return mode, _configured_packet_path(packet), _configured_packet_root(packet_root)


def main(arguments: list[str] | None = None) -> int:
    mode, packet_path, packet_root = _cli_options(list(sys.argv[1:] if arguments is None else arguments))
    try:
        envelope = json.loads(sys.stdin.read().lstrip("\ufeff"))
        if not isinstance(envelope, dict):
            envelope = {}
    except (UnicodeError, json.JSONDecodeError):
        envelope = {}
    try:
        response = handle_hook(mode or "", envelope, packet_path=packet_path, packet_root=packet_root)
    except Exception:
        # Hooks are advisory enforcement. Uncovered internal failures fail open,
        # and stdout remains a single schema-compatible JSON object.
        response = {}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
