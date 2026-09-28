"""Contract tests for the deterministic run report renderer (P2-2).

The renderer must format only what the artifacts contain, name every missing
artifact as a gap, and produce byte-identical output for the same input.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_report  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


class ReportTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run-a"
        (self.run_dir / "out").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def seed_full_run(self) -> None:
        write_json(self.run_dir / "out" / "daily_run_summary.json", {
            "status": "complete", "detail_status": "daily_run_complete",
            "evaluation_epoch": 1790481509.0, "generated_at": "2026-09-27T02:05:09+00:00",
            "positions_input_sha256": "a" * 64,
            "stages": [{"stage": "refresh", "status": "complete", "detail_status": "ok",
                        "exit_code": 0, "artifacts": ["inputs/positions_fx_snapshot.json"]},
                       {"stage": "watchlist", "status": "complete",
                        "detail_status": "boundaries_evaluated", "exit_code": 0,
                        "artifacts": ["out/watchlist_results.json"],
                        "crossed_boundaries": ["X-down"]}],
        })
        write_json(self.run_dir / "out" / "weights.json", {
            "status": "complete", "evaluation_epoch": 1790481509.0,
            "current_weights": [
                {"symbol": "Y", "current_weight": 0.2, "market_value_base": 200.0,
                 "currency": "CNY", "quote": {"as_of": "2026-09-24T07:00:00Z"}},
                {"symbol": "X", "current_weight": 0.7, "market_value_base": 700.0,
                 "currency": "CNY", "quote": {"as_of": "2026-09-24T07:00:00Z"}},
                {"symbol": "CASH_CNY", "current_weight": 0.1, "market_value_base": 100.0,
                 "currency": "CNY", "quote": {"as_of": "2026-09-24T07:00:00Z"}},
            ],
        })
        write_json(self.run_dir / "out" / "watchlist_results.json", {
            "X": {"status": "ok", "detail_status": "complete",
                  "categories": {"downside_boundary_crossed": ["X-down"]}},
            "Y": {"status": "insufficient_evidence", "detail_status": "thresholds_undefined",
                  "categories": {}},
        })
        write_json(self.run_dir / "out" / "quotes.json", {
            "records": [{}, {}],
            "portfolio_batch_audit": {
                "requested_count": 2, "result_record_count": 2, "portfolio_matched_count": 2,
                "expected_active_symbols": ["X", "Y"], "coverage_complete": True,
                "strict_quote_contract": True,
                "quote_freshness_contracts": {
                    "X": {"market_state": "CLOSED", "quote_age_seconds": 235142.72,
                          "applied_max_age_seconds": 259200.0, "status": "matched"},
                },
            },
        })
        write_json(self.run_dir / "out" / "daily_sync.json", {
            "status": "incomplete", "detail_status": "thesis_red_team_incomplete",
            "completeness": {"complete": True, "coverage_complete": True},
            "errors": ["thesis_red_team_incomplete"],
            "quote_snapshot": [],
        })
        write_json(self.run_dir / "out" / "risk_diagnostic.json", {
            "status": "complete", "detail_status": "partial_risk_diagnostic_computed",
            "observation_window": {"first": "2025-09-26", "last": "2026-09-24",
                                   "common_observations": 233},
            "coverage": {"covered_count": 2, "active_non_cash_count": 3,
                         "covered_share_of_non_cash_value": 0.72,
                         "statement": "limited diagnostic over covered symbols only",
                         "excluded_symbols": [{"symbol": "CASH_CNY", "reason": "cash_excluded"}]},
            "annualized_volatility": {"X": 0.42, "Y": 0.31},
            "risk_contribution_within_subset": {"X": 0.68, "Y": 0.32},
            "base_currency": "CNY",
            "value_coverage": {"equity_covered_share_of_portfolio_value": 0.68,
                                "equity_uncovered_share_of_portfolio_value": 0.24,
                                "unmeasured_cash_share_of_portfolio_value": 0.0,
                                "fx_modelled_cash_share_of_portfolio_value": 0.03,
                                "base_currency_cash_share_of_portfolio_value": 0.05,
                                "unmeasured_share_of_portfolio_value": 0.24},
            "cash_fx_risk": {
                "legs": [{"symbol": "CASH_USD", "pair": "USDCNY",
                           "weight_of_portfolio_value": 0.03,
                           "annualized_fx_volatility": 0.0275,
                           "standalone_weighted_volatility": 0.0008}],
                "base_currency_cash": [{"symbol": "CASH_CNY", "value_base": 40000.0}],
                "unmeasured_cash": [{"symbol": "CASH_HKD", "reason": "no_fx_history"}],
                "measured_legs_combination": {
                    "equity_leg": {"weighted": 0.19},
                    "fx_leg": {"weighted_sum_of_standalone_legs": 0.0008},
                    "assumed_zero_correlation_point_estimate": 0.1902,
                    "correlation_bounds": {"lower": 0.1892, "upper": 0.1908},
                    "excluded_from_this_combination": ["515650.SS"],
                    "statement": "bounds cover measured legs only"},
            },
            "renormalized_weights_within_subset": {"X": 0.6, "Y": 0.4},
        })
        write_json(self.run_dir / "out" / "scenario_result.json", {
            "scenario_results": [{"name": "recession", "portfolio_return_before_cost": -0.20928499,
                                  "portfolio_return_after_cost": -0.20928499}],
            "bucket_policy_results": [{"buckets": [
                {"id": "core", "weight_within_scope": 0.53785554, "target_weight": 0.8,
                 "deviation": -0.26214446}]}],
        })

    def render(self, *extra: str) -> tuple[int, str]:
        argv = ["--run-dir", str(self.run_dir), *extra]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_report.main(argv)
        return code, buffer.getvalue()


class RenderTests(ReportTestCase):
    def test_full_run_renders_every_section(self):
        self.seed_full_run()
        code, text = self.render()
        self.assertEqual(code, 0)
        for heading in ("# 运行报告：run-a", "## 阶段状态", "## 行情覆盖与时效",
                        "## 当前权重", "## 观察边界", "## 情景（如已运行）",
                        "## 风险诊断（部分覆盖）", "## 缺口与制品"):
            self.assertIn(heading, text)
        self.assertIn("601899" if False else "| 1 | X |", text)
        self.assertIn("X-down", text)
        self.assertIn("recession", text)
        self.assertIn("未发现缺失的已知制品", text)

    def test_weights_are_ordered_by_descending_weight(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertLess(text.index("| 1 | X |"), text.index("| 2 | Y |"))
        self.assertLess(text.index("| 2 | Y |"), text.index("| 3 | CASH_CNY |"))

    def test_render_is_deterministic(self):
        self.seed_full_run()
        first = self.render()[1]
        second = self.render()[1]
        self.assertEqual(first, second)
        self.assertEqual(hashlib.sha256(first.encode("utf-8")).hexdigest(),
                         hashlib.sha256(second.encode("utf-8")).hexdigest())

    def test_missing_artifacts_are_named_as_gaps(self):
        write_json(self.run_dir / "out" / "weights.json", {"status": "complete",
                                                          "current_weights": []})
        _code, text = self.render()
        self.assertIn("缺口：缺少 out/quotes.json", text)
        self.assertIn("缺口：缺少 out/daily_run_summary.json 的 stages", text)
        self.assertIn("缺口：缺少 out/watchlist_results.json", text)
        self.assertIn("不等于未越界", text)

    def test_out_writes_file_and_reports_hash(self):
        self.seed_full_run()
        target = Path(self._tmp.name) / "report.md"
        code, payload = self.render("--out", str(target))
        self.assertEqual(code, 0)
        envelope = json.loads(payload)
        self.assertEqual(envelope["detail_status"], "report_rendered")
        self.assertEqual(envelope["missing_artifacts"], [])
        written = target.read_bytes()
        self.assertEqual(envelope["report_sha256"],
                         hashlib.sha256(written).hexdigest())

    def test_missing_run_dir_fails_closed(self):
        argv = ["--run-dir", str(Path(self._tmp.name) / "absent")]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = pia_report.main(argv)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(buffer.getvalue())["detail_status"], "run_dir_missing")


if __name__ == "__main__":
    unittest.main()
