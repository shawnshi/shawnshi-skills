import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("standardize_codex_rollout.py")
SPEC = importlib.util.spec_from_file_location("standardize_codex_rollout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def rollout_record(timestamp, record_type, payload):
    return {"timestamp": timestamp, "type": record_type, "payload": payload}


def shell_source(command, key="command"):
    return f"const r = await tools.shell_command({{{key}:{json.dumps(command)}}}); text(r);"


def wrapped_output(payload, *, failed=False):
    label = "Script failed" if failed else "Script completed"
    code = 1 if failed else 0
    body = json.dumps(payload, sort_keys=True)
    return [
        {"type": "text", "text": f"{label}\nWall time 0.1 seconds\nOutput:\n"},
        {"type": "text", "text": f"Exit code: {code}\nWall time: 0.1 seconds\nOutput:\n{body}"},
    ]


def run_standardizer(records, authorization_receipts=None):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        snapshot = root / "snapshot.jsonl"
        output = root / "events.jsonl"
        summary = root / "summary.json"
        snapshot.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        command = [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(snapshot),
            "--output",
            str(output),
            "--summary",
            str(summary),
            "--start",
            "2026-08-16T12:00:00Z",
            "--end",
            "2026-08-16T12:10:00Z",
        ]
        if authorization_receipts is not None:
            receipts = root / "authorization.jsonl"
            receipts.write_text(
                "".join(json.dumps(receipt) + "\n" for receipt in authorization_receipts),
                encoding="utf-8",
            )
            command.extend(["--authorization-receipts", str(receipts)])
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        return events, json.loads(summary.read_text(encoding="utf-8"))


class IntentTests(unittest.TestCase):
    def test_reading_manifest_script_is_not_a_write(self):
        source = 'const r = await tools.exec_command({cmd: "Get-Content -LiteralPath \'C:\\\\repo\\\\scripts\\\\generate_resource_manifests.ps1\' -Raw"});'
        self.assertIsNone(MODULE.write_intent("exec", source))

    def test_manifest_execution_and_patch_are_writes(self):
        manifest = 'const r = await tools.exec_command({cmd: "& \'C:\\\\repo\\\\scripts\\\\generate_resource_manifests.ps1\' -Root \'C:\\\\repo\' -IncludeSkills \'audit\'"});'
        self.assertEqual(MODULE.write_intent("exec", manifest)["operation"], "exec_write")

        patch = 'const patch = "*** Begin Patch\\n*** Update File: C:\\\\repo\\\\a.txt\\n@@\\n-old\\n+new\\n*** End Patch"; await tools.apply_patch(patch);'
        intent = MODULE.write_intent("exec", patch)
        self.assertEqual(intent["operation"], "apply_patch")
        self.assertEqual(intent["target_count"], 1)

    def test_diary_intent_supports_command_cmd_and_variable_backing(self):
        historical = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops replace-date --file diary"
        current = "python -X utf8 'C:/fixture/diary_ops.py' replace-date --file diary"
        scope = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops scope --file diary"
        self.assertEqual(MODULE.write_intent("exec", shell_source(historical))["operation"], "replace_date")
        self.assertEqual(MODULE.write_intent("exec", shell_source(current, key="cmd"))["operation"], "replace_date")
        self.assertIsNone(MODULE.write_intent("exec", shell_source(scope)))


class ExternalReceiptSecurityTests(unittest.TestCase):
    def run_with_receipt(self, flag, receipt):
        records = [
            rollout_record(
                "2026-08-16T12:00:00Z",
                "event_msg",
                {"type": "task_started", "turn_id": "r-receipt"},
            )
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = root / "snapshot.jsonl"
            receipts = root / "receipts.jsonl"
            output = root / "events.jsonl"
            summary = root / "summary.json"
            snapshot.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            receipts.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(snapshot),
                    "--output",
                    str(output),
                    "--summary",
                    str(summary),
                    "--start",
                    "2026-08-16T12:00:00Z",
                    flag,
                    str(receipts),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            output_text = output.read_text(encoding="utf-8") if output.exists() else None
        return result, output_text

    def test_allowlisted_skill_receipt_has_no_raw_path(self):
        receipt = {
            "schema_version": 2,
            "event_id": "skill-load-sample",
            "timestamp": "2026-08-16T12:00:01Z",
            "root_task_id": "r-receipt",
            "actor_id": "root",
            "actor_type": "root",
            "event_type": "skill_load",
            "component": "skill_loader",
            "operation": "read_full_skill",
            "status": "ok",
            "context_epoch": "0",
            "skill_name": "sample",
            "skill_path_sha256": "a" * 64,
            "skill_version": None,
            "skill_sha256": "b" * 64,
            "skill_tokens": 10,
            "tokenizer": "cl100k_base",
        }
        result, output = self.run_with_receipt("--skill-receipts", receipt)
        self.assertEqual(result.returncode, 0, result.stderr)
        event = next(
            item for item in map(json.loads, output.splitlines())
            if item["event_type"] == "skill_load"
        )
        self.assertNotIn("skill_path", event)
        self.assertEqual(event["skill_path_sha256"], "a" * 64)

    def test_external_receipts_reject_absolute_paths_and_extra_secrets(self):
        fixtures = (
            (
                "--skill-receipts",
                {
                    "event_type": "skill_load",
                    "skill_path": "C:/Users/private-user/.codex/skills/sample/SKILL.md",
                    "extra_secret": "must-not-enter-events",
                },
            ),
            (
                "--context-receipts",
                {
                    "event_type": "context_recovered",
                    "extra_secret": "must-not-enter-events",
                },
            ),
        )
        for flag, receipt in fixtures:
            with self.subTest(flag=flag):
                result, output = self.run_with_receipt(flag, receipt)
                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(output)
                self.assertNotIn("C:/Users/private-user", combined)
                self.assertNotIn("must-not-enter-events", combined)


class ExtractorRemediationTests(unittest.TestCase):
    def test_schema_v2_diary_commit_preserves_historical_receipt_hashes(self):
        scope_hash = "9" * 64
        command = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops replace-date --file diary"
        commit = {
            "schema_version": 2,
            "component": "diary_ops",
            "status": "success",
            "event_type": "write_commit",
            "task_mode": "write",
            "action": "replace_date",
            "operation": "replace_date",
            "authorization_id": "historical-auth",
            "authorization_scope_sha256": scope_hash,
            "write_scope_sha256": scope_hash,
            "payload_sha256": "8" * 64,
            "target": "C:/fixture/private.md",
            "message": "secret-diary-content",
        }
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-history"}),
            rollout_record("2026-08-16T12:00:01Z", "response_item", {"type": "custom_tool_call", "call_id": "history-1", "name": "exec", "input": shell_source(command)}),
            rollout_record("2026-08-16T12:00:02Z", "response_item", {"type": "custom_tool_call_output", "call_id": "history-1", "output": wrapped_output(commit)}),
        ]

        events, summary = run_standardizer(records)
        commits = [event for event in events if event["event_type"] == "write_commit"]
        self.assertEqual(len(commits), 1)
        self.assertEqual(summary["write_commit_count"], 1)
        self.assertEqual(commits[0]["authorization_id"], "historical-auth")
        self.assertEqual(commits[0]["authorization_scope_sha256"], scope_hash)
        self.assertEqual(commits[0]["write_scope_sha256"], scope_hash)
        serialized = json.dumps(events)
        self.assertNotIn("C:/fixture/private.md", serialized)
        self.assertNotIn("secret-diary-content", serialized)

    def test_three_diary_pairs_preserve_hashes_without_business_text(self):
        records = [rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-diary"})]
        expected = []
        second = 1
        for index, marker in enumerate(("a", "b", "c"), start=1):
            authorization_id = f"auth-{index}"
            scope_hash = marker * 64
            payload_hash = str(index) * 64
            expected.append((authorization_id, scope_hash))
            scope_call = f"scope-{index}"
            write_call = f"write-{index}"
            scope_command = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops scope --file diary"
            write_command = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops replace-date --file diary --content_file C:/fixture/draft.md"
            approval = {
                "schema": "diary-write-scope-v1",
                "status": "ready_for_confirmation",
                "event_type": "approval_request",
                "task_mode": "write",
                "action": "replace_date",
                "operation": "replace_date",
                "authorization_id": authorization_id,
                "authorization_scope_sha256": scope_hash,
                "payload_sha256": payload_hash,
                "target": f"C:/fixture/private-{index}.md",
                "message": "secret-diary-content",
            }
            commit = dict(approval)
            commit.update({"status": "success", "event_type": "write_commit", "write_scope_sha256": scope_hash})
            records.extend(
                [
                    rollout_record(f"2026-08-16T12:00:{second:02d}Z", "response_item", {"type": "custom_tool_call", "call_id": scope_call, "name": "exec", "input": shell_source(scope_command)}),
                    rollout_record(f"2026-08-16T12:00:{second + 1:02d}Z", "response_item", {"type": "custom_tool_call_output", "call_id": scope_call, "output": wrapped_output(approval)}),
                    rollout_record(f"2026-08-16T12:00:{second + 2:02d}Z", "response_item", {"type": "custom_tool_call", "call_id": write_call, "name": "exec", "input": shell_source(write_command, key="cmd" if index == 2 else "command")}),
                    rollout_record(f"2026-08-16T12:00:{second + 3:02d}Z", "response_item", {"type": "custom_tool_call_output", "call_id": write_call, "output": wrapped_output(commit)}),
                ]
            )
            second += 4

        events, summary = run_standardizer(records)
        approvals = [event for event in events if event["event_type"] == "approval_request"]
        attempts = [event for event in events if event["event_type"] == "write_attempt"]
        commits = [event for event in events if event["event_type"] == "write_commit"]
        self.assertEqual((len(approvals), len(attempts), len(commits)), (3, 3, 3))
        self.assertEqual(summary["write_attempt_count"], 3)
        self.assertEqual(summary["write_commit_count"], 3)
        for authorization_id, scope_hash in expected:
            approval = next(event for event in approvals if event["authorization_id"] == authorization_id)
            commit = next(event for event in commits if event["authorization_id"] == authorization_id)
            self.assertEqual(approval["authorization_scope_sha256"], scope_hash)
            self.assertEqual(commit["authorization_scope_sha256"], scope_hash)
            self.assertEqual(commit["write_scope_sha256"], scope_hash)
        serialized = json.dumps(events)
        self.assertNotIn("C:/fixture/private", serialized)
        self.assertNotIn("secret-diary-content", serialized)
        self.assertNotIn("content_file", serialized)

    def test_validation_rejection_is_observable_without_commit_or_executor_failure(self):
        scope_hash = "d" * 64
        command = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops replace-date --file diary --content_file C:/fixture/draft.md"
        rejection = {
            "schema": "diary-write-scope-v1",
            "status": "error",
            "error_code": "VALIDATION_FAILED",
            "action": "replace_date",
            "operation": "replace_date",
            "authorization_id": "auth-rejected",
            "authorization_scope_sha256": scope_hash,
            "payload_sha256": "e" * 64,
            "target": "C:/fixture/private.md",
            "message": "secret validation detail",
        }
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-reject"}),
            rollout_record("2026-08-16T12:00:01Z", "response_item", {"type": "custom_tool_call", "call_id": "reject-1", "name": "exec", "input": shell_source(command)}),
            rollout_record("2026-08-16T12:00:02Z", "response_item", {"type": "custom_tool_call_output", "call_id": "reject-1", "output": wrapped_output(rejection, failed=True)}),
        ]
        events, summary = run_standardizer(records)
        self.assertEqual(sum(event["event_type"] == "write_attempt" for event in events), 1)
        self.assertEqual(sum(event["event_type"] == "write_commit" for event in events), 0)
        tool_event = next(event for event in events if event["event_type"] == "tool_call")
        self.assertEqual(tool_event["status"], "ok")
        self.assertEqual(tool_event["outcome"], "validation_guard")
        self.assertFalse(tool_event["executor_failure"])
        self.assertEqual(summary["tool_failures"], 0)
        self.assertEqual(next(event for event in events if event["event_type"] == "write_attempt")["authorization_id"], "auth-rejected")
        self.assertNotIn("secret validation detail", json.dumps(events))

    def test_duplicate_is_suppressed_and_conflicting_receipts_fail_closed(self):
        embedded_scope = "f" * 64
        external_scope = "0" * 64
        command = "$ops='C:/fixture/diary_ops.py'\npython -X utf8 $ops replace-date --file diary"
        commit = {
            "schema": "diary-write-scope-v1",
            "status": "success",
            "event_type": "write_commit",
            "action": "replace_date",
            "operation": "replace_date",
            "authorization_id": "embedded-auth",
            "authorization_scope_sha256": embedded_scope,
            "write_scope_sha256": embedded_scope,
            "payload_sha256": "1" * 64,
        }
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-conflict"}),
            rollout_record("2026-08-16T12:00:01Z", "response_item", {"type": "custom_tool_call", "call_id": "conflict-1", "name": "exec", "input": shell_source(command)}),
            rollout_record("2026-08-16T12:00:02Z", "response_item", {"type": "custom_tool_call_output", "call_id": "conflict-1", "output": wrapped_output(commit)}),
        ]
        events, _ = run_standardizer(
            records,
            [{"call_id": "conflict-1", "authorization_id": "external-auth", "authorization_scope_sha256": external_scope}],
        )
        attempts = [event for event in events if event["event_type"] == "write_attempt"]
        commits = [event for event in events if event["event_type"] == "write_commit"]
        self.assertEqual((len(attempts), len(commits)), (1, 1))
        for event in (attempts[0], commits[0]):
            self.assertTrue(event["authorization_conflict"])
            self.assertNotIn("authorization_id", event)
            self.assertNotIn("authorization_scope_sha256", event)
            self.assertEqual(event["embedded_authorization_scope_sha256"], embedded_scope)
            self.assertEqual(event["external_authorization_scope_sha256"], external_scope)
        self.assertEqual(commits[0]["write_scope_sha256"], embedded_scope)

    def test_error_classifier_is_segment_aware_and_ansi_safe(self):
        parser = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\n\x1b[31;1mParserError: \x1b[0minvalid pipeline"
        no_match = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\n"
        guard = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nSkill audit gate failed: inventory_mismatch=1"
        interface = "Script failed\nOutput:\nScript error:\nTypeError: tools.shell_command is not a function"
        unicode_failure = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nTraceback (most recent call last):\nUnicodeDecodeError: invalid byte"
        path_failure = "Script failed\nOutput:\nScript error:\nExit code: 2\nOutput:\nrg: C:/fixture/missing: The system cannot find the path specified."
        python_path = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nTraceback (most recent call last):\n  File 'task.py', line 1\nFileNotFoundError: missing"
        python_permission = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nTraceback (most recent call last):\nPermissionError: denied"
        python_dependency = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nTraceback (most recent call last):\nModuleNotFoundError: unavailable"
        python_validation = "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nTraceback (most recent call last):\nValueError: invalid fixture"
        passive_parser = "Script completed\nOutput:\nParserError: invalid passive read"
        resource_permission = "Script completed\nOutput:\nResourceUnavailable: Program failed to run: Access to the path is denied"
        clean_after_history = "Script completed\nOutput:\nprinted history: Exit code: 1\nOutput:\nclean payload"
        fallback = "Script failed\nOutput:\nScript error:\nunclassified failure"
        cases = [
            (parser, shell_source("pwsh -File C:/fixture/probe.ps1"), ("syntax", "powershell_parser", True)),
            (no_match, shell_source("rg -n needle C:/fixture/source.py"), ("data", "no_match", False)),
            (guard, shell_source("python C:/fixture/validator.py"), ("validation", "validation_guard", False)),
            (interface, shell_source("Get-Content C:/fixture/source.py"), ("dependency", "tool_interface", True)),
            (unicode_failure, shell_source("python C:/fixture/validator.py"), ("data", "unicode_decode", True)),
            (path_failure, shell_source("rg -n needle C:/fixture/missing"), ("path", "search_path", True)),
            (python_path, shell_source("python C:/fixture/task.py"), ("path", "python_path", True)),
            (python_permission, shell_source("python C:/fixture/task.py"), ("permission", "python_permission", True)),
            (python_dependency, shell_source("python C:/fixture/task.py"), ("dependency", "python_dependency", True)),
            (python_validation, shell_source("python C:/fixture/task.py"), ("validation", "python_validation", True)),
            (passive_parser, shell_source("Get-Content C:/fixture/source.py"), ("syntax", "powershell_parser", True)),
            (resource_permission, shell_source("Get-Content C:/fixture/source.py"), ("permission", "process_permission", True)),
            (fallback, shell_source("python C:/fixture/task.py"), ("unknown", "script_failed", True)),
        ]
        for output, source, expected in cases:
            with self.subTest(expected=expected):
                result = MODULE.classify_tool_output(output, source)
                self.assertEqual((result["error_category"], result["error_signature"], result["executor_failure"]), expected)

        self.assertIsNone(MODULE.classify_tool_output(clean_after_history, shell_source("python C:/fixture/task.py")))

        source_read = "Script completed\nOutput:\nconst ERROR_LITERAL = 'VALIDATION_FAILED';"
        self.assertIsNone(MODULE.classify_tool_output(source_read, shell_source("Get-Content C:/fixture/source.py")))
        search_read = "Script completed\nOutput:\nC:/fixture/source.py:9:VALIDATION_FAILED"
        self.assertIsNone(MODULE.classify_tool_output(search_read, shell_source("rg -n VALIDATION_FAILED C:/fixture/source.py")))

    def test_failed_generic_write_never_generates_commit(self):
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-write-fail"}),
            rollout_record("2026-08-16T12:00:01Z", "response_item", {"type": "custom_tool_call", "call_id": "write-fail", "name": "exec", "input": shell_source("Set-Content C:/fixture/output.txt value")}),
            rollout_record("2026-08-16T12:00:02Z", "response_item", {"type": "custom_tool_call_output", "call_id": "write-fail", "output": "Script completed\nOutput:\nResourceUnavailable: Program failed to run: Access to the path is denied"}),
        ]

        events, summary = run_standardizer(records)
        tools = [event for event in events if event["event_type"] == "tool_call"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["status"], "error")
        self.assertEqual(len([event for event in events if event["event_type"] == "write_attempt"]), 1)
        self.assertEqual(len([event for event in events if event["event_type"] == "write_commit"]), 0)
        self.assertEqual(summary["tool_failures"], 1)

    def test_session_meta_preserves_redacted_subagent_provenance(self):
        records = [
            rollout_record("2026-08-16T12:00:00Z", "session_meta", {"id": "sensitive-thread-id", "thread_source": "subagent"}),
            rollout_record("2026-08-16T12:00:01Z", "event_msg", {"type": "task_started", "turn_id": "r-child"}),
            rollout_record("2026-08-16T12:00:02Z", "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 90, "output_tokens": 10}, "last_token_usage": {"input_tokens": 90, "output_tokens": 10}}}),
        ]

        events, _ = run_standardizer(records)
        self.assertTrue(events)
        self.assertTrue(all(event["actor_type"] == "subagent" for event in events))
        self.assertTrue(all(event["actor_id"].startswith("subagent-") for event in events))
        self.assertNotIn("sensitive-thread-id", json.dumps(events))

    def test_embedded_parent_session_meta_cannot_rebind_rollout_actor(self):
        records = [
            rollout_record("2026-08-16T12:00:00Z", "session_meta", {"id": "child-thread", "thread_source": "subagent"}),
            rollout_record("2026-08-16T12:00:01Z", "event_msg", {"type": "task_started", "turn_id": "r-child"}),
            rollout_record("2026-08-16T12:00:02Z", "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 90, "output_tokens": 10}, "last_token_usage": {"input_tokens": 90, "output_tokens": 10}}}),
            rollout_record("2026-08-16T12:00:03Z", "session_meta", {"id": "embedded-parent", "thread_source": "user"}),
            rollout_record("2026-08-16T12:00:04Z", "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 11}, "last_token_usage": {"input_tokens": 10, "output_tokens": 1}}}),
        ]

        events, _ = run_standardizer(records)

        self.assertTrue(events)
        self.assertTrue(all(event["actor_type"] == "subagent" for event in events))
        self.assertTrue(all(event["actor_id"].startswith("subagent-") for event in events))

    def test_compound_expected_outcomes_do_not_count_as_failures(self):
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r-compound"}),
            rollout_record("2026-08-16T12:00:01Z", "response_item", {"type": "custom_tool_call", "call_id": "compound-rg", "name": "exec", "input": shell_source("python C:/fixture/probe.py; rg -n needle C:/fixture/source.py")}),
            rollout_record("2026-08-16T12:00:02Z", "response_item", {"type": "custom_tool_call_output", "call_id": "compound-rg", "output": "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\n--- SEARCH ---\n"}),
            rollout_record("2026-08-16T12:00:03Z", "response_item", {"type": "custom_tool_call", "call_id": "compound-guard", "name": "exec", "input": shell_source("python C:/fixture/tests.py; python C:/fixture/validator.py")}),
            rollout_record("2026-08-16T12:00:04Z", "response_item", {"type": "custom_tool_call_output", "call_id": "compound-guard", "output": "Script failed\nOutput:\nScript error:\nExit code: 1\nOutput:\nSkill audit gate failed: missing_manifest=1"}),
        ]
        events, summary = run_standardizer(records)
        tools = {event["call_id"]: event for event in events if event["event_type"] == "tool_call"}
        self.assertEqual(tools["compound-rg"]["outcome"], "no_match")
        self.assertEqual(tools["compound-guard"]["outcome"], "validation_guard")
        self.assertEqual([step["operation"] for step in tools["compound-rg"]["substeps"]], ["python", "rg"])
        self.assertEqual(tools["compound-rg"]["substeps"][-1]["outcome"], "no_match")
        self.assertTrue(all(event["status"] == "ok" for event in tools.values()))
        self.assertEqual(summary["tool_failures"], 0)


class EndToEndTests(unittest.TestCase):
    def test_authorization_receipt_is_bound_by_call_id_and_scope(self):
        source_input = 'const patch = "*** Begin Patch\\n*** Update File: C:\\\\repo\\\\a.txt\\n@@\\n-old\\n+new\\n*** End Patch"; await tools.apply_patch(patch);'
        intent = MODULE.write_intent("exec", source_input)
        scope = MODULE.write_scope_sha256("exec", intent)
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r1"}),
            rollout_record(
                "2026-08-16T12:00:01Z",
                "response_item",
                {"type": "custom_tool_call", "call_id": "patch-auth", "name": "exec", "input": source_input},
            ),
            rollout_record(
                "2026-08-16T12:00:02Z",
                "response_item",
                {"type": "custom_tool_call_output", "call_id": "patch-auth", "output": "Script completed\nOutput:\n{}"},
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = root / "snapshot.jsonl"
            receipts = root / "authorization.jsonl"
            output = root / "events.jsonl"
            summary = root / "summary.json"
            snapshot.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            receipts.write_text(
                json.dumps(
                    {
                        "call_id": "patch-auth",
                        "authorization_id": "auth-1",
                        "authorization_scope_sha256": scope,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(snapshot),
                    "--output",
                    str(output),
                    "--summary",
                    str(summary),
                    "--start",
                    "2026-08-16T12:00:00Z",
                    "--authorization-receipts",
                    str(receipts),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        commit = next(event for event in events if event["event_type"] == "write_commit")
        self.assertEqual(commit["authorization_id"], "auth-1")
        self.assertEqual(commit["write_scope_sha256"], scope)
        self.assertEqual(commit["authorization_scope_sha256"], scope)

    def test_rollout_standardization_surfaces_nested_errors_and_writes(self):
        records = [
            rollout_record("2026-08-16T12:00:00Z", "event_msg", {"type": "task_started", "turn_id": "r1"}),
            rollout_record(
                "2026-08-16T12:00:01Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "call_id": "patch-1",
                    "name": "exec",
                    "input": 'const patch = "*** Begin Patch\\n*** Update File: C:\\\\repo\\\\a.txt\\n@@\\n-secret-body\\n+replacement\\n*** End Patch"; await tools.apply_patch(patch);',
                },
            ),
            rollout_record(
                "2026-08-16T12:00:02Z",
                "response_item",
                {"type": "custom_tool_call_output", "call_id": "patch-1", "output": "Script completed\nOutput:\n{}"},
            ),
            rollout_record(
                "2026-08-16T12:00:03Z",
                "response_item",
                {"type": "custom_tool_call", "call_id": "parser-1", "name": "exec", "input": "const r = 1;"},
            ),
            rollout_record(
                "2026-08-16T12:00:04Z",
                "response_item",
                {
                    "type": "custom_tool_call_output",
                    "call_id": "parser-1",
                    "output": "Script completed\nOutput:\n\nParserError: invalid pipeline",
                },
            ),
            rollout_record(
                "2026-08-16T12:00:05Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "call_id": "read-1",
                    "name": "exec",
                    "input": 'const r = await tools.exec_command({cmd: "Get-Content -LiteralPath \'C:\\\\repo\\\\scripts\\\\generate_resource_manifests.ps1\' -Raw"});',
                },
            ),
            rollout_record(
                "2026-08-16T12:00:06Z",
                "response_item",
                {"type": "custom_tool_call_output", "call_id": "read-1", "output": "Script completed\nOutput:\ntext"},
            ),
            rollout_record(
                "2026-08-16T12:00:07Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "call_id": "manifest-1",
                    "name": "exec",
                    "input": 'const r = await tools.exec_command({cmd: "& \'C:\\\\repo\\\\scripts\\\\generate_resource_manifests.ps1\' -Root \'C:\\\\repo\' -IncludeSkills \'audit\'"});',
                },
            ),
            rollout_record(
                "2026-08-16T12:00:08Z",
                "response_item",
                {"type": "custom_tool_call_output", "call_id": "manifest-1", "output": "Script completed\nOutput:\nwritten"},
            ),
            rollout_record(
                "2026-08-16T12:00:09Z",
                "response_item",
                {
                    "type": "custom_tool_call",
                    "call_id": "skill-1",
                    "name": "exec",
                    "input": 'const r = await tools.exec_command({cmd: "Get-Content -LiteralPath \'C:\\\\repo\\\\audit\\\\SKILL.md\' -Raw"});',
                },
            ),
            rollout_record(
                "2026-08-16T12:00:10Z",
                "response_item",
                {"type": "custom_tool_call_output", "call_id": "skill-1", "output": "Script completed\nOutput:\nskill"},
            ),
            rollout_record("2026-08-16T12:00:11Z", "event_msg", {"type": "context_compacted"}),
            rollout_record(
                "2026-08-16T12:00:12Z",
                "response_item",
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "restored"}]},
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "snapshot.jsonl"
            output = root / "events.jsonl"
            summary = root / "summary.json"
            source.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--summary",
                    str(summary),
                    "--start",
                    "2026-08-16T12:00:00Z",
                    "--end",
                    "2026-08-16T12:00:20Z",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            summary_payload = json.loads(summary.read_text(encoding="utf-8"))

        event_types = [event["event_type"] for event in events]
        self.assertEqual(event_types.count("write_attempt"), 2)
        self.assertEqual(event_types.count("write_commit"), 2)
        self.assertEqual(event_types.count("skill_load_candidate"), 1)
        self.assertEqual(event_types.count("context_recovered"), 1)
        parser_event = next(event for event in events if event.get("event_id") == "tool-parser-1")
        self.assertEqual(parser_event["status"], "error")
        self.assertEqual(parser_event["outer_status"], "ok")
        self.assertEqual(parser_event["error_signature"], "powershell_parser")
        self.assertFalse(next(event for event in events if event["event_type"] == "context_recovered")["required_fields_verified"])
        self.assertNotIn("secret-body", json.dumps(events))
        self.assertEqual(summary_payload["write_commit_count"], 2)
        self.assertEqual(summary_payload["nested_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
