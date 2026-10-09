import contextlib
import io
import json
import unittest
from unittest.mock import patch

import review_handoff
import supplement_agent
from run_contract import RunContractError, bind_subagent_launch_options, validate_subagent_output_options


class SubagentOutputBindingTests(unittest.TestCase):
    def setUp(self):
        self.packet = {"subagent_options": {"output": False}}

    def test_native_options_are_forwarded_without_rerouting_and_are_copied(self):
        options = {"agent": "delegate", "output": False, "toolBudget": {"hard": 10}}
        checked = validate_subagent_output_options(self.packet, options)
        self.assertEqual(checked, options)
        checked["toolBudget"]["hard"] = 1
        self.assertEqual(options["toolBudget"]["hard"], 10)

    def test_missing_and_file_based_runtime_outputs_are_refused(self):
        for options in (None, [], {}, {"output": True}, {"output": None},
                        {"output": 0}, {"output": ""},
                        {"output": "registered.draft.json"},
                        {"output": "managed-artifacts/registered.draft.json"}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(RunContractError, "explicitly false"):
                    validate_subagent_output_options(self.packet, options)

    def test_file_only_mode_is_refused_even_with_output_false(self):
        with self.assertRaisesRegex(RunContractError, "file-only"):
            validate_subagent_output_options(
                self.packet, {"output": False, "outputMode": "file-only"}
            )

    def test_packet_cannot_weaken_output_binding(self):
        for binding in (None, {}, {"output": 0}, {"output": True},
                        {"output": "draft.json"}, {"output": False, "path": "draft.json"}):
            with self.subTest(binding=binding):
                with self.assertRaisesRegex(RunContractError, "packet must bind"):
                    validate_subagent_output_options(
                        {"subagent_options": binding}, {"output": False}
                    )

    def test_launch_adapter_binds_native_pi_options(self):
        packet = {
            **self.packet,
            "execution_budget": {"max_duration_seconds": 600},
            "finalization": {"grace_seconds": 900},
            "usage_budget": {"tokens": 150000, "cost_usd": 0.5},
            "tool_budget": {"soft": 20, "hard": 28, "block": "*"},
        }
        checked = bind_subagent_launch_options(packet, {"agent": "worker", "output": False})
        self.assertEqual(checked["timeoutMs"], 1500000)
        self.assertEqual(checked["usageBudget"], {"tokens": {"hard": 150000}, "costUsd": {"hard": 0.5}})
        self.assertEqual(checked["toolBudget"], packet["tool_budget"])
        self.assertIs(checked["async"], True)
        self.assertEqual(checked["context"], "fresh")
        checked["toolBudget"]["hard"] = 1
        self.assertEqual(packet["tool_budget"]["hard"], 28)

    def test_launch_adapter_rejects_drift_and_snake_case(self):
        packet = {**self.packet, "timeout_ms": 900000,
                  "usage_budget": {"tokens": 200000, "cost_usd": 0.5}}
        for drift in ({"timeout_ms": 900000}, {"tool_budget": {"hard": 10}},
                      {"timeoutMs": 1}, {"async": False}, {"context": "fork"},
                      {"usageBudget": {"tokens": {"hard": 1}}}):
            with self.subTest(drift=drift), self.assertRaises(RunContractError):
                bind_subagent_launch_options(packet, {"output": False, **drift})
        with self.assertRaisesRegex(RunContractError, "positive timeout"):
            bind_subagent_launch_options(self.packet, {"output": False})

    def test_launch_adapter_refuses_composite_management_and_timeout_aliases(self):
        packet = {**self.packet, "timeout_ms": 900000,
                  "usage_budget": {"tokens": 200000, "cost_usd": 0.5}}
        task = {"agent": "worker", "task": "process the registered gap"}
        rejected = (
            {"chain": [{"parallel": [task, task]}]},
            {"tasks": [task, task]}, {"parallel": [task, task]},
            {"workflow": True}, {"workflow": "review"},
            {"action": "list"}, {"action": "resume"}, {"resume": "old-run"},
            {"id": "old-run"}, {"runId": "old-run"}, {"run_id": "old-run"},
            {"maxRuntimeMs": 1}, {"maxRuntimeMs": 900000},
            {"gate": "echo fixture"}, {"futureLaunchMode": "parallel"},
        )
        for extra in rejected:
            with self.subTest(extra=extra), self.assertRaisesRegex(RunContractError, "unsupported fields"):
                bind_subagent_launch_options(packet, {"output": False, **extra})

    def test_dispatch_preflights_refuse_composite_shape_before_lifecycle_work(self):
        packet = {**self.packet, "timeout_ms": 900000,
                  "usage_budget": {"tokens": 200000, "cost_usd": 0.5}}
        options = {"output": False, "tasks": [{"agent": "worker", "task": "same gap"}] * 2}
        with patch.object(supplement_agent, "_load_bound_packet", return_value=(None, {}, packet, None, None, None)):
            with self.assertRaisesRegex(RunContractError, "unsupported fields"):
                supplement_agent.preflight_launch("request.json", "gap", options)
        with patch.object(review_handoff, "load", return_value=({}, "sha")), \
                patch.object(review_handoff, "registered", return_value=({}, packet, {}, "sha")), \
                patch.object(review_handoff, "live") as live:
            with self.assertRaisesRegex(RunContractError, "unsupported fields"):
                review_handoff.preflight("request.json", options)
            live.assert_not_called()
        red_request = {"review_kind": "red_team", "reviewer_id": "RedTeam",
                       "deterministic_fast_path": False, "execution_packet": packet}
        with patch.object(review_handoff, "load", return_value=(red_request, "sha")):
            with self.assertRaisesRegex(RunContractError, "unsupported fields"):
                review_handoff.preflight_red_team("request.json", options)

    def test_single_child_identity_and_native_scalars_are_preserved(self):
        packet = {**self.packet, "timeout_ms": 900000,
                  "usage_budget": {"tokens": 200000, "cost_usd": 0.5}}
        options = {"output": False, "agent": "worker", "task": "registered task",
                   "model": "openai-codex/gpt-6.1-sol", "cwd": "frozen/run",
                   "outputMode": "inline", "artifacts": True,
                   "includeProgress": False, "chatProgress": "off"}
        checked = bind_subagent_launch_options(packet, options)
        self.assertTrue(all(checked[key] == value for key, value in options.items()))
        self.assertEqual(checked["timeoutMs"], 900000)
        for invalid in ({"agent": ""}, {"task": {}}, {"model": None}, {"cwd": 1},
                        {"async": 1}, {"artifacts": 0}, {"includeProgress": None},
                        {"outputMode": "unknown"}, {"chatProgress": "live-card"},
                        {"chatProgress": {}}):
            with self.subTest(invalid=invalid), self.assertRaises(RunContractError):
                bind_subagent_launch_options(packet, {"output": False, **invalid})

    def test_review_cli_requires_actual_launch_options_before_loading_request(self):
        stdout = io.StringIO()
        with patch("sys.argv", ["review_handoff.py", "preflight", "--request", "absent.json"]), \
                patch.object(review_handoff, "preflight") as execute, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(review_handoff.main(), 2)
        execute.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "refused")
        self.assertIn("--launch-options", result["error"])


if __name__ == "__main__":
    unittest.main()
