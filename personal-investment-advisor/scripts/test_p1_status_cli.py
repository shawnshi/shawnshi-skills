import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia
from status_contract import (
    CANONICAL_STATUSES,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_INSUFFICIENT_EVIDENCE,
    aggregate_status,
    exit_code_for,
    make_envelope,
    normalize_status,
    status_from_payload,
)


class StatusContractTests(unittest.TestCase):
    def test_native_statuses_map_to_four_public_states(self):
        cases = {
            "ok": STATUS_COMPLETE,
            "pass": STATUS_COMPLETE,
            "incomplete": STATUS_INCOMPLETE,
            "pending": STATUS_INCOMPLETE,
            "insufficient_data": STATUS_INSUFFICIENT_EVIDENCE,
            "not_applicable": STATUS_INSUFFICIENT_EVIDENCE,
            "invalid": STATUS_FAILED,
            "data_error": STATUS_FAILED,
        }
        for native, expected in cases.items():
            with self.subTest(native=native):
                self.assertEqual(normalize_status(native), expected)

    def test_unknown_and_empty_states_fail_closed(self):
        for value in (None, "", "new_unreviewed_state", 7):
            with self.subTest(value=value):
                self.assertEqual(normalize_status(value), STATUS_FAILED)

    def test_exit_codes_are_stable_and_distinct(self):
        self.assertEqual(
            {status: exit_code_for(status) for status in CANONICAL_STATUSES},
            {
                STATUS_COMPLETE: 0,
                STATUS_INCOMPLETE: 1,
                STATUS_INSUFFICIENT_EVIDENCE: 2,
                STATUS_FAILED: 3,
            },
        )

    def test_payload_aggregation_is_conservative(self):
        self.assertEqual(
            status_from_payload([{"status": "ok"}, {"status": "insufficient_data"}], 1),
            STATUS_INSUFFICIENT_EVIDENCE,
        )
        self.assertEqual(
            aggregate_status(["complete", "incomplete", "data_error"]),
            STATUS_FAILED,
        )
        self.assertEqual(status_from_payload({"status": "ok"}, 9), STATUS_FAILED)

    def test_contradictory_success_payloads_fail_closed(self):
        self.assertEqual(
            status_from_payload({"status": "ok", "valid": False}, 0),
            STATUS_FAILED,
        )
        self.assertEqual(
            status_from_payload({"status": "ok", "errors": ["broken"]}, 0),
            STATUS_FAILED,
        )
        self.assertEqual(
            status_from_payload(
                {"status": "ok", "completeness": {"complete": False}}, 0
            ),
            STATUS_INCOMPLETE,
        )

    def test_noncomplete_top_status_still_aggregates_stages_and_completeness(self):
        self.assertEqual(
            status_from_payload(
                {
                    "status": "incomplete",
                    "completeness": {"complete": False},
                    "stages": [
                        {"status": "insufficient_evidence"},
                        {"status": "invalid"},
                    ],
                },
                1,
            ),
            STATUS_FAILED,
        )
        self.assertEqual(
            status_from_payload(
                {
                    "status": "incomplete",
                    "stages": [{"status": "insufficient_data"}],
                },
                1,
            ),
            STATUS_INSUFFICIENT_EVIDENCE,
        )

    def test_invalid_flag_has_priority_over_noncomplete_top_status(self):
        for top_status in ("incomplete", "insufficient_evidence"):
            with self.subTest(top_status=top_status):
                self.assertEqual(
                    status_from_payload(
                        {
                            "status": top_status,
                            "valid": False,
                            "completeness": {"complete": False},
                        },
                        1,
                    ),
                    STATUS_FAILED,
                )

    def test_process_failure_exit_outranks_soft_payload_status(self):
        self.assertEqual(
            status_from_payload({"status": "incomplete"}, 3), STATUS_FAILED
        )
        self.assertEqual(
            status_from_payload({"status": "insufficient_evidence"}, 9),
            STATUS_FAILED,
        )
        self.assertEqual(
            status_from_payload({"status": "incomplete"}, 2), STATUS_FAILED
        )
        self.assertEqual(
            status_from_payload({"status": "insufficient_evidence"}, 2),
            STATUS_INSUFFICIENT_EVIDENCE,
        )

    def test_envelope_never_preserves_an_unknown_status(self):
        envelope = make_envelope(
            command="probe",
            status="future_state",
            detail_status="probe",
        )
        self.assertEqual(envelope["status"], STATUS_FAILED)
        self.assertEqual(envelope["exit_code"], 3)


class StableRouterTests(unittest.TestCase):
    @staticmethod
    def _completed(payload, returncode=0, stderr=""):
        stdout = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def _parse(self, *argv):
        return pia._build_parser().parse_args(list(argv))

    @mock.patch.object(pia.subprocess, "run")
    def test_research_route_keeps_metacharacters_in_one_non_shell_argument(self, run):
        run.return_value = self._completed(
            {"status": "ok", "detail_status": "research_brief_valid"}
        )
        suspicious = "brief.json; Write-Output SHOULD_NOT_RUN"
        envelope, code = pia._dispatch(self._parse("research", suspicious))

        invocation = run.call_args.args[0]
        self.assertEqual(invocation[-1], suspicious)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(Path(invocation[1]).name, "research_brief_gate.py")
        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(code, 0)
        self.assertEqual(envelope["completion_scope"], "research_brief_validation")

    @mock.patch.object(pia.subprocess, "run")
    def test_screen_business_fail_is_a_completed_screen_not_router_failure(self, run):
        run.return_value = self._completed([{"symbol": "ABC", "status": "fail"}])
        args = self._parse("screen", "--tickers", "ABC", "--profile", "quality_us")
        envelope, code = pia._dispatch(args)

        invocation = run.call_args.args[0]
        self.assertIn("--format", invocation)
        self.assertEqual(invocation[invocation.index("--format") + 1], "json")
        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(envelope["detail_status"], "screen_completed")
        self.assertEqual(code, 0)

    @mock.patch.object(pia.subprocess, "run")
    def test_screen_missing_evidence_uses_evidence_exit_code(self, run):
        run.return_value = self._completed(
            [{"symbol": "ABC", "status": "insufficient_evidence"}],
            returncode=1,
        )
        args = self._parse("screen", "--tickers", "ABC", "--profile", "quality_us")
        envelope, code = pia._dispatch(args)
        self.assertEqual(envelope["status"], STATUS_INSUFFICIENT_EVIDENCE)
        self.assertEqual(code, 2)

    @mock.patch.object(pia.subprocess, "run")
    def test_daily_sync_preserves_incomplete_without_claiming_completion(self, run):
        run.return_value = self._completed(
            {"status": "incomplete", "errors": ["thesis_red_team_incomplete"]},
            returncode=1,
        )
        args = self._parse(
            "daily-sync",
            "--positions-file",
            "positions.json",
            "--quotes-file",
            "quotes.json",
            "--thesis-evidence-file",
            "evidence.json",
        )
        envelope, code = pia._dispatch(args)
        invocation = run.call_args.args[0]
        self.assertIn("--thesis-evidence-file", invocation)
        self.assertEqual(
            invocation[invocation.index("--thesis-evidence-file") + 1],
            "evidence.json",
        )
        self.assertEqual(envelope["status"], STATUS_INCOMPLETE)
        self.assertEqual(code, 1)

    @mock.patch.object(pia.subprocess, "run")
    def test_scenario_route_uses_only_the_fixed_analyzer_and_explicit_args(self, run):
        run.return_value = self._completed(
            {"status": "ok", "detail_status": "scenario_analysis_valid", "valid": True}
        )
        args = self._parse(
            "scenario",
            "portfolio.json",
            "assumptions.json",
        )
        envelope, code = pia._dispatch(args)
        invocation = run.call_args.args[0]
        self.assertEqual(Path(invocation[1]).name, "portfolio_scenario_analyzer.py")
        self.assertEqual(
            invocation[2:],
            ["portfolio.json", "assumptions.json"],
        )
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(code, 0)

    @mock.patch.object(pia.subprocess, "run")
    def test_scenario_output_route_reads_new_json_file_instead_of_stdout(self, run):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            output = Path(tmpdir) / "scenario.json"

            def write_output(*_args, **_kwargs):
                output.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "valid": True,
                            "detail_status": "scenario_analysis_valid",
                        }
                    ),
                    encoding="utf-8",
                )
                return self._completed("", returncode=0)

            run.side_effect = write_output
            envelope, code = pia._dispatch(
                self._parse(
                    "scenario",
                    "portfolio.json",
                    "assumptions.json",
                    "--output",
                    str(output),
                )
            )

        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(envelope["result"]["detail_status"], "scenario_analysis_valid")
        self.assertEqual(code, 0)

    @mock.patch.object(pia.subprocess, "run")
    def test_scenario_output_cannot_resolve_to_an_input(self, run):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            portfolio = Path(tmpdir) / "portfolio.json"
            assumptions = Path(tmpdir) / "assumptions.json"
            portfolio.write_text('{"positions": []}', encoding="utf-8")
            assumptions.write_text("{}", encoding="utf-8")
            original = portfolio.read_bytes()

            envelope, code = pia._dispatch(
                self._parse(
                    "scenario",
                    str(portfolio),
                    str(assumptions),
                    "--output",
                    str(portfolio),
                )
            )

            self.assertEqual(portfolio.read_bytes(), original)
        run.assert_not_called()
        self.assertEqual(envelope["status"], STATUS_FAILED)
        self.assertEqual(envelope["detail_status"], "output_path_conflicts_with_input")
        self.assertEqual(code, 3)

    @mock.patch.object(pia.subprocess, "run")
    def test_portfolio_audit_discloses_position_context_only(self, run):
        run.return_value = self._completed(
            {
                "portfolio_context": {"position_status": "matched"},
                "portfolio_summary": {},
                "portfolio_risk": {},
                "portfolio_fit": {},
            }
        )
        args = self._parse(
            "portfolio-audit", "ABC", "--positions-file", "positions.json"
        )
        envelope, code = pia._dispatch(args)
        self.assertEqual(envelope["status"], STATUS_INCOMPLETE)
        self.assertEqual(envelope["detail_status"], "position_context_only")
        self.assertEqual(code, 1)
        self.assertTrue(envelope["limitations"])

    @mock.patch.object(pia.subprocess, "run")
    def test_calibrate_requires_a_verified_output_file(self, run):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            output = Path(tmpdir) / "calibration.md"

            def write_report(*_args, **_kwargs):
                output.write_text("report\n", encoding="utf-8")
                return self._completed("report written", returncode=0)

            run.side_effect = write_report
            args = self._parse("calibrate", "--output-path", str(output))
            envelope, code = pia._dispatch(args)

        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(envelope["detail_status"], "report_written")
        self.assertEqual(code, 0)

    @mock.patch.object(pia.subprocess, "run")
    def test_calibration_output_cannot_resolve_to_the_journal(self, run):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            journal.write_text("{}\n", encoding="utf-8")
            original = journal.read_bytes()
            envelope, code = pia._dispatch(
                self._parse(
                    "calibrate",
                    "--journal-path",
                    str(journal),
                    "--output-path",
                    str(journal),
                )
            )
            self.assertEqual(journal.read_bytes(), original)
        run.assert_not_called()
        self.assertEqual(envelope["status"], STATUS_FAILED)
        self.assertEqual(envelope["detail_status"], "output_path_conflicts_with_input")
        self.assertEqual(code, 3)

    def test_calibration_child_cannot_overwrite_the_journal(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            journal = Path(tmpdir) / "journal.jsonl"
            journal.write_text("{}\n", encoding="utf-8")
            original = journal.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "decision_outcome_report.py"),
                    "--journal-path",
                    str(journal),
                    "--output-path",
                    str(journal),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(journal.read_bytes(), original)

    @mock.patch.object(pia.subprocess, "run")
    def test_validate_dashboard_always_uses_current_strict_contract(self, run):
        run.return_value = self._completed(
            {"status": "ok", "detail_status": "dashboard_contract_valid"}
        )
        envelope, code = pia._dispatch(
            self._parse("validate", "dashboard", "dashboard.json")
        )
        invocation = run.call_args.args[0]
        self.assertEqual(Path(invocation[1]).name, "dashboard_gate.py")
        self.assertIn("--strict-current-contract", invocation)
        self.assertEqual(envelope["status"], STATUS_COMPLETE)
        self.assertEqual(code, 0)

    @mock.patch.object(pia.subprocess, "run")
    def test_unknown_child_status_fails_closed(self, run):
        run.return_value = self._completed(
            {"status": "new_unreviewed_state", "detail_status": "new"}
        )
        envelope, code = pia._dispatch(self._parse("research", "brief.json"))
        self.assertEqual(envelope["status"], STATUS_FAILED)
        self.assertEqual(code, 3)

    def test_actual_malformed_research_input_is_wrapped_as_failed(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("PIA_TEST_TMPDIR")) as tmpdir:
            malformed = Path(tmpdir) / "brief.json"
            malformed.write_text("{", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "pia.py"), "research", str(malformed)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(payload["status"], STATUS_FAILED)
        self.assertEqual(payload["result"]["status"], "data_error")

    def test_cli_usage_error_is_json_and_failed(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "pia.py"), "screen"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(payload["status"], STATUS_FAILED)
        self.assertEqual(payload["detail_status"], "cli_usage_error")


if __name__ == "__main__":
    unittest.main()
