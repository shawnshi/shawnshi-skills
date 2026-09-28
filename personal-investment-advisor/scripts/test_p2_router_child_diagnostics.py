"""Regression tests: the router must not discard a child's structured reason.

Before this guard, a child that failed a business contract and wrote its precise
error to stdout (scenario analyzer: ``weight_snapshot.source_locator must be a
public HTTP(S) URL, registered SEC identifier, or controlled dataset URI``) was
reported as ``child did not publish a new JSON output file`` with the cause
dropped, because only stderr was forwarded.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
from status_contract import STATUS_FAILED  # noqa: E402

POSITIONS = {
    "positions": [
        {"symbol": "AAA", "quantity": 10, "avg_cost": 1.0, "currency": "CNY",
         "market": "CN", "asset_type": "stock"},
        {"symbol": "CASH_CNY", "quantity": 100, "avg_cost": 1.0, "currency": "CNY",
         "market": "CASH", "asset_type": "cash"},
    ],
    "base_currency": "CNY",
    "exchange_rates": {"CNY": 1.0},
}


def _completed(stdout: str, stderr: str = "", returncode: int = 1):
    completed = subprocess.CompletedProcess(args=["child"], returncode=returncode,
                                            stdout=stdout, stderr=stderr)
    return completed


class ChildFailureDetailTests(unittest.TestCase):
    def test_structured_stdout_errors_are_recovered(self):
        stdout = json.dumps({
            "valid": False,
            "status": "invalid",
            "detail_status": "contract_validation_failed",
            "errors": ["weight_snapshot.fx_source_locator must be a public HTTP(S) URL"],
        })
        details, route_extra = pia._child_failure_details(_completed(stdout))
        self.assertEqual(
            details,
            ["child: weight_snapshot.fx_source_locator must be a public HTTP(S) URL"],
        )
        self.assertEqual(route_extra["child_detail_status"], "contract_validation_failed")
        self.assertEqual(route_extra["child_status"], "invalid")

    def test_nested_result_errors_are_recovered_and_bounded(self):
        stdout = json.dumps({
            "status": "failed",
            "result": {"errors": [f"error-{index}" for index in range(9)]},
        })
        details, _ = pia._child_failure_details(_completed(stdout))
        self.assertEqual(len(details), pia.CHILD_ERROR_EXCERPT_LIMIT)
        self.assertEqual(details[0], "child: error-0")

    def test_non_json_stdout_and_stderr_stay_bounded(self):
        details, route_extra = pia._child_failure_details(
            _completed("plain text output", "traceback line\nline two\n")
        )
        self.assertEqual(details, [])
        self.assertIn("traceback line", route_extra["child_stderr_excerpt"])

    def test_malformed_and_cyclic_stdout_never_raise(self):
        for stdout in ("{not json", "[1, 2, 3]", "", "null"):
            with self.subTest(stdout=stdout):
                details, route_extra = pia._child_failure_details(_completed(stdout))
                self.assertEqual(details, [])
                self.assertNotIn("child_status", route_extra)


class RouterChildReasonTests(unittest.TestCase):
    def _write_inputs(self, root: Path) -> tuple[Path, Path, Path]:
        positions = root / "positions.json"
        positions.write_text(json.dumps(POSITIONS), encoding="utf-8")
        assumptions = root / "assumptions.json"
        assumptions.write_text(json.dumps({
            "scenario_contract_version": "2.0",
            "base_currency": "CNY",
            "weight_snapshot": {
                "as_of": "2026-09-27T00:00:00+00:00",
                "source": "test fixture",
                "source_locator": "local-artifact:not-a-registered-locator",
                "retrieved_at": "2026-09-27T00:00:00+00:00",
                "content_sha256": "0" * 64,
                "valuation_basis": "base_currency_market_value",
                "market_values_base_currency": {"AAA": 100.0, "CASH_CNY": 100.0},
            },
            "scenarios": [{
                "name": "fixture",
                "assumption_source": "test fixture",
                "asset_returns": {
                    "AAA": {"basis": "local_total_return", "return": -0.1, "currency": "CNY"},
                    "CASH_CNY": {"basis": "local_total_return", "return": 0.0, "currency": "CNY"},
                },
                "fx_returns": {},
                "cost_model": {"default": {"transaction_cost_bps": 0, "assumed_turnover": 0}},
            }],
        }), encoding="utf-8")
        return positions, assumptions, root / "scenario_out.json"

    def test_failed_child_reason_reaches_the_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            positions, assumptions, output = self._write_inputs(root)
            envelope, exit_code = pia._run_child(
                public_command="scenario",
                script_name="portfolio_scenario_analyzer.py",
                child_arguments=[str(positions), str(assumptions), "--output", str(output)],
                completion_scope="test",
                output_mode="json_file",
                required_output=output,
            )
        self.assertEqual(envelope["status"], STATUS_FAILED)
        self.assertEqual(envelope["detail_status"], "json_output_file_not_verified")
        self.assertEqual(exit_code, 3)
        child_errors = [error for error in envelope["errors"] if error.startswith("child: ")]
        self.assertTrue(
            child_errors,
            f"child structured reason missing: {envelope['errors']}",
        )
        self.assertIn("source_locator", " ".join(child_errors))
        self.assertEqual(envelope["route"]["shell"], False)

    def test_missing_child_stdout_keeps_the_generic_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "never_written.json"
            with mock.patch.object(
                pia, "_execute_child",
                return_value=_completed("", "", returncode=2),
            ):
                envelope, _ = pia._run_child(
                    public_command="scenario",
                    script_name="portfolio_scenario_analyzer.py",
                    child_arguments=["a", "b"],
                    completion_scope="test",
                    output_mode="json_file",
                    required_output=output,
                )
        self.assertEqual(envelope["detail_status"], "json_output_file_not_verified")
        self.assertFalse([error for error in envelope["errors"] if error.startswith("child: ")])
        self.assertIn("did not publish", " ".join(envelope["errors"]))


if __name__ == "__main__":
    unittest.main()
