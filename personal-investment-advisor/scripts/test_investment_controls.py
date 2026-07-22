import sys
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from advice_journal import build_journal_entry
from dashboard_gate import _validate_evidence_items, validate_dashboard
from decision_outcome_report import calculate_calibration
from instrument_gate import validate_instrument
from live_evidence_probe import probe_us_stock
from management_claim_tracker import evaluate_claims
from portfolio_loader import (
    build_portfolio_fit,
    build_portfolio_risk,
    build_portfolio_summary,
    get_exchange_rate,
    validate_portfolio_payload,
)
from portfolio_scenario_analyzer import analyze_scenarios
from quality_screener import evaluate_metrics
from research_brief_gate import validate_research_brief
from sync_outcomes import build_outcome_update
from yf import extract_catalyst_map


def valid_brief():
    return {
        "research_id": "R-001",
        "instrument": {"symbol": "AAPL", "market": "US", "asset_type": "stock", "currency": "USD"},
        "as_of_date": "2026-07-22",
        "investment_horizon_days": 90,
        "benchmark": {"symbol": "SPY", "market": "US", "currency": "USD"},
        "method_profile": "quality_equity",
        "research_question": "Will earnings revisions exceed consensus?",
        "market_consensus": "Consensus expects stable margins.",
        "core_hypothesis": "Margin expansion is underestimated.",
        "falsification_conditions": ["Gross margin falls below prior-year level"],
        "key_variables": ["gross_margin", "revenue_growth"],
        "source_policy": {
            "cutoff_date": "2026-07-22",
            "allowed_source_tiers": ["company_primary", "audited_filing", "market_data"],
            "primary_source_required": True,
        },
        "output_contract": {
            "decision_scope": "research_only",
            "required_scenarios": ["base", "bull", "bear"],
            "include_counterevidence": True,
            "transaction_cost_bps": 10,
            "dual_trigger_policy": "conservative",
        },
    }


def valid_dashboard():
    evidence = {
        "fact": "Revenue grew 10%",
        "connection": "Demand improved",
        "deduction": "Estimate may rise",
        "source_type": "filing",
        "source_tier": "audited_filing",
        "source_locator": "https://www.sec.gov/Archives/example#p3",
        "published_at": "2026-07-01",
        "retrieved_at": "2026-07-02",
        "as_of_date": "2026-07-22",
        "freshness": "current",
        "confidence": "high",
        "independent_source_count": 1,
    }
    return {
        "stock_name": "Apple",
        "stock_code": "AAPL",
        "market_type": "美股",
        "research_mode": "thesis_mode",
        "sentiment_score": 50,
        "trend_prediction": "震荡",
        "operation_advice": "不适用",
        "decision_type": "research_only",
        "confidence_level": "中",
        "confidence_details": {
            "score": 60,
            "data_quality": "medium",
            "technical_alignment": "neutral",
            "valuation_support": "mixed",
            "actionability": "low",
        },
        "freshness_flags": {
            "price_data_fresh": True,
            "info_data_fresh": True,
            "news_data_fresh": True,
            "portfolio_data_fresh": True,
            "stale_inputs": [],
        },
        "evidence_items": [evidence],
        "dashboard": {
            "core_conclusion": {
                "one_sentence": "Research watch only",
                "signal_type": "fundamental",
                "time_sensitivity": "90d",
                "position_advice": {"has_position": False},
            },
            "qualitative_analysis": {},
            "data_perspective": {
                "trend_status": "neutral",
                "price_position": {"current_price": 100},
                "volume_analysis": "neutral",
                "chip_structure": {"chip_health": "不适用(非A股)"},
                "valuation": "mixed",
                "atr_14": 2.0,
            },
            "intelligence": {},
            "battle_plan": {
                "sniper_points": {"stop_loss": 90, "take_profit": 120},
                "position_strategy": "research only",
                "action_checklist": ["verify filing"],
            },
        },
        "analysis_summary": "summary",
        "risk_warning": "risk",
        "short_term_outlook": "uncertain",
        "medium_term_outlook": "uncertain",
        "search_performed": True,
        "data_sources": {"filing": "https://www.sec.gov/Archives/example"},
        "data_gaps": [],
        "position_direction": "not_applicable",
        "blind_spot_warning": "Consensus may already price the thesis.",
        "research_brief": valid_brief(),
        "earnings_snapshot": {
            "next_earnings_date": "2026-08-01",
            "revenue_growth": 0.1,
            "trailing_pe": 20,
            "forward_pe": 18,
        },
        "catalyst_map": {"upcoming": [], "active": [], "broken": [], "data_gaps": []},
    }


class InstrumentGateTests(unittest.TestCase):
    def test_cn_symbol_is_normalized(self):
        result = validate_instrument("600519", "CN", "stock")
        self.assertTrue(result["valid"])
        self.assertEqual(result["normalized_symbol"], "600519.SS")

    def test_currency_mismatch_fails(self):
        result = validate_instrument("AAPL", "US", "stock", "CNY")
        self.assertFalse(result["valid"])


class LiveEvidenceProbeTests(unittest.TestCase):
    def _fetcher(self, nasdaq_symbol="AAPL", quote_epoch=None):
        quote_epoch = quote_epoch or datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc).timestamp()

        def fetch(url, headers, timeout):
            hostname = urlparse(url).hostname
            if hostname == "query1.finance.yahoo.com":
                payload = {
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "symbol": "AAPL",
                                    "regularMarketTime": quote_epoch,
                                    "regularMarketPrice": 327.74,
                                    "currency": "USD",
                                    "exchangeName": "NMS",
                                }
                            }
                        ]
                    }
                }
            elif hostname == "api.nasdaq.com":
                payload = {
                    "data": {
                        "symbol": nasdaq_symbol,
                        "companyName": "Apple Inc. Common Stock",
                        "exchange": "NASDAQ-GS",
                        "marketStatus": "Closed",
                    }
                }
            elif "company_tickers_exchange" in url:
                payload = {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
                }
            elif "data.sec.gov/submissions" in url:
                payload = {
                    "cik": "0000320193",
                    "name": "Apple Inc.",
                    "tickers": ["AAPL"],
                    "exchanges": ["Nasdaq"],
                    "filings": {
                        "recent": {
                            "form": ["10-Q"],
                            "filingDate": ["2026-05-01"],
                            "accessionNumber": ["0000320193-26-000013"],
                            "primaryDocument": ["aapl-20260328.htm"],
                        }
                    },
                }
            else:
                raise AssertionError(f"unexpected URL: {url}")
            return payload, 200, url

        return fetch

    def test_live_probe_requires_consistent_quote_exchange_and_filing_identity(self):
        result = probe_us_stock(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            fetch_json=self._fetcher(),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["formal_use_allowed"])
        self.assertEqual(result["sources"]["regulator_identity"]["cik"], "0000320193")
        self.assertEqual(result["sources"]["company_disclosures"]["filings"][0]["form"], "10-Q")
        self.assertTrue(all(result["cross_checks"].values()))

    def test_live_probe_fails_closed_on_identity_mismatch(self):
        result = probe_us_stock(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            fetch_json=self._fetcher(nasdaq_symbol="MSFT"),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertFalse(result["valid"])
        self.assertIn("cross-check failed: symbol_match", result["errors"])

    def test_live_probe_rejects_stale_price(self):
        stale = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
        result = probe_us_stock(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            fetch_json=self._fetcher(quote_epoch=stale),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("market price age" in item for item in result["errors"]))


class ResearchBriefTests(unittest.TestCase):
    def test_valid_brief_passes(self):
        self.assertEqual(validate_research_brief(valid_brief()), [])

    def test_missing_falsifier_fails(self):
        brief = valid_brief()
        brief["falsification_conditions"] = []
        self.assertTrue(any("falsification_conditions" in item for item in validate_research_brief(brief)))

    def test_boolean_and_primary_source_policy_fail_closed(self):
        brief = valid_brief()
        brief["source_policy"]["primary_source_required"] = "yes"
        brief["source_policy"]["allowed_source_tiers"] = ["secondary"]
        brief["output_contract"]["include_counterevidence"] = "yes"
        errors = validate_research_brief(brief)
        self.assertTrue(any("primary_source_required must be true" in item for item in errors))
        self.assertTrue(any("must include a primary source tier" in item for item in errors))
        self.assertTrue(any("include_counterevidence must be true" in item for item in errors))


class ManagementClaimTests(unittest.TestCase):
    def test_missing_sources_fail_closed(self):
        result = evaluate_claims({"claims": [{"claim_id": "c1"}]})
        self.assertFalse(result["valid"])

    def test_sourced_claim_is_compared_without_honesty_score(self):
        payload = {
            "test_mode": True,
            "stock_code": "AAPL",
            "as_of_date": "2026-07-22",
            "source_documents": [
                {
                    "document_id": "d1",
                    "source_tier": "company_primary",
                    "source_locator": "https://example.test/filing",
                    "published_at": "2026-01-01",
                    "retrieved_at": "2026-07-22",
                    "text": "Revenue growth will exceed ten percent.",
                },
                {
                    "document_id": "d2",
                    "source_tier": "audited_filing",
                    "source_locator": "https://example.test/result",
                    "published_at": "2026-07-01",
                    "retrieved_at": "2026-07-22",
                    "text": "Revenue grew twelve percent.",
                },
            ],
            "claims": [
                {
                    "claim_id": "c1",
                    "statement": "Revenue growth >= 10%",
                    "metric": "revenue_growth",
                    "operator": ">=",
                    "target": 0.10,
                    "deadline": "2026-06-30",
                    "source_document_id": "d1",
                    "source_locator": "paragraph 3",
                    "actual": 0.12,
                    "actual_source_document_id": "d2",
                    "actual_source_locator": "table 1",
                }
            ],
        }
        result = evaluate_claims(payload)
        self.assertTrue(result["valid"])
        self.assertEqual(result["management_claim_tracking"]["claims"][0]["status"], "met")
        self.assertFalse(result["management_claim_tracking"]["formal_use_allowed"])
        self.assertNotIn("honesty", result["management_claim_tracking"])


class EvidenceAndScreenTests(unittest.TestCase):
    def test_math_gate_cli_returns_nonzero_for_invalid_dashboard(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            valid_path = Path(tmpdir) / "valid.json"
            invalid_path = Path(tmpdir) / "invalid.json"
            malformed_path = Path(tmpdir) / "malformed.json"
            valid_path.write_text(json.dumps(valid_dashboard(), ensure_ascii=False), encoding="utf-8")
            invalid = valid_dashboard()
            invalid["confidence_details"]["score"] = 120
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            malformed_path.write_text("{", encoding="utf-8")
            valid_result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "dashboard_math_gate.py"), str(valid_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            invalid_result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "dashboard_math_gate.py"), str(invalid_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            malformed_result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "dashboard_math_gate.py"), str(malformed_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(valid_result.returncode, 0)
        self.assertEqual(invalid_result.returncode, 1)
        self.assertEqual(malformed_result.returncode, 2)
    def test_full_thesis_dashboard_passes_both_contracts(self):
        self.assertEqual(validate_dashboard(valid_dashboard()), [])

    def test_test_fixture_claims_cannot_enter_formal_dashboard(self):
        dashboard = valid_dashboard()
        dashboard["management_claim_tracking"] = {
            "summary": {"met": 1, "missed": 0, "insufficient_evidence": 0},
            "claims": [{"claim_id": "test"}],
            "assessment_boundary": "claim fulfillment only; no honesty or fraud inference",
            "formal_use_allowed": False,
        }
        self.assertTrue(
            any("not allowed for formal use" in error for error in validate_dashboard(dashboard))
        )

    def test_evidence_requires_ordered_dates_and_locator(self):
        item = {
            "fact": "Revenue grew 10%",
            "connection": "Demand improved",
            "deduction": "Estimate may rise",
            "source_type": "filing",
            "source_tier": "audited_filing",
            "source_locator": "https://www.sec.gov/Archives/example#p3",
            "published_at": "2026-07-01",
            "retrieved_at": "2026-07-02",
            "as_of_date": "2026-07-22",
            "freshness": "current",
            "confidence": "high",
            "independent_source_count": 1,
        }
        self.assertEqual(_validate_evidence_items([item]), [])
        item["retrieved_at"] = "2026-08-01"
        self.assertTrue(any("retrieved_at cannot be after as_of_date" in error for error in _validate_evidence_items([item])))

    def test_reserved_evidence_locator_is_rejected(self):
        item = valid_dashboard()["evidence_items"][0]
        item["source_locator"] = "https://example.test/filing"
        self.assertTrue(any("reserved test locator" in error for error in _validate_evidence_items([item])))

    def test_missing_metric_is_not_a_pass(self):
        profile = {"thresholds": {"roe_avg": {"min": 0.08}, "fcf_sum": {"min_exclusive": 0}}}
        result = evaluate_metrics({"roe_avg": 0.12, "fcf_sum": None}, profile)
        self.assertEqual(result["status"], "insufficient_data")


class PortfolioTests(unittest.TestCase):
    def test_complete_three_scenario_packet_passes(self):
        portfolio = {"base_currency": "USD", "positions": [{"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 1.0}]}
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {"name": "base", "asset_returns": {"AAPL": 0.05}, "assumption_source": "test"},
                {"name": "bull", "asset_returns": {"AAPL": 0.20}, "assumption_source": "test"},
                {"name": "bear", "asset_returns": {"AAPL": -0.20}, "assumption_source": "test"},
            ],
        }
        self.assertTrue(analyze_scenarios(portfolio, assumptions)["valid"])

    def test_duplicate_position_symbol_fails(self):
        portfolio = {
            "base_currency": "USD",
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 0.5},
                {"symbol": "AAPL", "quantity": 2, "avg_cost": 90, "currency": "USD", "current_weight": 0.5},
            ]
        }
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {"name": name, "asset_returns": {"AAPL": 0.0}, "assumption_source": "test"}
                for name in ["base", "bull", "bear"]
            ],
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate position symbol" in item for item in result["errors"]))

    def test_scenario_reports_before_and_after_cost(self):
        portfolio = {"base_currency": "USD", "positions": [{"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 1.0}]}
        assumptions = {
            "base_currency": "USD",
            "transaction_cost_bps": 10,
            "assumed_turnover": 1.0,
            "scenarios": [
                {"name": name, "asset_returns": {"AAPL": 0.1}, "assumption_source": "test"}
                for name in ["base", "bull", "bear"]
            ],
        }
        scenario = analyze_scenarios(portfolio, assumptions)["scenario_results"][0]
        self.assertEqual(scenario["portfolio_return_before_cost"], 0.1)
        self.assertEqual(scenario["portfolio_return_after_cost"], 0.099)

    def test_scenario_rejects_non_finite_values(self):
        portfolio = {"base_currency": "USD", "positions": [{"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": "nan"}]}
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {"name": name, "asset_returns": {"AAPL": "inf"}, "assumption_source": "test"}
                for name in ["base", "bull", "bear"]
            ],
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertFalse(result["valid"])
        self.assertTrue(any("must be finite" in item for item in result["errors"]))

    def test_scenario_rejects_non_positive_position_values(self):
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {"name": name, "asset_returns": {"AAPL": 0.0}, "assumption_source": "test"}
                for name in ["base", "bull", "bear"]
            ],
        }
        for field, value in [("quantity", 0), ("avg_cost", -1), ("current_weight", 0)]:
            with self.subTest(field=field):
                position = {"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 1.0}
                position[field] = value
                result = analyze_scenarios({"base_currency": "USD", "positions": [position]}, assumptions)
                self.assertFalse(result["valid"])
                self.assertTrue(any(field in item and "positive" in item for item in result["errors"]))

    def test_scenario_requires_explicit_return_for_every_symbol(self):
        portfolio = {"base_currency": "USD", "positions": [{"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 0.6}, {"symbol": "CASH", "quantity": 1, "avg_cost": 1, "currency": "USD", "current_weight": 0.4}]}
        assumptions = {"base_currency": "USD", "scenarios": [{"name": "bear", "asset_returns": {"AAPL": -0.2}, "assumption_source": "test"}]}
        result = analyze_scenarios(portfolio, assumptions)
        self.assertFalse(result["valid"])

    def test_liquidity_stays_unknown_without_days_to_liquidate(self):
        positions = [{"symbol": "AAPL", "current_weight": 0.2, "thesis": "quality"}]
        summary = build_portfolio_summary(positions)
        risk = build_portfolio_risk(summary)
        self.assertEqual(risk["liquidity_risk"], "未知")
        fit = build_portfolio_fit(
            {"has_position": True, "weight_status": "within_target"}, summary, risk
        )
        self.assertEqual(fit["eligibility"], "within_weight_constraint")
        self.assertNotIn("action_in_portfolio", fit)

    def test_portfolio_contract_rejects_duplicates(self):
        payload = {
            "base_currency": "USD",
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD"},
                {"symbol": "aapl", "quantity": 2, "avg_cost": 90, "currency": "USD"},
            ],
        }
        self.assertTrue(any("duplicate position symbol" in item for item in validate_portfolio_payload(payload)))

    def test_missing_cross_currency_rate_fails(self):
        with self.assertRaises(ValueError):
            get_exchange_rate("USD", {"base_currency": "CNY", "exchange_rates": {}})


class CatalystAndCalibrationTests(unittest.TestCase):
    def test_missing_news_is_a_gap_not_a_broken_thesis(self):
        result = extract_catalyst_map([], {})
        self.assertEqual(result["broken"], [])
        self.assertTrue(result["data_gaps"])

    def test_fixed_horizon_benchmark_adjusted_return(self):
        entry = {
            "executed": True,
            "execution_price": 100,
            "execution_date": "2026-01-01",
            "execution_timing": "close",
            "investment_horizon_days": 2,
            "benchmark_symbol": "SPY",
            "position_direction": "long",
            "transaction_cost_bps": 10,
        }
        asset = [
            {"Date": "2026-01-01", "High": 101, "Low": 99, "Close": 100},
            {"Date": "2026-01-03", "High": 111, "Low": 109, "Close": 110},
        ]
        benchmark = [
            {"Date": "2026-01-01", "Close": 200},
            {"Date": "2026-01-03", "Close": 204},
        ]
        result = build_outcome_update(entry, asset, benchmark, today=date(2026, 1, 4))
        self.assertTrue(result["calibration_eligible"])
        self.assertAlmostEqual(result["outcome_return_pct"], 10.0)
        self.assertAlmostEqual(result["benchmark_return_pct"], 2.0)
        self.assertAlmostEqual(result["net_excess_return_pct"], 7.9)

    def test_short_return_does_not_reverse_benchmark(self):
        entry = {
            "executed": True,
            "execution_price": 100,
            "execution_date": "2026-01-01",
            "execution_timing": "close",
            "investment_horizon_days": 2,
            "benchmark_symbol": "SPY",
            "position_direction": "short",
            "transaction_cost_bps": 10,
        }
        asset = [
            {"Date": "2026-01-01", "High": 101, "Low": 99, "Close": 100},
            {"Date": "2026-01-03", "High": 91, "Low": 89, "Close": 90},
        ]
        benchmark = [
            {"Date": "2026-01-01", "Close": 200},
            {"Date": "2026-01-03", "Close": 204},
        ]
        result = build_outcome_update(entry, asset, benchmark, today=date(2026, 1, 4))
        self.assertAlmostEqual(result["net_excess_return_pct"], 7.9)

    def test_non_finite_benchmark_price_is_ineligible(self):
        entry = {
            "executed": True,
            "execution_price": 100,
            "execution_date": "2026-01-01",
            "execution_timing": "close",
            "investment_horizon_days": 1,
            "benchmark_symbol": "SPY",
            "position_direction": "long",
            "transaction_cost_bps": 0,
        }
        asset = [{"Date": "2026-01-01", "Close": 100}, {"Date": "2026-01-02", "Close": 101}]
        benchmark = [{"Date": "2026-01-01", "Close": 0}, {"Date": "2026-01-02", "Close": 1}]
        result = build_outcome_update(entry, asset, benchmark, today=date(2026, 1, 3))
        self.assertFalse(result["calibration_eligible"])

    def test_non_positive_stop_price_is_ineligible(self):
        entry = {
            "executed": True,
            "execution_price": 100,
            "execution_date": "2026-01-01",
            "execution_timing": "close",
            "investment_horizon_days": 1,
            "benchmark_symbol": "SPY",
            "position_direction": "long",
            "transaction_cost_bps": 0,
            "stop_loss": -10,
        }
        asset = [{"Date": "2026-01-01", "High": 101, "Low": -20, "Close": 100}]
        benchmark = [{"Date": "2026-01-01", "Close": 100}]
        result = build_outcome_update(entry, asset, benchmark, today=date(2026, 1, 3))
        self.assertFalse(result["calibration_eligible"])
        self.assertIn("stop_loss must be positive", result["calibration_exclusion_reason"])

    def _dual_trigger_case(self):
        entry = {
            "executed": True,
            "execution_price": 100,
            "execution_date": "2026-01-01",
            "execution_timing": "close",
            "investment_horizon_days": 5,
            "benchmark_symbol": "SPY",
            "position_direction": "long",
            "transaction_cost_bps": 0,
            "stop_loss": 90,
            "take_profit": 110,
        }
        asset = [
            {"Date": "2026-01-01", "High": 101, "Low": 99, "Close": 100},
            {"Date": "2026-01-02", "High": 115, "Low": 85, "Close": 105},
        ]
        benchmark = [
            {"Date": "2026-01-01", "Close": 200},
            {"Date": "2026-01-02", "Close": 202},
        ]
        return entry, asset, benchmark

    def test_dual_trigger_uses_intraday_first_trigger(self):
        entry, asset, benchmark = self._dual_trigger_case()
        intraday = [
            {"Date": "2026-01-02T09:30:00-05:00", "High": 105, "Low": 95, "Close": 102},
            {"Date": "2026-01-02T10:00:00-05:00", "High": 111, "Low": 100, "Close": 110},
            {"Date": "2026-01-02T10:30:00-05:00", "High": 108, "Low": 89, "Close": 92},
        ]
        benchmark_intraday = [
            {"Date": "2026-01-02T09:30:00-05:00", "Close": 201},
            {"Date": "2026-01-02T10:00:00-05:00", "Close": 202},
        ]
        result = build_outcome_update(
            entry,
            asset,
            benchmark,
            intraday_history=intraday,
            benchmark_intraday_history=benchmark_intraday,
            today=date(2026, 1, 3),
        )
        self.assertTrue(result["calibration_eligible"])
        self.assertEqual(result["outcome_status"], "Target Reached")
        self.assertEqual(result["outcome_resolution_method"], "intraday_first_trigger")
        self.assertEqual(result["calibration_quality"], "observed_intraday")

    def test_dual_trigger_without_intraday_uses_conservative_stop_first(self):
        entry, asset, benchmark = self._dual_trigger_case()
        result = build_outcome_update(entry, asset, benchmark, today=date(2026, 1, 3))
        self.assertTrue(result["calibration_eligible"])
        self.assertEqual(result["outcome_status"], "Stopped Out")
        self.assertEqual(result["outcome_resolution_method"], "daily_ohlc_conservative_stop_first")
        self.assertEqual(result["calibration_quality"], "assumption_based_conservative")

    def test_intraday_resolution_requires_time_aligned_benchmark(self):
        entry, asset, benchmark = self._dual_trigger_case()
        intraday = [
            {"Date": "2026-01-02T09:30:00-05:00", "High": 111, "Low": 100, "Close": 110}
        ]
        result = build_outcome_update(
            entry, asset, benchmark, intraday_history=intraday, today=date(2026, 1, 3)
        )
        self.assertFalse(result["calibration_eligible"])
        self.assertIn("benchmark intraday price", result["calibration_exclusion_reason"])

    def test_dual_trigger_can_still_be_explicitly_excluded(self):
        entry, asset, benchmark = self._dual_trigger_case()
        result = build_outcome_update(
            entry, asset, benchmark, dual_trigger_policy="exclude", today=date(2026, 1, 3)
        )
        self.assertFalse(result["calibration_eligible"])
        self.assertTrue(result["dual_trigger_detected"])

    def test_calibration_excludes_unexecuted_entries(self):
        entries = [
            {"executed": False, "calibration_eligible": False},
            {
                "executed": True,
                "calibration_eligible": True,
                "net_excess_return_pct": 2.0,
                "investment_horizon_days": 30,
                "confidence_level": "中",
            },
        ]
        result = calculate_calibration(entries)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["average_net_excess_return_pct"], 2.0)

    def test_calibration_separates_conservative_assumptions_from_observed_headline(self):
        entries = [
            {
                "executed": True,
                "calibration_eligible": True,
                "net_excess_return_pct": 2.0,
                "investment_horizon_days": 30,
                "confidence_level": "中",
                "calibration_quality": "observed_intraday",
            },
            {
                "executed": True,
                "calibration_eligible": True,
                "net_excess_return_pct": -3.0,
                "investment_horizon_days": 30,
                "confidence_level": "中",
                "calibration_quality": "assumption_based_conservative",
            },
        ]
        result = calculate_calibration(entries)
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["observed_count"], 1)
        self.assertEqual(result["assumption_based_count"], 1)
        self.assertEqual(result["average_net_excess_return_pct"], 2.0)
        self.assertEqual(result["assumption_based_average_net_excess_return_pct"], -3.0)

    def test_journal_captures_reproducibility_fields(self):
        brief = valid_brief()
        dashboard = {
            "stock_code": "AAPL",
            "stock_name": "Apple",
            "market_type": "美股",
            "research_mode": "thesis_mode",
            "decision_type": "watch",
            "operation_advice": "观望",
            "confidence_level": "中",
            "confidence_details": {"score": 60},
            "position_direction": "long",
            "research_brief": brief,
            "evidence_items": [{"fact": "x"}],
            "dashboard": {"core_conclusion": {"one_sentence": "watch"}, "data_perspective": {"price_position": {"current_price": 100}}, "battle_plan": {"sniper_points": {}}},
        }
        entry = build_journal_entry(dashboard)
        self.assertEqual(entry["benchmark_symbol"], "SPY")
        self.assertEqual(entry["investment_horizon_days"], 90)
        self.assertEqual(len(entry["source_snapshot_hash"]), 64)
        self.assertEqual(entry["dual_trigger_policy"], "conservative")


if __name__ == "__main__":
    unittest.main()
