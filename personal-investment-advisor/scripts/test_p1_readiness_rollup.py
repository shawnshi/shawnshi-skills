"""Readiness roll-up: a run's artifacts decide readiness, and its gaps stay named."""

from __future__ import annotations

import io
import json
import contextlib
import tempfile
import unittest
from pathlib import Path

import pia_readiness
import pia_report


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ReadinessRollupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "20260930T0900CST-ready"
        self.addCleanup(self._tmp.cleanup)
        (self.run_dir / "out").mkdir(parents=True)

    def summary(self, **overrides) -> dict:
        payload = {
            "schema_version": "pia_daily_run_summary_v1",
            "status": "complete",
            "detail_status": "daily_sync_with_thesis_complete",
            "decision_scope": "advisory",
            "generated_at": "2026-09-30T09:00:00+08:00",
            "evaluation_epoch": 1800000000.0,
            "stages": [{"name": "quotes", "status": "complete"}],
            "run_inventory": {"requested_stages": ["refresh", "quotes"],
                              "stages_not_run": []},
            "status_consistency": {"consistent": True, "top_status": "complete",
                                   "derived_status": "complete"},
            "residual_unknowns": [
                {"kind": "account_rules_not_verified", "statement": "账户规则未核验"},
                {"kind": "cost_model_not_sourced", "statement": "成本模型未取源"},
            ],
        }
        payload.update(overrides)
        return payload

    def seed(self, *, summary=None, quotes=None, with_thesis=True,
             with_gate=True, scope_override=None) -> None:
        write_json(self.run_dir / "out" / "daily_run_summary.json",
                   self.summary() if summary is None else summary)
        base_quotes = {
            "status": "complete",
            "records": [{"symbol": "601899.SS"}, {"symbol": "GOOG"}],
            "provider_receipt": {"provider": "yfinance", "operation": "daily_sync_quote_metadata",
                                 "outcomes": {"601899.SS": "ok", "GOOG": "ok"},
                                 "outcome_counts": {"ok": 2}},
            "portfolio_batch_audit": {
                "coverage_complete": True,
                "quote_freshness_contracts": {
                    "601899.SS": {"market_state": "REGULAR"},
                    "GOOG": {"market_state": "REGULAR"},
                },
            },
        }
        write_json(self.run_dir / "out" / "quotes.json",
                   base_quotes if quotes is None else quotes)
        if with_thesis:
            write_json(self.run_dir / "out" / "daily_sync_with_thesis.json", {
                "status": "complete", "decision_scope": scope_override or "advisory",
                "thesis_red_team": {"status": "complete", "evidence_status": "ok",
                                    "fatal_event_status": "no_condition_due_yet"},
            })
        if with_gate:
            write_json(self.run_dir / pia_report.READINESS_ARTIFACT, {
                "status": "complete",
                "detail_status": "input_terms_feasible_under_supplied_snapshots",
                "actionability": "human_review_required_no_order",
            })

    def rollup(self, *extra: str) -> tuple[int, dict]:
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_readiness.main(["--run-dir", str(self.run_dir), *extra])
        return code, json.loads(captured.getvalue())

    def test_a_fully_evidenced_run_is_ready_only_for_human_review(self):
        self.seed()
        code, payload = self.rollup()
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ready_for_human_review")
        self.assertEqual(payload["detail_status"],
                         "machine_prerequisites_verified_human_gates_pending")
        self.assertEqual(payload["decision_scope"], "advisory")
        self.assertEqual(payload["blockers"], [])
        self.assertEqual(payload["human_gates"],
                         ["账户规则与成本模型已由一手来源核验"])
        self.assertTrue(all(row["verified"] is True
                            for row in payload["machine_prerequisites"]))
        self.assertNotIn("账户规则与成本模型已由一手来源核验",
                         [row["prerequisite"] for row in payload["machine_prerequisites"]])
        self.assertIs(payload["non_executable"], True)
        self.assertIn("human_review_required_no_order", payload["statement"])

    def test_the_rollup_can_be_written_without_touching_the_run(self):
        self.seed()
        target = Path(self._tmp.name) / "rollup" / "readiness.json"
        before = (self.run_dir / "out" / "daily_run_summary.json").read_bytes()
        code, payload = self.rollup("--out", str(target))
        self.assertEqual(code, 0)
        self.assertEqual(payload["rollup_file"], str(target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["run_id"],
                         self.run_dir.name)
        self.assertEqual((self.run_dir / "out" / "daily_run_summary.json").read_bytes(), before)
        self.assertFalse((self.run_dir / "out" / "readiness.json").exists())

    def test_an_unevaluated_thesis_blocks_readiness_and_is_named(self):
        self.seed(with_thesis=False)
        code, payload = self.rollup()
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["detail_status"], "actionable_prerequisites_unmet")
        self.assertIn("unmet machine prerequisite: Thesis 已评估（evidence_status=ok）"
                      " [未发现 thesis_red_team]", payload["blockers"])
        thesis_row = next(row for row in payload["machine_prerequisites"]
                          if row["prerequisite"].startswith("Thesis"))
        self.assertIsNone(thesis_row["verified"])

    def test_a_failed_provider_symbol_blocks_readiness(self):
        quotes = {
            "records": [{"symbol": "688002.SS"}],
            "provider_receipt": {"provider": "yfinance",
                                 "outcomes": {"688002.SS": "error"},
                                 "outcome_counts": {"ok": 1, "error": 1}},
            "portfolio_batch_audit": {
                "coverage_complete": True,
                "quote_freshness_contracts": {"688002.SS": {"market_state": "REGULAR"}},
            },
        }
        self.seed(quotes=quotes)
        code, payload = self.rollup()
        self.assertEqual(code, 2)
        provider_row = next(row for row in payload["machine_prerequisites"]
                            if row["prerequisite"].startswith("provider"))
        self.assertIs(provider_row["verified"], False)
        self.assertIn("outcome_counts=", provider_row["evidence"])

    def test_a_closed_market_row_explains_itself(self):
        quotes = {
            "records": [{"symbol": "GOOG"}],
            "provider_receipt": {"outcome_counts": {"ok": 1}},
            "portfolio_batch_audit": {
                "coverage_complete": True,
                "quote_freshness_contracts": {"GOOG": {"market_state": "CLOSED"}},
            },
        }
        self.seed(quotes=quotes)
        code, payload = self.rollup()
        self.assertEqual(code, 2)
        session_row = next(row for row in payload["machine_prerequisites"]
                           if row["prerequisite"].startswith("评估时点市场"))
        self.assertIs(session_row["verified"], False)
        self.assertIn("GOOG", session_row["evidence"])

    def test_absent_residual_unknowns_are_a_blocker_not_zero_unknowns(self):
        summary = self.summary()
        summary.pop("residual_unknowns")
        self.seed(summary=summary)
        code, payload = self.rollup()
        self.assertEqual(code, 2)
        self.assertIs(payload["residual_unknowns_declared"], False)
        self.assertIsNone(payload["residual_unknowns"])
        self.assertIn("residual unknowns were not declared by the run", payload["blockers"])

    def test_an_inconsistent_run_status_blocks_readiness(self):
        summary = self.summary(status="complete",
                               status_consistency={"consistent": False,
                                                   "top_status": "complete",
                                                   "derived_status": "failed"})
        self.seed(summary=summary)
        code, payload = self.rollup()
        self.assertEqual(code, 2)
        self.assertIn("run status is inconsistent with its stage statuses", payload["blockers"])

    def test_a_scope_conflict_fails_closed_without_rendering_a_verdict(self):
        self.seed()
        write_json(self.run_dir / "out" / "weights.json",
                   {"evaluation_epoch": 1800000000.0, "decision_scope": "actionable",
                    "current_weights": []})
        code, payload = self.rollup()
        self.assertEqual(code, 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["detail_status"], "decision_scope_conflict")

    def test_a_missing_run_summary_is_an_input_failure(self):
        self.seed()
        (self.run_dir / "out" / "daily_run_summary.json").unlink()
        code, payload = self.rollup()
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "run_summary_missing")

    def test_a_missing_run_directory_is_an_input_failure(self):
        missing = Path(self._tmp.name) / "nope"
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_readiness.main(["--run-dir", str(missing)])
        payload = json.loads(captured.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["detail_status"], "run_dir_missing")


if __name__ == "__main__":
    unittest.main()
