from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tests.common import SCRIPTS, SKILL_ROOT, run_python


SCRIPT = "select_execution_profile.py"
HOST_ENV_KEYS = (
    "DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON",
    "DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON",
    "DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON",
    "DISCOVERY_CALL_CANDIDATE_TRUSTED_KEYS_JSON",
    "DISCOVERY_CALL_GOVERNANCE_NONCE_DIR",
    "DISCOVERY_CALL_GOVERNANCE_PUBLIC_KEY_B64",
    "DISCOVERY_CALL_GOVERNANCE_TRUSTED_ISSUER",
    "DISCOVERY_CALL_GOVERNANCE_TRUSTED_KEY_ID",
)


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in HOST_ENV_KEYS:
        env.pop(key, None)
    return env


def _run(*args: str, env: dict[str, str] | None = None):
    process_env = env or _clean_env()
    with patch.dict(os.environ, process_env, clear=True):
        result = run_python(SCRIPT, list(args))
    return result, json.loads(result.stdout)


class ExecutionProfileTests(unittest.TestCase):
    def test_public_only_draft_is_available_without_protected_host(self):
        result, payload = _run(
            "--business-mode",
            "standard_visit",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "draft",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["execution_profile"], "public_draft")
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["result_state"], "draft_for_review")
        self.assertFalse(payload["ready_for_use"])
        self.assertEqual(payload["question_count"], 0)
        self.assertEqual(
            payload["allowed_operations"],
            ["public_web_open", "public_web_search", "validate_public_draft"],
        )
        self.assertTrue(payload["requires_output_validation"])
        self.assertEqual(
            payload["research_budget"],
            {
                "public_tool_calls_max": 12,
                "public_searches_max": 6,
                "direct_sources_target_max": 10,
                "delegated_workers_max": 0,
            },
        )
        self.assertEqual(
            payload["research_stop_contract"],
            {
                "count_search_and_open_calls_together": True,
                "delegate_research": False,
                "on_budget_exhausted": "deliver_partial_with_evidence_warning",
                "validation_after_last_edit_required": True,
            },
        )
        self.assertEqual(
            payload["output_validation"]["argv"],
            [
                str(Path(sys.executable).resolve()),
                "-B",
                str((SCRIPTS / "validate_public_draft.py").resolve()),
            ],
        )
        self.assertEqual(payload["output_validation"]["cwd"], str(SKILL_ROOT.resolve()))
        self.assertRegex(payload["output_validation"]["script_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(payload["output_validation"]["input_transport"], "stdin")
        self.assertTrue(payload["output_validation"]["must_pass_before_delivery"])
        self.assertEqual(
            payload["output_validation"]["schema"],
            "discovery-call-public-draft-validation/v1",
        )
        self.assertIn("create_workspace", payload["forbidden_operations"])
        self.assertIn("mark_ready", payload["forbidden_operations"])
        self.assertIn("external_send", payload["forbidden_operations"])

    def test_hostless_internal_scope_fails_closed(self):
        result, payload = _run(
            "--business-mode",
            "strategic_account",
            "--data-scope",
            "authorized_internal",
            "--requested-outcome",
            "draft",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_host_required")
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["allowed_operations"], [])
        self.assertEqual(payload["question_count"], 1)
        self.assertFalse(payload["ready_for_use"])

    def test_conflict_precedes_public_draft_and_asks_one_question(self):
        result, payload = _run(
            "--business-mode",
            "standard_visit",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "draft",
            "--unresolved-conflict",
            "customer_identity",
            "--unresolved-conflict",
            "meeting_time",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_conflict")
        self.assertEqual(payload["question_count"], 1)
        self.assertEqual(payload["allowed_operations"], [])
        self.assertEqual(
            payload["conflict_fields"],
            ["customer_identity", "meeting_time"],
        )

    def test_external_action_uses_fixed_high_risk_contract(self):
        result, payload = _run(
            "--business-mode",
            "letter",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "external_send",
        )
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_high_risk")
        self.assertEqual(payload["question_count"], 0)
        self.assertEqual(
            payload["response_sections"],
            ["拒绝项", "逐项原因", "可做部分", "所需补充材料", "实名审批路径"],
        )
        self.assertEqual(payload["allowed_operations"], [])

    def test_partial_host_capability_never_enables_formal_workflow(self):
        env = _clean_env()
        env["DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON"] = "{}"
        env["DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON"] = "{}"
        result, payload = _run(
            "--business-mode",
            "standard_visit",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "official_workspace",
            env=env,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_host_required")
        self.assertFalse(payload["formal_path_available"])
        self.assertIn("source_capture", payload["missing_capabilities"])
        self.assertIn("candidate_attestation", payload["missing_capabilities"])
        self.assertIn("governance", payload["missing_capabilities"])

    def test_complete_capability_manifest_only_allows_signed_preflight(self):
        env = _clean_env()
        env.update(
            {
                "DISCOVERY_CALL_INTAKE_TRUSTED_KEYS_JSON": '{"issuer":{"key":"value"}}',
                "DISCOVERY_CALL_CURRENT_REQUEST_CONTEXT_JSON": '{"request_id":"req-1"}',
                "DISCOVERY_CALL_CAPABILITY_TRUSTED_KEYS_JSON": '{"issuer":{"key":"value"}}',
                "DISCOVERY_CALL_CANDIDATE_TRUSTED_KEYS_JSON": '{"issuer":{"key":"value"}}',
                "DISCOVERY_CALL_GOVERNANCE_NONCE_DIR": "/protected/nonce-ledger",
                "DISCOVERY_CALL_GOVERNANCE_PUBLIC_KEY_B64": "public-key",
                "DISCOVERY_CALL_GOVERNANCE_TRUSTED_ISSUER": "issuer",
                "DISCOVERY_CALL_GOVERNANCE_TRUSTED_KEY_ID": "key",
            }
        )
        result, payload = _run(
            "--business-mode",
            "standard_visit",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "official_workspace",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["execution_profile"], "protected_workflow_candidate")
        self.assertEqual(payload["allowed_operations"], ["signed_preflight"])
        self.assertFalse(payload["formal_authorized"])
        self.assertFalse(payload["requires_output_validation"])
        self.assertNotIn("output_validation", payload)
        self.assertIn("create_workspace", payload["forbidden_operations"])
        self.assertIn("public_web_search", payload["forbidden_operations"])

    def test_release_is_never_downgraded_to_public_draft(self):
        result, payload = _run(
            "--business-mode",
            "briefing",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "release",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_host_required")
        self.assertFalse(payload["allowed"])
        self.assertIn("official_state_requires_protected_host", payload["reason_codes"])

    def test_external_version_requires_host_but_is_not_treated_as_send(self):
        result, payload = _run(
            "--business-mode",
            "letter",
            "--data-scope",
            "public_only",
            "--requested-outcome",
            "external_version",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(payload["execution_profile"], "blocked_host_required")
        self.assertNotIn("direct_external_send", payload["reason_codes"])
        self.assertNotIn("response_sections", payload)

    def test_profile_decision_is_stable_across_three_runs(self):
        outputs = []
        for _ in range(3):
            result, payload = _run(
                "--business-mode",
                "briefing",
                "--data-scope",
                "public_only",
                "--requested-outcome",
                "draft",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(payload)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_public_draft_budget_is_mode_specific_and_never_delegates(self):
        expected_limits = {
            "briefing": (6, 3, 5),
            "standard_visit": (12, 6, 10),
            "strategic_account": (18, 9, 15),
        }
        for mode, (tool_calls, searches, sources) in expected_limits.items():
            with self.subTest(mode=mode):
                result, payload = _run(
                    "--business-mode",
                    mode,
                    "--data-scope",
                    "public_only",
                    "--requested-outcome",
                    "draft",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload["research_budget"]["public_tool_calls_max"], tool_calls)
                self.assertEqual(payload["research_budget"]["public_searches_max"], searches)
                self.assertEqual(payload["research_budget"]["direct_sources_target_max"], sources)
                self.assertEqual(payload["research_budget"]["delegated_workers_max"], 0)
                self.assertFalse(payload["research_stop_contract"]["delegate_research"])
                self.assertTrue(
                    payload["research_stop_contract"]["validation_after_last_edit_required"]
                )


if __name__ == "__main__":
    unittest.main()
