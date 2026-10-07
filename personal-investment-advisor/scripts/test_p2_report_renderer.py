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
            "decision_scope": "advisory",
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
            "status": "complete", "decision_scope": "advisory",
            "evaluation_epoch": 1790481509.0,
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
            "provider_receipt": {
                "provider": "yfinance", "operation": "daily_sync_quote_metadata",
                "outcomes": {"X": "ok", "Y": "skipped_circuit_open"},
                "outcome_counts": {"ok": 1, "skipped_circuit_open": 1},
                "circuit_breaker_signature": "curl: (35)",
                "statement": "provider-level receipt only",
            },
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
        write_json(self.run_dir / "out" / "daily_sync_with_thesis.json", {
            "status": "complete", "detail_status": "thesis_evaluated",
            "decision_scope": "advisory",
            "completeness": {"complete": True, "coverage_complete": True},
            "thesis_red_team": {
                "status": "complete", "evidence_status": "ok",
                "fatal_event_status": "no_condition_due_yet",
                "assessment_count": 1, "evidence_count": 3,
                "earliest_due_date": "2027-03-01",
                "fatal_symbols": [], "not_due_symbols": ["X"],
                "window_start": "2026-09-19T00:00:00+08:00",
                "window_end": "2026-09-29T21:20:00+08:00",
                "errors": [], "warnings": [],
                "assessments": [
                    {"symbol": "X", "conclusion": "condition_not_due",
                     "condition_ids": ["X-margin-2027-03-01"],
                     "due_date": "2027-03-01",
                     "evidence_ids": ["ev_a", "ev_b"], "rationale": "not due"},
                ],
            },
        })
        write_json(self.run_dir / "out" / "position_limits.json", {
            "schema_version": "pia_position_limits_v1",
            "decision_scope": "observation_only",
            "generated_from": {"policy": "policy.json", "policy_sha256": "b" * 64,
                               "evaluation_epoch": 1790481500.0},
            "rules": {"max_single_position_weight": 0.3, "max_single_position_loss": 0.15,
                      "upside_cost_multiple": 1.5},
            "positions": [
                {"symbol": "X", "display_label": "X Corp", "current_weight": 0.7,
                 "boundaries": [
                     {"role": "downside_boundary", "value": 85.0},
                     {"role": "upside_boundary", "value": 150.0},
                 ]},
            ],
            "note": "自动派生，仅触发研究复核；不生成订单。",
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
        self.assertIn("## 事件红队（Thesis）", text)
        self.assertIn("致命事件：no_condition_due_yet", text)
        self.assertIn("| X | condition_not_due | 2027-03-01 | 2 |", text)
        self.assertIn("## 仓位限制（策略派生）（制品自带标签：observation_only；非 run 范围）", text)
        self.assertIn("单标的上限 0.3000", text)
        self.assertIn("| X Corp | 0.7000 | 0.3000 | 85.0000 | 150.0000 |", text)
        self.assertIn("| 决策范围 | advisory（来源：daily_run_summary", text)
        self.assertIn("## 阶段状态（制品声明范围：advisory）", text)
        self.assertIn("## 当前权重（制品声明范围：advisory）", text)
        self.assertIn("## 行情覆盖与时效", text)
        self.assertIn("provider 回执：yfinance / daily_sync_quote_metadata", text)
        self.assertIn("- Y：skipped_circuit_open（provider 层未取得元数据，不等于无报价）", text)

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


    def _clear_scope(self, filename):
        """Remove one artifact's scope declaration so a test controls the verdict."""
        path = self.run_dir / "out" / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("decision_scope", None)
        write_json(path, payload)

    def test_undeclared_scope_is_not_inherited_from_the_pipeline_default(self):
        self.seed_full_run()
        summary_path = self.run_dir / "out" / "daily_run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.pop("decision_scope")
        weights_path = self.run_dir / "out" / "weights.json"
        weights = json.loads(weights_path.read_text(encoding="utf-8"))
        weights.pop("decision_scope")
        write_json(summary_path, summary)
        write_json(weights_path, weights)
        self._clear_scope("daily_sync_with_thesis.json")
        target = Path(self._tmp.name) / "report.md"
        code, payload = self.render("--out", str(target))
        self.assertEqual(code, 1)
        envelope = json.loads(payload)
        self.assertEqual(envelope["detail_status"], "decision_scope_unknown")
        self.assertEqual(envelope["decision_scope"], "unknown")
        self.assertTrue(target.is_file())
        self.assertIn("| 决策范围 | unknown（来源：none", target.read_text(encoding="utf-8"))

    def test_conflicting_declared_scopes_fail_closed_without_a_report(self):
        self.seed_full_run()
        weights_path = self.run_dir / "out" / "weights.json"
        weights = json.loads(weights_path.read_text(encoding="utf-8"))
        weights["decision_scope"] = "research_only"
        write_json(weights_path, weights)
        self._clear_scope("daily_sync_with_thesis.json")
        target = Path(self._tmp.name) / "report.md"
        code, payload = self.render("--out", str(target))
        self.assertEqual(code, 3)
        envelope = json.loads(payload)
        self.assertEqual(envelope["detail_status"], "decision_scope_conflict")
        self.assertEqual(envelope["declared_scopes"],
                         {"daily_run_summary": "advisory", "weights": "research_only",
                          "position_limits": "observation_only"})
        self.assertFalse(target.exists())

    def test_unrecognized_scope_value_fails_closed(self):
        self.seed_full_run()
        summary_path = self.run_dir / "out" / "daily_run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["decision_scope"] = "yolo"
        write_json(summary_path, summary)
        code, payload = self.render()
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(payload)["detail_status"], "decision_scope_conflict")
        self.assertIn("decision_scope_unrecognized: yolo", json.loads(payload)["errors"])

    def test_expected_scope_mismatch_fails_closed(self):
        self.seed_full_run()
        code, payload = self.render("--expect-scope", "actionable")
        self.assertEqual(code, 3)
        envelope = json.loads(payload)
        self.assertEqual(envelope["detail_status"], "decision_scope_mismatch")
        self.assertEqual(envelope["resolved_scope"], "advisory")

    def test_rendered_scope_follows_a_non_default_run(self):
        self.seed_full_run()
        for name in ("daily_run_summary.json", "weights.json",
                     "daily_sync_with_thesis.json"):
            path = self.run_dir / "out" / name
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["decision_scope"] = "research_only"
            write_json(path, payload)
        code, text = self.render("--expect-scope", "research_only")
        self.assertEqual(code, 0)
        self.assertIn("| 决策范围 | research_only（来源：daily_run_summary", text)
        self.assertIn("| 制品 | 声明范围 | SHA-256 |", text)
        self.assertIn("| out/weights.json | research_only |", text)
        self.assertIn("| out/quotes.json | undeclared |", text)


    def test_missing_provider_receipt_is_named_as_a_gap(self):
        self.seed_full_run()
        path = self.run_dir / "out" / "quotes.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("provider_receipt")
        write_json(path, payload)
        _code, text = self.render()
        self.assertIn("缺口：未发现 provider 回执（无法区分 provider 故障与真实无数据）", text)


    def test_unassessed_thesis_is_a_gap_not_silence(self):
        self.seed_full_run()
        (self.run_dir / "out" / "daily_sync_with_thesis.json").unlink()
        _code, text = self.render()
        self.assertIn("缺口：未发现 thesis_red_team（本轮未评估事件红队，不得读作已评估无事件）", text)


    def test_artifact_local_scope_label_does_not_fail_the_run(self):
        self.seed_full_run()
        target = Path(self._tmp.name) / "report.md"
        code, payload = self.render("--out", str(target))
        self.assertEqual(code, 0)
        envelope = json.loads(payload)
        self.assertEqual(envelope["scope_annotations"], [
            {"artifact": "position_limits", "declared_scope": "observation_only",
             "note": "artifact-local label, not a run decision scope"},
        ])

    def test_missing_position_limits_is_named_as_a_gap(self):
        self.seed_full_run()
        (self.run_dir / "out" / "position_limits.json").unlink()
        _code, text = self.render()
        self.assertIn("缺口：缺少 out/position_limits.json（无法判定仓位上限与上限边界）", text)


    def test_probe_verdicts_render_and_unproven_are_named(self):
        self.seed_full_run()
        summary_path = self.run_dir / "out" / "daily_run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["stages"].append({
            "stage": "coverage-probe", "status": "complete",
            "detail_status": "coverage_partially_unproven", "exit_code": 0,
            "probes": [
                {"channel": "cninfo_fulltext", "target": "300253.SZ",
                 "control": "002487.SZ", "verdict": "covered",
                 "target_count": 3, "control_count": 2,
                 "official_coverage_ready": True},
                {"channel": "sse_query", "target": "601899.SS", "control": "600000.SS",
                 "verdict": "channel_broken", "target_count": None,
                 "control_count": None, "official_coverage_ready": False},
            ],
            "unproven_probes": ["sse_query 601899.SS: channel_broken"],
        })
        write_json(summary_path, summary)
        code, text = self.render()
        self.assertEqual(code, 0)
        self.assertIn("覆盖探针（如已运行）", text)
        self.assertIn("| cninfo_fulltext | 300253.SZ | 002487.SZ | covered | 3.0000/2.0000 | true |", text)
        self.assertIn("未证明探针（不得当作已覆盖）：", text)
        self.assertIn("sse_query 601899.SS: channel_broken", text)

    def test_residual_unknowns_are_rendered_not_hidden(self):
        self.seed_full_run()
        summary_path = self.run_dir / "out" / "daily_run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["residual_unknowns"] = [
            {"kind": "account_rules_not_verified", "stage": None,
             "detail": "pia never connects to a broker",
             "statement": "交易规则均未经券商渠道核验"},
        ]
        write_json(summary_path, summary)
        _code, text = self.render()
        self.assertIn("残余未知（本轮未建立）", text)
        self.assertIn("| account_rules_not_verified | — | pia never connects to a broker |", text)

    def test_absent_residual_unknowns_is_a_gap_not_an_empty_list(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertIn("缺口：缺少 residual_unknowns", text)

    def test_empty_residual_unknown_list_is_also_a_gap(self):
        self.seed_full_run()
        summary_path = self.run_dir / "out" / "daily_run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["residual_unknowns"] = []
        write_json(summary_path, summary)
        _code, text = self.render()
        self.assertIn("residual_unknowns 为空列表", text)

    def test_actionable_readiness_lists_unverified_prerequisites(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertIn("## 可执行性就绪（actionable）", text)
        # A fixture with a circuit-open provider outcome must not read as ready.
        self.assertIn("| provider 无传输失败/未因熔断跳过 | 未核验 |", text)
        self.assertIn("| 本轮整体状态为 complete | 已核验 |", text)
        self.assertIn("不得读作就绪", text)

    def test_actionable_readiness_names_the_absent_gate_artifact(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertIn("未提供 out/actionability_assessment.json（本轮未运行 gate）", text)

    def test_actionable_readiness_reads_a_supplied_gate_verdict(self):
        self.seed_full_run()
        write_json(self.run_dir / "out" / "actionability_assessment.json", {
            "status": "complete", "detail_status": "input_terms_feasible_under_supplied_snapshots",
            "actionability": "human_review_required_no_order",
        })
        _code, text = self.render()
        self.assertIn("| actionability gate 快照裁决为 complete | 已核验 |", text)
        self.assertIn("human_review_required_no_order", text)
        # Even a passing gate leaves the structural account/cost unknowns unproven.
        self.assertIn("| 账户规则与成本模型已由一手来源核验 | 未提供 |", text)

    def test_absent_probe_stage_says_it_never_ran(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertIn("本轮未运行覆盖探针（未提供探针规格）；不得读作“通道已证明”", text)


class SecondaryQuoteRenderingTests(ReportTestCase):
    """A labelled secondary quote must be visible, never folded into primary coverage."""

    def seed_with_secondary(self):
        self.seed_full_run()
        writer = getattr(self, "write_quotes", None)
        payload = json.loads((self.run_dir / "out" / "quotes.json").read_text(encoding="utf-8"))
        payload["records"] = [
            {"symbol": "X", "data_sources": {"price": "Tencent Finance (secondary)",
                                              "price_locator": "fallback:tencent:X"},
             "quote_provenance": {"tier": "secondary", "symbol": "X",
                                  "source": "Tencent Finance (secondary)",
                                  "source_locator": "fallback:tencent:X",
                                  "observed_at": "2026-09-29T10:16:20-04:00",
                                  "primary_outcome": "error",
                                  "unverifiable": ["quoteType", "timeliness"]}},
            {"symbol": "Y"},
        ]
        write_json(self.run_dir / "out" / "quotes.json", payload)
        self.assertIsNone(writer)

    def test_secondary_quote_gets_its_own_section(self):
        self.seed_with_secondary()
        _code, text = self.render()
        self.assertIn("## 备用行情来源（主源失败后替代）", text)
        self.assertIn("| X | Tencent Finance (secondary) | error | 2026-09-29T10:16:20-04:00 |", text)
        self.assertIn("不计为一次主源成功", text)

    def test_readiness_names_the_substituted_symbols(self):
        self.seed_with_secondary()
        _code, text = self.render()
        self.assertIn("已用标注的备用源替代 1 个标的", text)
        self.assertIn("| provider 无传输失败/未因熔断跳过 | 未核验 |", text)

    def test_absent_secondary_quote_renders_no_section(self):
        self.seed_full_run()
        _code, text = self.render()
        self.assertNotIn("## 备用行情来源", text)
        self.assertNotIn("已用标注的备用源替代", text)


class ReadinessEnvelopeTests(ReportTestCase):
    """The envelope must state readiness in machine-readable form, not only prose."""

    def envelope(self):
        self.seed_full_run()
        out = self.run_dir / "report.md"
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            code = pia_report.main(["--run-dir", str(self.run_dir), "--out", str(out)])
        return code, json.loads(captured.getvalue())

    def test_envelope_lists_unmet_prerequisites(self):
        code, payload = self.envelope()
        self.assertEqual(code, 0)
        readiness = payload["actionable_readiness"]
        self.assertEqual(readiness["scope"], "advisory")
        self.assertEqual(readiness["verdict"], "not_ready")
        self.assertFalse(readiness["gate_artifact_present"])
        self.assertEqual(readiness["prerequisite_count"], len(readiness["prerequisites"]))
        self.assertTrue(any("provider" in item for item in readiness["unmet"]))
        verified = {row["prerequisite"]: row["verified"] for row in readiness["prerequisites"]}
        self.assertIs(verified["行情覆盖闭合"], True)
        self.assertIs(verified["actionability gate 快照裁决为 complete"], None)

    def test_supplied_gate_verdict_is_reflected_in_the_envelope(self):
        self.seed_full_run()
        write_json(self.run_dir / "out" / "actionability_assessment.json", {
            "status": "complete", "detail_status": "input_terms_feasible_under_supplied_snapshots",
            "actionability": "human_review_required_no_order",
        })
        out = self.run_dir / "report.md"
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            pia_report.main(["--run-dir", str(self.run_dir), "--out", str(out)])
        readiness = json.loads(captured.getvalue())["actionable_readiness"]
        self.assertTrue(readiness["gate_artifact_present"])
        gate_row = next(row for row in readiness["prerequisites"]
                        if row["prerequisite"].startswith("actionability gate"))
        self.assertIs(gate_row["verified"], True)
        self.assertNotIn(gate_row["prerequisite"], readiness["unmet"])


if __name__ == "__main__":
    unittest.main()
