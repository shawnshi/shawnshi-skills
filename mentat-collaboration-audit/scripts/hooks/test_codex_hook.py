from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK_DIR = Path(__file__).resolve().parent
HOOK_PATH = HOOK_DIR / "codex_hook.py"
SPEC = importlib.util.spec_from_file_location("mentat_codex_hook", HOOK_PATH)
assert SPEC is not None and SPEC.loader is not None
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


class HookTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mentat-hook-test-")
        self.root = Path(self.temporary.name)
        self.state_root = self.root / "state"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.session_id = "session-sensitive-123"
        self.turn_id = "turn-sensitive-456"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def envelope(self, event: str, **values: object) -> dict[str, object]:
        envelope: dict[str, object] = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "cwd": str(self.workspace),
            "hook_event_name": event,
        }
        envelope.update(values)
        return envelope

    def handle(
        self,
        mode: str,
        envelope: dict[str, object],
        packet: Path | None = None,
        packet_root: Path | None = None,
    ) -> dict[str, object]:
        return hook.handle_hook(
            mode,
            envelope,
            state_root=self.state_root,
            packet_path=packet,
            packet_root=packet_root,
        )

    def assert_denied(self, response: dict[str, object]) -> None:
        specific = response.get("hookSpecificOutput")
        self.assertIsInstance(specific, dict)
        self.assertEqual("PreToolUse", specific.get("hookEventName"))
        self.assertEqual("deny", specific.get("permissionDecision"))
        self.assertIsInstance(specific.get("permissionDecisionReason"), str)

    def write_packet(self, **changes: object) -> Path:
        packet: dict[str, object] = {
            "objective": "Sensitive business objective",
            "authorization_scope": {"write": "owned subtree only"},
            "completed_steps": ["Inspected evidence"],
            "output_paths": ["C:/scratch/result.json"],
        }
        packet.update(changes)
        path = self.root / "state-packet.json"
        path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
        return path


class EntrypointTests(HookTestCase):
    def test_one_json_in_and_one_schema_valid_json_out(self) -> None:
        envelope = self.envelope(
            "PreToolUse",
            tool_name="Bash",
            tool_use_id="tool-1",
            tool_input={"command": "echo hello"},
        )
        environment = os.environ.copy()
        environment["MENTAT_HOOK_STATE_DIR"] = str(self.state_root)
        completed = subprocess.run(
            [sys.executable, "-B", str(HOOK_PATH), "--mode", "PreToolUse"],
            input=json.dumps(envelope),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        self.assertEqual({}, json.loads(completed.stdout))
        self.assertEqual(1, len(completed.stdout.strip().splitlines()))

    def test_windows_utf8_bom_input_is_accepted(self) -> None:
        envelope = self.envelope(
            "PreToolUse",
            tool_name="Bash",
            tool_use_id="tool-bom",
            tool_input={"command": "Get-Content definitely-missing-bom-probe*.txt"},
        )
        environment = os.environ.copy()
        environment["MENTAT_HOOK_STATE_DIR"] = str(self.state_root)
        completed = subprocess.run(
            [sys.executable, "-B", str(HOOK_PATH), "--mode", "PreToolUse"],
            input="\ufeff" + json.dumps(envelope),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, completed.returncode)
        response = json.loads(completed.stdout)
        self.assertEqual("deny", response["hookSpecificOutput"]["permissionDecision"])


class WaitGateTests(HookTestCase):
    def post_wait(self, version: str, status: str = "timeout") -> dict[str, object]:
        return self.handle(
            "PostToolUse",
            self.envelope(
                "PostToolUse",
                tool_name="wait_agent",
                tool_use_id="wait-tool",
                tool_input={"timeout_ms": 30000, "secret": "must-not-persist"},
                tool_response={
                    "status": status,
                    "state_version": version,
                    "raw": "private raw response must-not-persist",
                },
            ),
        )

    def pre(self, tool_name: str) -> dict[str, object]:
        return self.handle(
            "PreToolUse",
            self.envelope(
                "PreToolUse",
                tool_name=tool_name,
                tool_use_id="pre-tool",
                tool_input={"timeout_ms": 30000},
            ),
        )

    def test_two_identical_timeouts_gate_wait_and_allow_one_probe(self) -> None:
        self.assertEqual({}, self.post_wait("v1"))
        self.assertEqual({}, self.post_wait("v1"))
        self.assert_denied(self.pre("wait_agent"))
        self.assertEqual({}, self.pre("list_agents"))
        self.assert_denied(self.pre("list_agents"))
        self.assert_denied(self.pre("wait_agent"))

    def test_observed_state_change_resets_gate(self) -> None:
        self.post_wait("v1")
        self.post_wait("v1")
        self.pre("list_agents")
        response = self.handle(
            "PostToolUse",
            self.envelope(
                "PostToolUse",
                tool_name="list_agents",
                tool_use_id="probe-tool",
                tool_input={},
                tool_response={"status": "ok", "state_version": "v2"},
            ),
        )
        self.assertEqual({}, response)
        self.assertEqual({}, self.pre("wait_agent"))

    def test_same_probe_state_does_not_reset_gate(self) -> None:
        self.post_wait("v1")
        self.post_wait("v1")
        self.pre("list_agents")
        self.handle(
            "PostToolUse",
            self.envelope(
                "PostToolUse",
                tool_name="list_agents",
                tool_input={},
                tool_response={"status": "ok", "state_version": "v1"},
            ),
        )
        self.assert_denied(self.pre("wait_agent"))

    def test_unknown_coverage_fails_open_and_is_bounded(self) -> None:
        for index in range(hook.MAX_COVERAGE_RECEIPTS + 12):
            envelope = self.envelope(
                "PostToolUse",
                session_id=f"unknown-session-{index}",
                turn_id=f"unknown-turn-{index}",
                tool_name="wait_agent",
                tool_input={},
            )
            self.assertEqual({}, self.handle("PostToolUse", envelope))
        receipts = list((self.state_root / "coverage").glob("*.json"))
        self.assertLessEqual(len(receipts), hook.MAX_COVERAGE_RECEIPTS)
        sample = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual("unknown_fail_open", sample["coverage"])

    def test_runtime_state_is_redacted(self) -> None:
        self.post_wait("v1")
        stored = "\n".join(
            path.read_text(encoding="utf-8")
            for path in self.state_root.rglob("*.json")
        )
        filenames = "\n".join(path.name for path in self.state_root.rglob("*.json"))
        for forbidden in (
            self.session_id,
            self.turn_id,
            "must-not-persist",
            "private raw response",
            "timeout_ms",
        ):
            self.assertNotIn(forbidden, stored)
            self.assertNotIn(forbidden, filenames)


class PreflightTests(HookTestCase):
    def bash(self, command: str, cwd: Path | None = None) -> dict[str, object]:
        return self.handle(
            "PreToolUse",
            self.envelope(
                "PreToolUse",
                cwd=str(cwd or self.workspace),
                tool_name="Bash",
                tool_use_id="bash-tool",
                tool_input={"command": command},
            ),
        )

    def exec_command(self, tool_input: object) -> dict[str, object]:
        return self.handle(
            "PreToolUse",
            self.envelope(
                "PreToolUse",
                cwd=str(self.workspace),
                tool_name="functions.exec_command",
                tool_use_id="exec-command-tool",
                tool_input=tool_input,
            ),
        )

    def patch(self, text: str) -> dict[str, object]:
        return self.handle(
            "PreToolUse",
            self.envelope(
                "PreToolUse",
                tool_name="apply_patch",
                tool_use_id="patch-tool",
                tool_input={"patch": text},
            ),
        )

    def test_valid_non_repository_command_passes(self) -> None:
        self.assertEqual({}, self.bash("echo hello"))
        self.assertEqual({}, self.bash("git --version"))

    def test_search_regex_is_not_treated_as_a_literal_path_glob(self) -> None:
        self.assertEqual({}, self.bash('rg -n "error.*timeout" codex_hook.py'))

    def test_compound_commands_fail_open_before_repository_or_glob_checks(self) -> None:
        self.assertEqual({}, self.bash("git status; echo inspected"))
        self.assertEqual({}, self.bash('git -C "missing-repo" status ;git --version'))
        self.assertEqual({}, self.bash("Get-Content missing*.txt | Select-Object -First 1"))

    def test_repository_required_git_command_denied_outside_repo(self) -> None:
        self.assert_denied(self.bash("git status"))

    def test_exec_command_accepts_cmd_and_compatible_command(self) -> None:
        self.assertEqual({}, self.exec_command({"cmd": "echo hello"}))
        self.assert_denied(self.exec_command({"cmd": "git status"}))
        self.assert_denied(self.exec_command({"command": "git status"}))

    def test_exec_command_missing_invalid_or_conflicting_command_is_denied(self) -> None:
        invalid_inputs = (
            None,
            {},
            {"cmd": None},
            {"cmd": ""},
            {"cmd": 7},
            {"cmd": "echo safe", "command": "git status"},
        )
        for tool_input in invalid_inputs:
            with self.subTest(tool_input=tool_input):
                self.assert_denied(self.exec_command(tool_input))

    def test_valid_git_explicit_c_repository_passes(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is unavailable")
        repository = self.root / "valid repo"
        completed = subprocess.run(
            ["git", "init", str(repository)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual({}, self.bash(f'git -C "{repository}" status'))

    def test_patch_add_update_delete_paths(self) -> None:
        existing = self.workspace / "existing.txt"
        existing.write_text("before", encoding="utf-8")
        self.assertEqual(
            {},
            self.patch("*** Begin Patch\n*** Add File: new.txt\n+new\n*** End Patch"),
        )
        self.assertEqual(
            {},
            self.patch("*** Begin Patch\n*** Update File: existing.txt\n@@\n-before\n+after\n*** End Patch"),
        )
        self.assertEqual(
            {},
            self.patch("*** Begin Patch\n*** Delete File: existing.txt\n*** End Patch"),
        )
        self.assert_denied(
            self.patch("*** Begin Patch\n*** Update File: missing.txt\n@@\n-old\n+new\n*** End Patch")
        )
        self.assert_denied(
            self.patch("*** Begin Patch\n*** Delete File: missing.txt\n*** End Patch")
        )

    def test_wildcard_zero_one_and_ambiguous(self) -> None:
        self.assert_denied(self.bash("Get-Content *.txt"))
        (self.workspace / "one.txt").write_text("one", encoding="utf-8")
        self.assertEqual({}, self.bash("Get-Content *.txt"))
        (self.workspace / "two.txt").write_text("two", encoding="utf-8")
        self.assert_denied(self.bash("Get-Content *.txt"))


class SessionRuntimeRootTests(HookTestCase):
    def test_uuid_session_receipt_is_written_under_session_scratch(self) -> None:
        self.session_id = "01a00a76-c3b7-79c3-bff6-2d97ace4fdf2"
        packet_root = self.root / "brain"
        envelope = self.envelope("PostToolUse", tool_name="Bash")
        self.assertEqual(
            {},
            hook.handle_hook("PreToolUse", envelope, packet_root=packet_root),
        )
        runtime_root = (
            packet_root
            / self.session_id
            / hook.PACKET_RELATIVE_PATH.parent
            / "_runtime"
        )
        receipts = list((runtime_root / "coverage").glob("*.json"))
        self.assertEqual(1, len(receipts))
        self.assertFalse((HOOK_DIR / "_runtime").exists())

    def test_non_uuid_session_is_hashed_and_contained(self) -> None:
        packet_root = self.root / "brain"
        envelope = self.envelope("PreToolUse")
        envelope["session_id"] = "../escape\\with/separators"
        runtime_root = hook._session_runtime_root(envelope, packet_root)
        self.assertIsNotNone(runtime_root)
        assert runtime_root is not None
        runtime_root.relative_to(packet_root.resolve())
        self.assertTrue(runtime_root.parts[-4].startswith("session-"))
        self.assertNotIn("escape", str(runtime_root))

    def test_missing_session_or_packet_root_has_no_session_runtime(self) -> None:
        envelope = self.envelope("PreToolUse")
        envelope.pop("session_id")
        self.assertIsNone(hook._session_runtime_root(envelope, self.root / "brain"))
        self.assertIsNone(hook._session_runtime_root(self.envelope("PreToolUse"), None))


class CompactionTests(HookTestCase):
    def test_uuid_session_resolves_packet_from_session_scratch_root(self) -> None:
        self.session_id = "01a00a76-c3b7-79c3-bff6-2d97ace4fdf2"
        packet_root = self.root / "brain"
        packet = packet_root / self.session_id / hook.PACKET_RELATIVE_PATH
        packet.parent.mkdir(parents=True)
        packet.write_text(
            json.dumps(
                {
                    "objective": "Session-scoped objective",
                    "authorization_scope": "read packet only",
                    "completed_steps": ["one"],
                    "output_paths": ["C:/scratch/result.json"],
                }
            ),
            encoding="utf-8",
        )
        precompact = self.envelope("PreCompact", trigger="auto")
        self.assertEqual(
            {},
            self.handle("PreCompact", precompact, packet_root=packet_root),
        )
        session_start = self.envelope("SessionStart", source="compact")
        session_start.pop("turn_id", None)
        response = self.handle("SessionStart", session_start, packet_root=packet_root)
        recovered = json.loads(response["hookSpecificOutput"]["additionalContext"])["context_recovery"]
        self.assertTrue(recovered["required_fields_verified"])
        self.assertEqual("Session-scoped objective", recovered["objective"])

    def precompact(self, packet: Path | None) -> dict[str, object]:
        return self.handle(
            "PreCompact",
            self.envelope("PreCompact", trigger="auto", custom_instructions="do not persist"),
            packet,
        )

    def session_start(self, packet: Path | None) -> dict[str, object]:
        envelope = self.envelope("SessionStart", source="compact")
        envelope.pop("turn_id", None)
        return self.handle("SessionStart", envelope, packet)

    def test_valid_packet_receipt_and_minimal_recovery_context(self) -> None:
        packet = self.write_packet()
        self.assertEqual({}, self.precompact(packet))
        receipts = list((self.state_root / "compaction").glob("*.json"))
        self.assertEqual(1, len(receipts))
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "schema_version",
                "state_sha256",
                "completed_step_count",
                "output_path_count",
                "required_fields_verified",
            },
            set(receipt),
        )
        response = self.session_start(packet)
        specific = response["hookSpecificOutput"]
        self.assertEqual("SessionStart", specific["hookEventName"])
        recovered = json.loads(specific["additionalContext"])["context_recovery"]
        self.assertTrue(recovered["required_fields_verified"])
        self.assertEqual("Sensitive business objective", recovered["objective"])

    def test_invalid_packet_never_claims_verified(self) -> None:
        packet = self.write_packet(output_paths="not-an-array")
        self.assertEqual({}, self.precompact(packet))
        response = self.session_start(packet)
        self.assertEqual({}, response)
        serialized = json.dumps(response)
        self.assertNotIn("required_fields_verified", serialized)

    def test_tamper_detection_never_claims_verified(self) -> None:
        packet = self.write_packet()
        self.precompact(packet)
        packet.write_text(
            json.dumps(
                {
                    "objective": "Tampered objective",
                    "authorization_scope": {"write": "owned subtree only"},
                    "completed_steps": ["Inspected evidence"],
                    "output_paths": ["C:/scratch/result.json"],
                }
            ),
            encoding="utf-8",
        )
        response = self.session_start(packet)
        self.assertEqual({}, response)
        self.assertNotIn("required_fields_verified", json.dumps(response))

    def test_compaction_runtime_receipt_contains_no_business_text(self) -> None:
        packet = self.write_packet()
        self.precompact(packet)
        stored = "\n".join(
            path.read_text(encoding="utf-8")
            for path in self.state_root.rglob("*.json")
        )
        self.assertNotIn("Sensitive business objective", stored)
        self.assertNotIn("owned subtree only", stored)
        self.assertNotIn(str(packet), stored)
        self.assertNotIn(self.session_id, stored)


class SourceResidueTests(unittest.TestCase):
    def test_no_default_runtime_state_or_bytecode_residue(self) -> None:
        self.assertFalse((HOOK_DIR / "_runtime").exists())
        self.assertFalse((HOOK_DIR / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
