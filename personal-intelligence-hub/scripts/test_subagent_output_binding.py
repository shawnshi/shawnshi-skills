import contextlib
import io
import json
import unittest
from unittest.mock import patch

import review_handoff
from run_contract import RunContractError, validate_subagent_output_options


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
