"""Contract tests for ``--output`` on the active-research stages (P2-4).

The stages only printed their result; callers had to redirect stdout, and a
mis-typed redirect could put an error message into a downstream input. The router
now persists the parsed ``result`` for a *complete* stage only, verifies the bytes
it wrote, refuses to overwrite without ``--force``, and never writes onto an input.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
from status_contract import STATUS_COMPLETE, STATUS_INSUFFICIENT_EVIDENCE  # noqa: E402


def envelope(status: str, result=None) -> dict:
    return {"contract_version": "1.1", "command": "portfolio-construct", "status": status,
            "detail_status": "x", "exit_code": 0 if status == STATUS_COMPLETE else 2,
            "completion_scope": "test", "result": result, "errors": [], "limitations": [],
            "route": {"script": "x", "shell": False}}


class WriteResultOutputTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "result.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_complete_envelope_is_written_and_hashed(self):
        written, reason, digest = pia._write_result_output(
            envelope(STATUS_COMPLETE, {"candidate_weight": {"A": 0.5}}), self.output, force=False)
        self.assertTrue(written)
        self.assertIsNone(reason)
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(payload["candidate_weight"], {"A": 0.5})
        import hashlib
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(self.output.with_suffix(".json.tmp").exists())

    def test_incomplete_envelope_is_not_written(self):
        written, reason, digest = pia._write_result_output(
            envelope(STATUS_INSUFFICIENT_EVIDENCE, {"stub": True}), self.output, force=True)
        self.assertFalse(written)
        self.assertEqual(reason, "output_skipped_because_stage_not_complete")
        self.assertIsNone(digest)
        self.assertFalse(self.output.exists())

    def test_existing_output_requires_force(self):
        self.output.write_text("previous", encoding="utf-8")
        written, reason, _ = pia._write_result_output(
            envelope(STATUS_COMPLETE, {"a": 1}), self.output, force=False)
        self.assertFalse(written)
        self.assertEqual(reason, "output_exists_without_force")
        self.assertEqual(self.output.read_text(encoding="utf-8"), "previous")
        written, reason, _ = pia._write_result_output(
            envelope(STATUS_COMPLETE, {"a": 1}), self.output, force=True)
        self.assertTrue(written)
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), {"a": 1})

    def test_output_may_not_be_an_input_file(self):
        source = self.root / "scan.json"
        source.write_text("{}", encoding="utf-8")
        written, reason, _ = pia._write_result_output(
            envelope(STATUS_COMPLETE, {"a": 1}), source, force=True, input_paths=[source])
        self.assertFalse(written)
        self.assertEqual(reason, "output_path_conflicts_with_input")
        self.assertEqual(source.read_text(encoding="utf-8"), "{}")

    def test_route_records_the_write(self):
        result = pia._run_active_stage(
            envelope=envelope(STATUS_COMPLETE, {"a": 1}), code=0,
            output_path=self.output, force=False)
        route = result[0]["route"]
        self.assertTrue(route["result_written"])
        self.assertEqual(route["result_path"], str(self.output))
        self.assertTrue(route["result_sha256"])

    def test_route_records_the_skip_reason(self):
        result = pia._run_active_stage(
            envelope=envelope(STATUS_INSUFFICIENT_EVIDENCE, None), code=2,
            output_path=self.output, force=False)
        self.assertEqual(result[0]["route"]["result_written"], False)
        self.assertEqual(result[0]["route"]["result_skipped_reason"],
                         "output_skipped_because_stage_not_complete")


class DispatchWiringTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "scan.json"
        self.package = self.root / "package.json"
        self.policy = self.root / "policy.json"
        for path in (self.package, self.policy):
            path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_portfolio_construct_writes_the_requested_output(self):
        parser = pia._build_parser()
        args = parser.parse_args(["portfolio-construct", str(self.package),
                                  "--policy-file", str(self.policy),
                                  "--output", str(self.output)])
        completed = (envelope(STATUS_COMPLETE, {"candidate_weight": {"A": 1.0}}), 0)
        with mock.patch.object(pia, "_run_child", return_value=completed):
            result, code = pia._dispatch(args)
        self.assertEqual(code, 0)
        self.assertTrue(result["route"]["result_written"])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")),
                         {"candidate_weight": {"A": 1.0}})

    def test_alpha_validate_without_output_is_unchanged(self):
        parser = pia._build_parser()
        args = parser.parse_args(["alpha-validate", str(self.package),
                                  "--policy-file", str(self.policy)])
        completed = (envelope(STATUS_INSUFFICIENT_EVIDENCE, {"promotion": {}}), 2)
        with mock.patch.object(pia, "_run_child", return_value=completed):
            result, code = pia._dispatch(args)
        self.assertEqual(code, 2)
        self.assertNotIn("result_written", result["route"])
        self.assertFalse((self.root / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
