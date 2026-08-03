import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import test_investment_controls as fixtures
from watchlist_gate import evaluate_watchlist


ALLOWED_STATUSES = {
    "not_applicable",
    "insufficient_evidence",
    "insufficient_data",
    "data_error",
    "invalid",
    "ok",
}


def run_cli(script_name, *arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script_name), *map(str, arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


class CliStatusContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary_root = os.environ.get("PIA_TEST_TMPDIR")

    def assert_status(self, result, expected_status, expected_exit):
        self.assertEqual(result.returncode, expected_exit, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(payload["status"], ALLOWED_STATUSES)
        self.assertEqual(payload["status"], expected_status)
        self.assertIn("detail_status", payload)
        return payload

    def test_dashboard_gate_json_and_exit_code_contract(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as tmpdir:
            valid_path = Path(tmpdir) / "valid.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            malformed_path = Path(tmpdir) / "malformed.json"
            valid_path.write_text(
                json.dumps(fixtures.valid_dashboard(), ensure_ascii=False), encoding="utf-8"
            )
            invalid = fixtures.valid_dashboard()
            invalid["research_mode"] = "trading_mode"
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            malformed_path.write_text("{", encoding="utf-8")

            valid = run_cli("dashboard_gate.py", valid_path)
            invalid_result = run_cli("dashboard_gate.py", invalid_path)
            malformed = run_cli("dashboard_gate.py", malformed_path)

        self.assert_status(valid, "ok", 0)
        self.assert_status(invalid_result, "invalid", 1)
        self.assert_status(malformed, "data_error", 2)

    def test_dashboard_math_gate_json_and_nested_type_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as tmpdir:
            valid_path = Path(tmpdir) / "valid.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            malformed_path = Path(tmpdir) / "malformed.json"
            valid_path.write_text(
                json.dumps(fixtures.valid_dashboard(), ensure_ascii=False), encoding="utf-8"
            )
            invalid = fixtures.valid_dashboard()
            invalid["confidence_details"] = []
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            malformed_path.write_text("{", encoding="utf-8")

            valid = run_cli("dashboard_math_gate.py", valid_path)
            invalid_result = run_cli("dashboard_math_gate.py", invalid_path)
            malformed = run_cli("dashboard_math_gate.py", malformed_path)

        self.assert_status(valid, "ok", 0)
        invalid_payload = self.assert_status(invalid_result, "invalid", 1)
        self.assertTrue(invalid_payload["errors"])
        self.assert_status(malformed, "data_error", 2)

    def test_research_brief_gate_uses_shared_status_vocabulary(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as tmpdir:
            valid_path = Path(tmpdir) / "valid.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            malformed_path = Path(tmpdir) / "malformed.json"
            valid_path.write_text(
                json.dumps(fixtures.valid_brief(), ensure_ascii=False), encoding="utf-8"
            )
            invalid = fixtures.valid_brief()
            invalid["output_contract"]["decision_scope"] = "portfolio_context"
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            malformed_path.write_text("{", encoding="utf-8")

            valid = run_cli("research_brief_gate.py", valid_path)
            invalid_result = run_cli("research_brief_gate.py", invalid_path)
            malformed = run_cli("research_brief_gate.py", malformed_path)

        self.assert_status(valid, "ok", 0)
        self.assert_status(invalid_result, "invalid", 1)
        self.assert_status(malformed, "data_error", 2)

    def test_watchlist_maps_legacy_business_states_to_shared_status(self):
        dashboard = fixtures.valid_dashboard()
        undefined = evaluate_watchlist(dashboard)
        self.assertEqual(undefined["status"], "insufficient_evidence")
        self.assertEqual(undefined["detail_status"], "thresholds_undefined")
        self.assertEqual(undefined["evaluation_status"], "thresholds_undefined")

        dashboard["monitoring_boundaries"] = fixtures.valid_monitoring_boundaries()
        missing_quote = evaluate_watchlist(dashboard)
        self.assertEqual(missing_quote["status"], "insufficient_data")
        self.assertEqual(missing_quote["detail_status"], "runtime_quote_missing")

    def test_malformed_catalyst_map_never_throws_before_dashboard_validation(self):
        for malformed in ([], "not-an-object", {"upcoming": 7}):
            with self.subTest(malformed=malformed):
                dashboard = fixtures.valid_dashboard()
                dashboard["catalyst_map"] = malformed
                report = evaluate_watchlist(dashboard)
                self.assertEqual(report["status"], "invalid")
                self.assertEqual(report["detail_status"], "dashboard_invalid")
                self.assertTrue(report["validation_errors"])

    def test_watchlist_cli_unreadable_and_undefined_statuses(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as tmpdir:
            undefined_path = Path(tmpdir) / "undefined.json"
            malformed_path = Path(tmpdir) / "malformed.json"
            undefined_path.write_text(
                json.dumps(fixtures.valid_dashboard(), ensure_ascii=False), encoding="utf-8"
            )
            malformed_path.write_text("{", encoding="utf-8")

            undefined = run_cli("watchlist_gate.py", undefined_path)
            malformed = run_cli("watchlist_gate.py", malformed_path)

        undefined_payload = self.assert_status(undefined, "insufficient_evidence", 1)
        self.assertEqual(undefined_payload["evaluation_status"], "thresholds_undefined")
        self.assert_status(malformed, "data_error", 2)


if __name__ == "__main__":
    unittest.main()
