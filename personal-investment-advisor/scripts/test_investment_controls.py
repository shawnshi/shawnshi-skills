import contextlib
import io
import sys
import json
import os
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from advice_journal import build_journal_entry
from broker_sync import sync_broker_data
from dashboard_catalog import INDEX_FILENAME, resolve_dashboards
from dashboard_gate import _validate_evidence_items, collect_dashboard_warnings, validate_dashboard
from decision_outcome_report import calculate_calibration
from instrument_gate import validate_instrument
from live_evidence_probe import probe_us_stock
from management_claim_tracker import evaluate_claims
from dashboard_math_gate import validate_math_consistency
from portfolio_loader import (
    build_portfolio_fit,
    build_position_context,
    build_portfolio_risk,
    build_portfolio_summary,
    get_exchange_rate,
    load_positions,
    validate_portfolio_payload,
)
from portfolio_scenario_analyzer import analyze_scenarios
from quality_screener import evaluate_metrics, evaluate_ticker
from rebalance_weights import recalculate_all_weights
from research_brief_gate import validate_research_brief
from save_dashboard import DashboardArchiveError, archive_dashboard, render_markdown
from sync_outcomes import build_outcome_update
from watchlist_gate import evaluate_watchlist
from yf import (
    build_portfolio_batch_audit,
    extract_catalyst_map,
    list_active_non_cash_symbols,
)
import yf as yf_module


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
        "research_mode": "research_only",
        "sentiment_score": 50,
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
                "research_boundary": "Evidence review only; no transaction instruction.",
            },
            "qualitative_analysis": {
                "trend_analysis": "Mixed evidence.",
                "fundamental_analysis": "Margins require confirmation.",
                "pattern_analysis": "Descriptive only.",
                "sector_position": "Peer comparison pending.",
                "hot_topics": "No unsupported theme inference.",
            },
            "data_perspective": {
                "trend_status": {
                    "ma_alignment": "mixed",
                    "rsi_14": 50,
                    "rsi_status": "neutral",
                    "macd_signal": "mixed",
                    "trend_score": 50,
                },
                "price_position": {"current_price": 100, "bias_status": "mid-range"},
                "volume_analysis": {
                    "volume_status": "neutral",
                    "turnover_rate": None,
                    "volume_ratio": None,
                },
                "chip_structure": {"chip_health": "不适用(非A股)"},
                "valuation": "mixed",
                "atr_14": 2.0,
            },
            "intelligence": {
                "sentiment_summary": "Mixed evidence.",
                "positive_catalysts": [],
                "risk_alerts": [],
                "thesis_tracking": {},
            },
            "research_plan": {
                "evidence_checks": ["Verify the next filing."],
                "falsification_checks": ["Check whether margins contract."],
                "monitoring_indicators": ["Reported gross margin."],
            },
        },
        "analysis_summary": "summary",
        "risk_warning": "risk",
        "short_term_outlook": "uncertain",
        "medium_term_outlook": "uncertain",
        "search_performed": True,
        "data_sources": {"filing": "https://www.sec.gov/Archives/example"},
        "data_gaps": [],
        "blind_spot_warning": "Consensus may already price the thesis.",
        "research_brief": valid_brief(),
        "scenario_analysis": {
            "valuation_method": "scenario-based operating evidence review",
            "base": {
                "assumptions": ["Current operating evidence remains stable"],
                "result": "Base operating case remains supported",
                "falsification_conditions": ["Core operating evidence weakens"],
            },
            "bull": {
                "assumptions": ["Key operating variables improve"],
                "result": "Upside operating case",
                "falsification_conditions": ["Expected improvement does not appear"],
            },
            "bear": {
                "assumptions": ["Demand and margins weaken"],
                "result": "Downside operating case",
                "falsification_conditions": ["Downside assumptions do not occur"],
            },
            "sensitivity": ["Demand", "Margin", "Capital intensity"],
        },
        "earnings_snapshot": {
            "next_earnings_date": "2026-08-01",
            "revenue_growth": 0.1,
            "trailing_pe": 20,
            "forward_pe": 18,
        },
        "catalyst_map": {"upcoming": [], "active": [], "broken": [], "data_gaps": []},
    }


def valid_monitoring_boundaries():
    return {
        "decision_scope": "observation_only",
        "metric": "regular_market_price",
        "boundaries": [
            {
                "boundary_id": "lower-001",
                "role": "downside_boundary",
                "operator": "lte",
                "value": 90,
                "currency": "USD",
                "quote_basis": "regular_market_price",
                "authority_status": "user_confirmed",
                "source_tier": "user_authorized",
                "source_locator": "user portfolio policy dated 2026-07-28",
                "as_of_date": "2026-07-22",
            },
            {
                "boundary_id": "upper-001",
                "role": "upside_boundary",
                "operator": "gte",
                "value": 120,
                "currency": "USD",
                "quote_basis": "regular_market_price",
                "authority_status": "user_confirmed",
                "source_tier": "user_authorized",
                "source_locator": "user portfolio policy dated 2026-07-28",
                "as_of_date": "2026-07-22",
            },
        ],
        "proximity_policy": {
            "mode": "explicit_relative_pct",
            "value": 0.03,
            "source_tier": "user_authorized",
            "source_locator": "user portfolio policy dated 2026-07-28",
            "as_of_date": "2026-07-22",
        },
    }


def valid_runtime_quote(current_price=100, market_state="CLOSED"):
    return {
        "symbol": "AAPL",
        "current_price": current_price,
        "currency": "USD",
        "as_of": "2026-07-30T20:00:00+00:00",
        "source": "test market-data snapshot",
        "market_state": market_state,
    }


class DashboardArchiveLifecycleTests(unittest.TestCase):
    def test_archive_persists_json_markdown_and_latest_index(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            result = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            )

            json_path = Path(result["json_path"])
            markdown_path = Path(result["markdown_path"])
            index_path = Path(tmpdir) / INDEX_FILENAME
            archived = json.loads(json_path.read_text(encoding="utf-8"))
            index = json.loads(index_path.read_text(encoding="utf-8"))

            self.assertTrue(json_path.is_file())
            self.assertTrue(markdown_path.is_file())
            self.assertEqual(validate_dashboard(archived), [])
            self.assertEqual(validate_math_consistency(archived), [])
            self.assertIn(
                f"```json\n{json_path.read_text(encoding='utf-8').rstrip()}\n```",
                markdown_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(index["dashboards"]["AAPL"]["dashboard_contract_version"], "6.1")
            self.assertRegex(
                index["dashboards"]["AAPL"]["json_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(
                index["dashboards"]["AAPL"]["markdown_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                index["dashboards"]["AAPL"]["json_path"],
                json_path.relative_to(tmpdir).as_posix(),
            )

            resolved = resolve_dashboards(tmpdir, ["AAPL", "MSFT"])
            by_symbol = {entry["symbol"]: entry for entry in resolved["entries"]}
            self.assertFalse(resolved["complete"])
            self.assertEqual(by_symbol["AAPL"]["status"], "valid")
            self.assertEqual(by_symbol["MSFT"]["status"], "insufficient_data")

    def test_catalog_uses_insufficient_data_for_missing_index_or_symbol(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            missing_index = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(missing_index["complete"])
            self.assertEqual(
                missing_index["entries"][0],
                {
                    "symbol": "AAPL",
                    "status": "insufficient_data",
                    "reason": "dashboard_index_missing",
                },
            )

            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            missing_symbol = resolve_dashboards(tmpdir, ["MSFT"])
            self.assertFalse(missing_symbol["complete"])
            self.assertEqual(
                missing_symbol["entries"][0],
                {
                    "symbol": "MSFT",
                    "status": "insufficient_data",
                    "reason": "dashboard_not_indexed",
                },
            )

    def test_archive_rejects_identity_mismatch_and_legacy_fields_without_writes(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    valid_dashboard(),
                    output_dir=tmpdir,
                    stock_alias="",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    valid_dashboard(),
                    output_dir=tmpdir,
                    stock_alias=None,
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    valid_dashboard(),
                    output_dir=tmpdir,
                    stock_alias="Apple",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    valid_dashboard(),
                    output_dir=tmpdir,
                    stock_alias="MSFT",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            internal_mismatch = valid_dashboard()
            internal_mismatch["research_brief"]["instrument"]["symbol"] = "MSFT"
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    internal_mismatch,
                    output_dir=tmpdir,
                    stock_alias="AAPL",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            unsafe_symbol = valid_dashboard()
            unsafe_symbol["stock_code"] = "../AAPL"
            unsafe_symbol["research_brief"]["instrument"]["symbol"] = "../AAPL"
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    unsafe_symbol,
                    output_dir=tmpdir,
                    stock_alias="../AAPL",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            reserved_symbol = valid_dashboard()
            reserved_symbol["stock_code"] = "CON"
            reserved_symbol["research_brief"]["instrument"]["symbol"] = "CON"
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    reserved_symbol,
                    output_dir=tmpdir,
                    stock_alias="CON",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            legacy = valid_dashboard()
            legacy["dashboard"]["battle_plan"] = {
                "sniper_points": {"stop_loss": 90, "take_profit": 120}
            }
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(legacy, output_dir=tmpdir, stock_alias="AAPL")
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

            math_invalid = valid_dashboard()
            math_invalid["confidence_details"]["score"] = 120
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    math_invalid,
                    output_dir=tmpdir,
                    stock_alias="AAPL",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

    def test_catalog_fails_closed_for_identity_mismatch_and_invalid_json(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            result = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            json_path = Path(result["json_path"])
            mismatched = json.loads(json_path.read_text(encoding="utf-8"))
            mismatched["stock_code"] = "MSFT"
            json_path.write_text(
                json.dumps(mismatched, ensure_ascii=False),
                encoding="utf-8",
            )

            mismatch_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(mismatch_report["complete"])
            self.assertEqual(
                mismatch_report["entries"][0]["reason"],
                "stock_code_mismatch",
            )

            json_path.write_text("{", encoding="utf-8")
            invalid_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(invalid_report["complete"])
            self.assertEqual(
                invalid_report["entries"][0]["reason"],
                "dashboard_unreadable",
            )

    def test_catalog_fails_closed_for_markdown_and_encoding_corruption(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            result = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            json_path = Path(result["json_path"])
            markdown_path = Path(result["markdown_path"])
            original_markdown = markdown_path.read_bytes()

            markdown_path.write_text("", encoding="utf-8")
            markdown_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(markdown_report["complete"])
            self.assertEqual(
                markdown_report["entries"][0]["status"],
                "insufficient_data",
            )
            self.assertEqual(
                markdown_report["entries"][0]["reason"],
                "dashboard_integrity_mismatch",
            )

            markdown_path.write_bytes(original_markdown)
            json_path.write_bytes(b"\xff\xfe\x00")
            encoding_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(encoding_report["complete"])
            self.assertEqual(
                encoding_report["entries"][0]["status"],
                "insufficient_data",
            )
            self.assertEqual(
                encoding_report["entries"][0]["reason"],
                "dashboard_unreadable",
            )

    def test_catalog_rejects_index_paths_outside_archive_root(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            index_path = Path(tmpdir) / INDEX_FILENAME
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["dashboards"]["AAPL"]["json_path"] = "../outside.json"
            index_path.write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )

            report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(report["complete"])
            self.assertEqual(report["entries"][0]["reason"], "dashboard_path_invalid")

    def test_catalog_rejects_index_entry_identity_mismatch(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            index_path = Path(tmpdir) / INDEX_FILENAME
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["dashboards"]["AAPL"]["stock_code"] = "MSFT"
            index_path.write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )

            report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(report["complete"])
            self.assertEqual(
                report["entries"][0]["reason"],
                "index_stock_code_mismatch",
            )

    def test_catalog_rejects_numeric_index_stock_code(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            dashboard = valid_dashboard()
            dashboard["stock_code"] = "123"
            dashboard["research_brief"]["instrument"]["symbol"] = "123"
            archive_dashboard(
                dashboard,
                output_dir=tmpdir,
                stock_alias="123",
            )
            index_path = Path(tmpdir) / INDEX_FILENAME
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["dashboards"]["123"]["stock_code"] = 123
            index_path.write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )

            report = resolve_dashboards(tmpdir, ["123"])
            self.assertFalse(report["complete"])
            self.assertEqual(
                report["entries"][0]["reason"],
                "index_stock_code_mismatch",
            )

    def test_catalog_rejects_non_string_index_path_metadata(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            index_path = Path(tmpdir) / INDEX_FILENAME
            index = json.loads(index_path.read_text(encoding="utf-8"))
            original_generation_id = index["dashboards"]["AAPL"]["generation_id"]

            index["dashboards"]["AAPL"]["generation_id"] = 123
            index_path.write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )
            generation_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertEqual(
                generation_report["entries"][0]["reason"],
                "generation_id_invalid",
            )

            index["dashboards"]["AAPL"]["generation_id"] = original_generation_id
            index["dashboards"]["AAPL"]["json_path"] = 123
            index_path.write_text(
                json.dumps(index, ensure_ascii=False),
                encoding="utf-8",
            )
            path_report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertEqual(
                path_report["entries"][0]["reason"],
                "dashboard_path_invalid",
            )

    def test_catalog_rejects_invalid_top_level_index_metadata(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            index_path = Path(tmpdir) / INDEX_FILENAME
            original = json.loads(index_path.read_text(encoding="utf-8"))
            mutations = (
                ("numeric updated_at", lambda index: index.update(updated_at=123)),
                ("missing updated_at", lambda index: index.pop("updated_at")),
                ("float schema", lambda index: index.update(schema_version=3.0)),
            )

            for label, mutate in mutations:
                with self.subTest(label=label):
                    index = json.loads(json.dumps(original))
                    mutate(index)
                    index_path.write_text(
                        json.dumps(index, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    report = resolve_dashboards(tmpdir, ["AAPL"])
                    self.assertEqual(report["catalog_status"], "index_invalid")
                    self.assertFalse(report["complete"])
                    self.assertEqual(
                        report["entries"][0]["reason"],
                        "dashboard_index_invalid",
                    )

    def test_catalog_rejects_incomplete_generation(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            result = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
            )
            Path(result["markdown_path"]).unlink()

            report = resolve_dashboards(tmpdir, ["AAPL"])
            self.assertFalse(report["complete"])
            self.assertEqual(
                report["entries"][0]["status"],
                "insufficient_data",
            )
            self.assertEqual(
                report["entries"][0]["reason"],
                "dashboard_generation_incomplete",
            )

    def test_newer_archive_replaces_only_latest_pointer(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            first = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            )
            second = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(
                    2026,
                    7,
                    30,
                    12,
                    0,
                    0,
                    1,
                    tzinfo=timezone.utc,
                ),
            )
            index = json.loads(
                (Path(tmpdir) / INDEX_FILENAME).read_text(encoding="utf-8")
            )

            self.assertTrue(Path(first["json_path"]).is_file())
            self.assertTrue(Path(second["json_path"]).is_file())
            self.assertNotEqual(first["json_path"], second["json_path"])
            self.assertEqual(
                index["dashboards"]["AAPL"]["json_path"],
                Path(second["json_path"]).relative_to(tmpdir).as_posix(),
            )

    def test_older_archive_cannot_regress_latest_pointer(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            newer = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc),
                generation_id="g-newer",
            )
            older = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                generation_id="g-older",
            )
            index = json.loads(
                (Path(tmpdir) / INDEX_FILENAME).read_text(encoding="utf-8")
            )

            self.assertTrue(Path(newer["json_path"]).is_file())
            self.assertTrue(Path(older["json_path"]).is_file())
            self.assertTrue(newer["index_updated"])
            self.assertFalse(older["index_updated"])
            self.assertEqual(
                index["dashboards"]["AAPL"]["json_path"],
                Path(newer["json_path"]).relative_to(tmpdir).as_posix(),
            )
            self.assertEqual(index["dashboards"]["AAPL"]["generation_id"], "g-newer")

    def test_equal_timestamp_uses_generation_id_as_stable_tiebreaker(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archived_at = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
            first = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=archived_at,
                generation_id="g-200",
            )
            lower = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=archived_at,
                generation_id="g-100",
            )
            higher = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=archived_at,
                generation_id="g-300",
            )
            index = json.loads(
                (Path(tmpdir) / INDEX_FILENAME).read_text(encoding="utf-8")
            )

            self.assertTrue(first["index_updated"])
            self.assertFalse(lower["index_updated"])
            self.assertTrue(higher["index_updated"])
            self.assertEqual(
                index["dashboards"]["AAPL"]["generation_id"],
                "g-300",
            )

    def test_top_level_index_timestamp_does_not_regress_across_symbols(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc),
                generation_id="g-aapl",
            )
            msft = valid_dashboard()
            msft["stock_name"] = "Microsoft"
            msft["stock_code"] = "MSFT"
            msft["research_brief"]["instrument"]["symbol"] = "MSFT"
            archive_dashboard(
                msft,
                output_dir=tmpdir,
                stock_alias="MSFT",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                generation_id="g-msft",
            )
            index = json.loads(
                (Path(tmpdir) / INDEX_FILENAME).read_text(encoding="utf-8")
            )

            self.assertEqual(
                datetime.fromisoformat(index["updated_at"]),
                datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(set(index["dashboards"]), {"AAPL", "MSFT"})

    def test_concurrent_archives_keep_latest_pointer_monotonic(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            barrier = threading.Barrier(2)

            def archive_at(archived_at, generation_id):
                barrier.wait()
                return archive_dashboard(
                    valid_dashboard(),
                    output_dir=tmpdir,
                    stock_alias="AAPL",
                    now=archived_at,
                    generation_id=generation_id,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                newer = executor.submit(
                    archive_at,
                    datetime(2026, 7, 30, 12, 1, tzinfo=timezone.utc),
                    "g-concurrent-newer",
                )
                older = executor.submit(
                    archive_at,
                    datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                    "g-concurrent-older",
                )
                results = [newer.result(), older.result()]

            index = json.loads(
                (Path(tmpdir) / INDEX_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                index["dashboards"]["AAPL"]["generation_id"],
                "g-concurrent-newer",
            )
            self.assertTrue(all(Path(item["json_path"]).is_file() for item in results))

    def test_existing_generation_is_never_overwritten(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archived_at = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
            first = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=archived_at,
                generation_id="g-immutable",
            )
            json_path = Path(first["json_path"])
            markdown_path = Path(first["markdown_path"])
            index_path = Path(tmpdir) / INDEX_FILENAME
            original_json = json_path.read_bytes()
            original_markdown = markdown_path.read_bytes()
            original_index = index_path.read_bytes()

            changed = valid_dashboard()
            changed["analysis_summary"] = "changed content must not overwrite"
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    changed,
                    output_dir=tmpdir,
                    stock_alias="AAPL",
                    now=archived_at,
                    generation_id="g-immutable",
                )

            self.assertEqual(json_path.read_bytes(), original_json)
            self.assertEqual(markdown_path.read_bytes(), original_markdown)
            self.assertEqual(index_path.read_bytes(), original_index)

    def test_index_failure_preserves_old_generation_and_index(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            first = archive_dashboard(
                valid_dashboard(),
                output_dir=tmpdir,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                generation_id="g-0001",
            )
            first_json = Path(first["json_path"])
            first_markdown = Path(first["markdown_path"])
            index_path = Path(tmpdir) / INDEX_FILENAME
            original_json = first_json.read_bytes()
            original_markdown = first_markdown.read_bytes()
            original_index = index_path.read_bytes()

            with patch(
                "dashboard_catalog._atomic_write_text",
                side_effect=OSError("simulated index commit failure"),
            ):
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(
                        valid_dashboard(),
                        output_dir=tmpdir,
                        stock_alias="AAPL",
                        now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                        generation_id="g-0002",
                    )

            self.assertEqual(first_json.read_bytes(), original_json)
            self.assertEqual(first_markdown.read_bytes(), original_markdown)
            self.assertEqual(index_path.read_bytes(), original_index)
            second_generation = (
                Path(tmpdir) / "AAPL" / "generations" / "g-0002"
            )
            self.assertTrue((second_generation / "dashboard.json").is_file())
            self.assertTrue((second_generation / "dashboard.md").is_file())
            self.assertFalse(
                any(
                    path.name.startswith(".pending-") or path.suffix == ".tmp"
                    for path in Path(tmpdir).rglob("*")
                )
            )

    def test_archive_rejects_linked_symbol_directory(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            archive_root = root / "archive"
            outside = root / "outside"
            archive_root.mkdir()
            outside.mkdir()
            try:
                os.symlink(
                    outside,
                    archive_root / "AAPL",
                    target_is_directory=True,
                )
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")

            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    valid_dashboard(),
                    output_dir=archive_root,
                    stock_alias="AAPL",
                    generation_id="g-link-test",
                )

            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((archive_root / INDEX_FILENAME).exists())

    @unittest.skipUnless(os.name == "nt", "NTFS junction test requires Windows")
    def test_archive_rejects_junction_symbol_directory(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            archive_root = root / "archive"
            outside = root / "outside"
            link = archive_root / "AAPL"
            archive_root.mkdir()
            outside.mkdir()
            command = (
                "New-Item -ItemType Junction "
                "-Path $env:PIA_TEST_JUNCTION_LINK "
                "-Target $env:PIA_TEST_JUNCTION_TARGET | Out-Null"
            )
            environment = os.environ.copy()
            environment["PIA_TEST_JUNCTION_LINK"] = str(link)
            environment["PIA_TEST_JUNCTION_TARGET"] = str(outside)
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            if result.returncode != 0 or not link.is_junction():
                self.skipTest(
                    f"directory junction unavailable: {result.stderr.strip()}"
                )
            try:
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(
                        valid_dashboard(),
                        output_dir=archive_root,
                        stock_alias="AAPL",
                        generation_id="g-junction-test",
                    )
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((archive_root / INDEX_FILENAME).exists())
            finally:
                if link.is_junction():
                    link.rmdir()

    def test_save_cli_commits_pair_before_deleting_input(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            input_path = root / "draft.json"
            archive_root = root / "archive"
            input_path.write_text(
                json.dumps(valid_dashboard(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "save_dashboard.py"),
                    "--stock",
                    "AAPL",
                    "--file",
                    str(input_path),
                    "--output-dir",
                    str(archive_root),
                    "--delete-input",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(input_path.exists())
            index = json.loads(
                (archive_root / INDEX_FILENAME).read_text(encoding="utf-8")
            )
            entry = index["dashboards"]["AAPL"]
            self.assertTrue((archive_root / entry["json_path"]).is_file())
            self.assertTrue((archive_root / entry["markdown_path"]).is_file())

    def test_save_cli_failure_preserves_input_and_writes_no_archive(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            input_path = root / "legacy.json"
            archive_root = root / "archive"
            legacy = valid_dashboard()
            legacy["operation_advice"] = "buy"
            input_path.write_text(
                json.dumps(legacy, ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "save_dashboard.py"),
                    "--stock",
                    "AAPL",
                    "--file",
                    str(input_path),
                    "--output-dir",
                    str(archive_root),
                    "--delete-input",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertTrue(input_path.is_file())
            self.assertFalse(archive_root.exists())

    def test_save_cli_index_failure_preserves_input_and_old_index(self):
        from save_dashboard import save_dashboard as run_save_dashboard

        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            input_path = root / "draft.json"
            archive_root = root / "archive"
            archive_dashboard(
                valid_dashboard(),
                output_dir=archive_root,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                generation_id="g-current",
            )
            index_path = archive_root / INDEX_FILENAME
            original_index = index_path.read_bytes()
            input_path.write_text(
                json.dumps(valid_dashboard(), ensure_ascii=False),
                encoding="utf-8",
            )

            arguments = [
                "save_dashboard.py",
                "--stock",
                "AAPL",
                "--file",
                str(input_path),
                "--output-dir",
                str(archive_root),
                "--delete-input",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch(
                    "dashboard_catalog._atomic_write_text",
                    side_effect=OSError("simulated index sharing violation"),
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as exit_context:
                    run_save_dashboard()

            self.assertEqual(exit_context.exception.code, 1)
            self.assertTrue(input_path.is_file())
            self.assertEqual(index_path.read_bytes(), original_index)

    def test_delete_input_refuses_to_remove_archived_generation(self):
        from save_dashboard import save_dashboard as run_save_dashboard

        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            archive_root = Path(tmpdir) / "archive"
            history = archive_dashboard(
                valid_dashboard(),
                output_dir=archive_root,
                stock_alias="AAPL",
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
                generation_id="g-history",
            )
            history_path = Path(history["json_path"])
            index_path = archive_root / INDEX_FILENAME
            original_history = history_path.read_bytes()
            original_index = index_path.read_bytes()
            original_files = {
                path.relative_to(archive_root).as_posix()
                for path in archive_root.rglob("*")
                if path.is_file()
            }

            arguments = [
                "save_dashboard.py",
                "--stock",
                "AAPL",
                "--file",
                str(history_path),
                "--output-dir",
                str(archive_root),
                "--delete-input",
            ]
            with (
                patch.object(sys, "argv", arguments),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as exit_context:
                    run_save_dashboard()

            self.assertEqual(exit_context.exception.code, 1)
            self.assertEqual(history_path.read_bytes(), original_history)
            self.assertEqual(index_path.read_bytes(), original_index)
            self.assertEqual(
                {
                    path.relative_to(archive_root).as_posix()
                    for path in archive_root.rglob("*")
                    if path.is_file()
                },
                original_files,
            )

    def test_delete_input_refuses_draft_changed_during_archive(self):
        from save_dashboard import save_dashboard as run_save_dashboard

        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            input_path = root / "draft.json"
            archive_root = root / "archive"
            input_path.write_text(
                json.dumps(valid_dashboard(), ensure_ascii=False),
                encoding="utf-8",
            )
            real_archive = archive_dashboard

            def archive_then_change_input(*args, **kwargs):
                result = real_archive(*args, **kwargs)
                input_path.write_text(
                    json.dumps(valid_dashboard(), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return result

            arguments = [
                "save_dashboard.py",
                "--stock",
                "AAPL",
                "--file",
                str(input_path),
                "--output-dir",
                str(archive_root),
                "--delete-input",
            ]
            output = io.StringIO()
            with (
                patch.object(sys, "argv", arguments),
                patch(
                    "save_dashboard.archive_dashboard",
                    side_effect=archive_then_change_input,
                ),
                contextlib.redirect_stdout(output),
            ):
                run_save_dashboard()

            self.assertTrue(input_path.is_file())
            self.assertIn(
                "input draft changed during archive",
                output.getvalue(),
            )
            self.assertTrue((archive_root / INDEX_FILENAME).is_file())

    def test_cli_non_latest_generation_preserves_input_and_returns_failure(self):
        from save_dashboard import save_dashboard as run_save_dashboard

        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            input_path = root / "draft.json"
            archive_root = root / "archive"
            archive_dashboard(
                valid_dashboard(),
                output_dir=archive_root,
                stock_alias="AAPL",
                now=datetime(2099, 1, 1, tzinfo=timezone.utc),
                generation_id="g-future",
            )
            index_path = archive_root / INDEX_FILENAME
            original_index = index_path.read_bytes()
            input_path.write_text(
                json.dumps(valid_dashboard(), ensure_ascii=False),
                encoding="utf-8",
            )

            arguments = [
                "save_dashboard.py",
                "--stock",
                "AAPL",
                "--file",
                str(input_path),
                "--output-dir",
                str(archive_root),
                "--delete-input",
            ]
            with (
                patch.object(sys, "argv", arguments),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as exit_context:
                    run_save_dashboard()

            self.assertEqual(exit_context.exception.code, 1)
            self.assertTrue(input_path.is_file())
            self.assertEqual(index_path.read_bytes(), original_index)
            self.assertEqual(
                json.loads(index_path.read_text(encoding="utf-8"))[
                    "dashboards"
                ]["AAPL"]["generation_id"],
                "g-future",
            )

    def test_pair_publish_failure_leaves_no_generation_or_temporary_files(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            with patch(
                "save_dashboard.os.rename",
                side_effect=OSError("simulated generation publish failure"),
            ):
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(
                        valid_dashboard(),
                        output_dir=tmpdir,
                        stock_alias="AAPL",
                    )

            artifacts = list(Path(tmpdir).rglob("*"))
            self.assertFalse(any(path.suffix in {".json", ".md", ".tmp"} for path in artifacts))
            self.assertFalse(
                any(path.name.startswith(".pending-") for path in artifacts)
            )

    def test_pair_write_failure_leaves_no_generation_or_temporary_files(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            from save_dashboard import _write_text_fsync

            write_calls = 0

            def fail_markdown_write(path, content):
                nonlocal write_calls
                write_calls += 1
                if write_calls == 2:
                    raise OSError("simulated Markdown staging failure")
                return _write_text_fsync(path, content)

            with patch(
                "save_dashboard._write_text_fsync",
                side_effect=fail_markdown_write,
            ):
                with self.assertRaises(DashboardArchiveError):
                    archive_dashboard(
                        valid_dashboard(),
                        output_dir=tmpdir,
                        stock_alias="AAPL",
                    )

            artifacts = list(Path(tmpdir).rglob("*"))
            self.assertFalse(
                any(path.suffix in {".json", ".md", ".tmp"} for path in artifacts)
            )
            self.assertFalse(
                any(path.name.startswith(".pending-") for path in artifacts)
            )

    def test_serialization_failure_occurs_before_archive_writes(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            dashboard = valid_dashboard()
            dashboard["data_sources"] = [object()]
            with self.assertRaises(DashboardArchiveError):
                archive_dashboard(
                    dashboard,
                    output_dir=tmpdir,
                    stock_alias="AAPL",
                )
            self.assertEqual(list(Path(tmpdir).iterdir()), [])


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

    def test_etf_brief_uses_evidence_only_profile(self):
        brief = valid_brief()
        brief["instrument"] = {
            "symbol": "QQQ",
            "market": "US",
            "asset_type": "etf",
            "currency": "USD",
        }
        brief["method_profile"] = "etf_research"
        self.assertEqual(validate_research_brief(brief), [])

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
    def test_full_research_only_dashboard_passes_both_contracts(self):
        self.assertEqual(validate_dashboard(valid_dashboard()), [])

    def test_dashboard_identity_requires_nonempty_matching_stock_code(self):
        dashboard = valid_dashboard()
        dashboard["stock_code"] = ""
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any("stock_code must be a non-empty string" in error for error in errors)
        )

        dashboard = valid_dashboard()
        dashboard["stock_code"] = "MSFT"
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any(
                "stock_code must match research_brief.instrument.symbol" in error
                for error in errors
            )
        )

        dashboard = valid_dashboard()
        dashboard["stock_code"] = 123
        dashboard["research_brief"]["instrument"]["symbol"] = 123
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any("stock_code must be a non-empty string" in error for error in errors)
        )
        self.assertTrue(
            any(
                "research_brief.instrument.symbol must be a non-empty string"
                in error
                for error in errors
            )
        )

        dashboard = valid_dashboard()
        dashboard["research_brief"]["instrument"]["market"] = "CN"
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any(
                "market_type must match research_brief.instrument.market" in error
                for error in errors
            )
        )

        dashboard = valid_dashboard()
        dashboard["market_type"] = "ETF"
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any(
                "market_type must match research_brief.instrument.asset_type"
                in error
                for error in errors
            )
        )

        dashboard = valid_dashboard()
        dashboard["market_type"] = "其他"
        errors = validate_dashboard(dashboard)
        self.assertTrue(
            any(
                "market_type must match research_brief.instrument.asset_type"
                in error
                for error in errors
            )
        )

    def test_qualitative_monitoring_indicator_does_not_block(self):
        dashboard = valid_dashboard()
        dashboard["dashboard"]["research_plan"]["monitoring_indicators"] = [
            "等待下一份审计财报"
        ]
        self.assertEqual(validate_dashboard(dashboard), [])
        self.assertEqual(collect_dashboard_warnings(dashboard), [])

    def test_trade_payload_without_brief_is_rejected(self):
        dashboard = valid_dashboard()
        dashboard.pop("research_brief")
        dashboard["research_mode"] = "trading_mode"
        dashboard["decision_type"] = "buy"
        dashboard["operation_advice"] = "买入"
        dashboard["position_direction"] = "long"
        errors = validate_dashboard(dashboard)
        self.assertTrue(any("research_brief is required" in error for error in errors))
        self.assertTrue(any("legacy trade field" in error for error in errors))
        self.assertTrue(any("invalid research_mode" in error for error in errors))
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "legacy-dashboard.json"
            path.write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "dashboard_gate.py"), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)

    def test_nested_trade_contract_is_rejected(self):
        dashboard = valid_dashboard()
        dashboard["dashboard"]["battle_plan"] = {
            "sniper_points": {"stop_loss": 90, "take_profit": 120},
            "position_strategy": {"suggested_position": "20%"},
        }
        errors = validate_dashboard(dashboard)
        self.assertTrue(any("legacy trade field" in error for error in errors))

    def test_structured_monitoring_boundaries_pass_without_restoring_trade_fields(self):
        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        self.assertEqual(validate_dashboard(dashboard), [])
        serialized = json.dumps(dashboard, ensure_ascii=False)
        for forbidden in ("stop_loss", "take_profit", "battle_plan", "sniper_points"):
            self.assertNotIn(forbidden, serialized)

    def test_monitoring_boundary_contract_rejects_string_values_and_inverted_bounds(self):
        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        dashboard["monitoring_boundaries"]["boundaries"][0]["value"] = "90 USD"
        self.assertTrue(
            any("value must be a positive finite JSON number" in error for error in validate_dashboard(dashboard))
        )

        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        dashboard["monitoring_boundaries"]["boundaries"][0]["value"] = 130
        self.assertTrue(
            any("downside boundary must be below upside boundary" in error for error in validate_dashboard(dashboard))
        )

    def test_watchlist_gate_is_fail_closed_and_never_emits_actions(self):
        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        dashboard["dashboard"]["data_perspective"]["price_position"]["current_price"] = 1
        dashboard["freshness_flags"]["price_data_fresh"] = False
        report = evaluate_watchlist(
            dashboard,
            valid_runtime_quote(118),
            now=datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["evaluation_status"], "complete")
        self.assertEqual(report["categories"]["near_boundary"], ["upper-001"])
        self.assertEqual(report["categories"]["downside_boundary_crossed"], [])
        self.assertEqual(report["runtime_quote"]["current_price"], 118)
        serialized = json.dumps(report, ensure_ascii=False)
        for forbidden in ("buy", "sell", "order", "position_size", "stop_loss", "take_profit"):
            self.assertNotIn(forbidden, serialized)

        stale_report = evaluate_watchlist(dashboard)
        self.assertEqual(stale_report["evaluation_status"], "insufficient_data")
        self.assertIn(
            "runtime_quote_missing",
            stale_report["categories"]["insufficient_data"],
        )

    def test_watchlist_gate_reports_each_crossed_boundary_role(self):
        downside = valid_dashboard()
        downside["monitoring_boundaries"] = valid_monitoring_boundaries()
        downside_report = evaluate_watchlist(
            downside,
            valid_runtime_quote(85),
            now=datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            downside_report["categories"]["downside_boundary_crossed"],
            ["lower-001"],
        )
        self.assertEqual(
            downside_report["categories"]["upside_boundary_crossed"],
            [],
        )

        upside = valid_dashboard()
        upside["monitoring_boundaries"] = valid_monitoring_boundaries()
        upside_report = evaluate_watchlist(
            upside,
            valid_runtime_quote(125),
            now=datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            upside_report["categories"]["upside_boundary_crossed"],
            ["upper-001"],
        )
        self.assertEqual(
            upside_report["categories"]["downside_boundary_crossed"],
            [],
        )

    def test_watchlist_gate_distinguishes_undefined_and_unverified_boundaries(self):
        undefined = evaluate_watchlist(valid_dashboard())
        self.assertEqual(undefined["evaluation_status"], "thresholds_undefined")

        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        dashboard["monitoring_boundaries"]["boundaries"][0]["authority_status"] = "unverified_legacy"
        report = evaluate_watchlist(
            dashboard,
            valid_runtime_quote(),
            now=datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertIn("lower-001", report["categories"]["insufficient_data"])

    def test_watchlist_gate_does_not_invent_a_near_rule(self):
        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        dashboard["monitoring_boundaries"].pop("proximity_policy")
        report = evaluate_watchlist(
            dashboard,
            valid_runtime_quote(),
            now=datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(report["evaluation_status"], "complete")
        self.assertEqual(
            report["categories"]["near_rule_undefined"],
            ["lower-001", "upper-001"],
        )
        self.assertEqual(report["categories"]["near_boundary"], [])

    def test_watchlist_cli_returns_structured_observation_report(self):
        dashboard = valid_dashboard()
        dashboard["monitoring_boundaries"] = valid_monitoring_boundaries()
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "dashboard.json"
            quote_path = Path(tmpdir) / "quote.json"
            path.write_text(json.dumps(dashboard, ensure_ascii=False), encoding="utf-8")
            quote_path.write_text(
                json.dumps(valid_runtime_quote(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "watchlist_gate.py"),
                    str(path),
                    "--quote-snapshot",
                    str(quote_path),
                    "--now",
                    "2026-07-30T21:00:00+00:00",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["evaluation_status"], "complete")
        self.assertEqual(
            report["categories"]["not_crossed"],
            ["lower-001", "upper-001"],
        )

    def test_renderer_contains_only_research_plan(self):
        dashboard = valid_dashboard()
        rendered = render_markdown(
            dashboard, json.dumps(dashboard, ensure_ascii=False)
        )
        self.assertIn("后续研究计划", rendered)
        for forbidden in (
            "战术调度指令",
            "理想买点",
            "止损位",
            "目标位",
            "建议仓位",
            "建仓策略",
            "操作建议",
        ):
            self.assertNotIn(forbidden, rendered)

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

    def test_evidence_only_etf_profile_is_not_a_financial_pass(self):
        result = evaluate_ticker(
            "QQQ",
            "etf_research",
            {"screening_mode": "evidence_only", "thresholds": {}},
        )
        self.assertEqual(result["status"], "not_applicable")
        self.assertIsNone(result["source"])
        self.assertEqual(result["checks"], [])


class PortfolioTests(unittest.TestCase):
    def test_loader_preserves_metadata_and_isolates_zero_quantity_records(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            payload = {
                "base_currency": "CNY",
                "exchange_rates": {"CNY": 1.0, "USD": 6.8},
                "risk_profile": {
                    "high_concentration_threshold": 0.25,
                    "medium_concentration_threshold": 0.15,
                    "max_market_exposure_high": 0.8,
                    "max_market_exposure_medium": 0.6,
                    "max_single_stock_weight": 0.2,
                    "liquidity_high_days": 10,
                    "liquidity_medium_days": 5,
                    "provenance": {
                        "source_type": "user_authorized",
                        "source": "test fixture",
                        "as_of_date": "2026-07-28",
                        "region": "global",
                        "purpose": "test",
                    },
                },
                "positions": [
                    {
                        "symbol": "AAPL",
                        "quantity": 2,
                        "avg_cost": 100,
                        "currency": "USD",
                        "market_type": "US_STOCK",
                    },
                    {
                        "symbol": "VOO",
                        "quantity": 0,
                        "avg_cost": 600,
                        "currency": "USD",
                        "market_type": "ETF",
                        "current_weight": 0,
                    },
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_positions(str(path))

        self.assertEqual(loaded["base_currency"], "CNY")
        self.assertEqual(loaded["exchange_rates"]["USD"], 6.8)
        self.assertEqual(loaded["risk_profile"]["provenance"]["source"], "test fixture")
        self.assertEqual([item["symbol"] for item in loaded["positions"]], ["AAPL"])
        self.assertEqual(loaded["_inactive_zero_quantity_symbols"], ["VOO"])
        inactive = build_position_context("VOO", current_price=700, payload=loaded)
        self.assertFalse(inactive["has_position"])
        self.assertEqual(inactive["position_status"], "inactive_zero_quantity")

    def test_cross_currency_position_context_declares_fx_and_base_currency(self):
        payload = {
            "_status": "ok",
            "_path": "test.json",
            "_positions_dict": {
                "AAPL": {
                    "symbol": "AAPL",
                    "quantity": 2,
                    "avg_cost": 100,
                    "currency": "USD",
                }
            },
            "_inactive_positions_dict": {},
            "positions": [],
            "base_currency": "CNY",
            "exchange_rates": {"USD": 6.8},
        }
        context = build_position_context("AAPL", current_price=110, payload=payload)
        self.assertEqual(context["base_currency"], "CNY")
        self.assertEqual(context["fx_rate_to_base"], 6.8)
        self.assertEqual(context["market_value"], 1496.0)
        self.assertEqual(context["cost_basis"], 1360.0)

    def test_dashboard_math_gate_applies_position_fx_rate(self):
        dashboard = {
            "portfolio_context": {
                "has_position": True,
                "quantity": 2,
                "avg_cost": 100,
                "current_price": 110,
                "fx_rate_to_base": 6.8,
                "market_value": 1496,
                "cost_basis": 1360,
                "unrealized_pnl": 136,
                "unrealized_pnl_pct": 0.1,
            }
        }
        self.assertEqual(validate_math_consistency(dashboard), [])

    def test_dashboard_gate_rejects_zero_position_fx_rate(self):
        dashboard = valid_dashboard()
        dashboard["portfolio_context"] = {
            "has_position": True,
            "quantity": 2,
            "avg_cost": 100,
            "current_price": 110,
            "currency": "USD",
            "base_currency": "CNY",
            "fx_rate_to_base": 0,
            "market_value": 220,
            "cost_basis": 200,
            "unrealized_pnl": 20,
            "unrealized_pnl_pct": 0.1,
            "position_status": "matched",
        }
        dashboard["holding_assessment"] = {
            "holding_context": "existing position",
            "cost_basis_context": "cost basis supplied by user",
            "risk_evidence": "requires monitoring",
            "monitoring_conditions": ["verify current filing"],
        }
        self.assertTrue(
            any(
                "fx_rate_to_base must be positive" in error
                for error in validate_dashboard(dashboard)
            )
        )

    def test_dashboard_accepts_observation_only_portfolio_fit_contract(self):
        dashboard = valid_dashboard()
        portfolio_context = {
            "has_position": True,
            "quantity": 1,
            "avg_cost": 100,
            "current_price": 110,
            "currency": "USD",
            "base_currency": "USD",
            "fx_rate_to_base": 1,
            "market_value": 110,
            "cost_basis": 100,
            "unrealized_pnl": 10,
            "unrealized_pnl_pct": 0.1,
            "position_status": "matched",
            "weight_status": "within_target",
        }
        summary = {
            "total_positions": 1,
            "tracked_weight": 1.0,
            "market_exposure": {"US": 1.0},
            "top_positions_by_weight": [{"symbol": "AAPL", "weight": 1.0}],
            "concentration_score": 1.0,
            "concentration_bucket": "unknown",
        }
        risk = {
            "concentration_risk": "未知",
            "market_exposure_risk": "未知",
            "style_drift_risk": "未知",
            "liquidity_risk": "未知",
            "risk_data_gaps": ["risk profile not configured"],
        }
        dashboard["portfolio_context"] = portfolio_context
        dashboard["portfolio_summary"] = summary
        dashboard["portfolio_risk"] = risk
        dashboard["portfolio_fit"] = build_portfolio_fit(
            portfolio_context,
            summary,
            risk,
        )
        dashboard["holding_assessment"] = {
            "holding_context": "existing position",
            "cost_basis_context": "cost basis supplied by user",
            "risk_evidence": "requires monitoring",
            "monitoring_conditions": ["verify current filing"],
        }
        self.assertEqual(validate_dashboard(dashboard), [])
        self.assertNotIn("eligibility", dashboard["portfolio_fit"])
        self.assertNotIn("constraint_impact", dashboard["portfolio_fit"])

    def test_zero_quantity_record_cannot_retain_positive_weight(self):
        payload = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": "VOO",
                    "quantity": 0,
                    "avg_cost": 600,
                    "currency": "USD",
                    "current_weight": 0.1,
                }
            ],
        }
        errors = validate_portfolio_payload(payload)
        self.assertTrue(
            any("current_weight must be 0 when quantity is 0" in error for error in errors)
        )

    def test_complete_portfolio_batch_audit_requires_exact_active_coverage(self):
        results = [
            {
                "symbol": "AAPL",
                "summary": {"last_close": 110},
                "portfolio_context": {"position_status": "matched"},
            },
            {
                "symbol": "MSFT",
                "summary": {"last_close": 500},
                "portfolio_context": {"position_status": "matched"},
            },
        ]
        audit = build_portfolio_batch_audit(
            results,
            requested_count=2,
            expected_symbols=["AAPL", "MSFT"],
            portfolio_load_status="ok",
        )
        self.assertTrue(audit["complete"])
        self.assertTrue(audit["coverage_complete"])
        self.assertEqual(audit["quote_failed_symbols"], [])
        self.assertEqual(audit["unmatched_symbols"], [])

        incomplete = build_portfolio_batch_audit(
            results[:1],
            requested_count=1,
            expected_symbols=["AAPL", "MSFT"],
            portfolio_load_status="ok",
        )
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["missing_requested_symbols"], ["MSFT"])

    def test_portfolio_quote_universe_excludes_cash_and_inactive_records(self):
        payload = {
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "market_type": "US"},
                {"symbol": "CASH_USD", "quantity": 100, "market_type": "cash"},
                {"symbol": "CASH_CNY", "quantity": 100, "market_type": "cash"},
            ],
            "_inactive_zero_quantity_symbols": ["VOO"],
        }
        self.assertEqual(list_active_non_cash_symbols(payload), ["AAPL"])

    def test_zero_or_negative_price_is_not_a_successful_quote(self):
        for price in (0, -1):
            with self.subTest(price=price):
                result = build_portfolio_batch_audit(
                    [
                        {
                            "symbol": "AAPL",
                            "summary": {"last_close": price},
                            "portfolio_context": {"position_status": "matched"},
                        }
                    ],
                    requested_count=1,
                    expected_symbols=["AAPL"],
                    portfolio_load_status="ok",
                )
                self.assertEqual(result["quote_success_count"], 0)
                self.assertFalse(result["complete"])

    def test_portfolio_batch_audit_requires_quotes_and_position_matches(self):
        results = [
            {
                "symbol": "AAPL",
                "summary": {"last_close": 110},
                "portfolio_context": {"position_status": "matched"},
                "portfolio_summary": {
                    "inactive_zero_quantity_count": 1,
                    "inactive_zero_quantity_symbols": ["VOO"],
                },
            },
            {
                "symbol": "VOO",
                "summary": {"last_close": 700},
                "portfolio_context": {"position_status": "inactive_zero_quantity"},
                "portfolio_summary": {
                    "inactive_zero_quantity_count": 1,
                    "inactive_zero_quantity_symbols": ["VOO"],
                },
            },
        ]
        audit = build_portfolio_batch_audit(results, requested_count=2)
        self.assertEqual(audit["quote_success_count"], 2)
        self.assertEqual(audit["portfolio_matched_count"], 1)
        self.assertEqual(audit["inactive_zero_quantity_symbols"], ["VOO"])
        self.assertFalse(audit["complete"])

    def test_yf_cli_emits_parseable_incomplete_audit_for_invalid_portfolio(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "invalid-portfolio.json"
            path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "AAPL",
                                "quantity": -1,
                                "avg_cost": 100,
                                "currency": "USD",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            argv = [
                "yf.py",
                "AAPL",
                "--with-portfolio",
                "--positions-file",
                str(path),
                "--json",
                "--lean",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(yf_module, "resolve_symbol", return_value="AAPL"),
                patch.object(
                    yf_module,
                    "get_stock_data",
                    return_value=(None, {"currentPrice": 100}, [], []),
                ),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                yf_module.main()

        self.assertEqual(exit_context.exception.code, 1)
        payload = json.loads(output.getvalue())
        audit = payload[0]["portfolio_batch_audit"]
        self.assertEqual(audit["portfolio_load_status"], "invalid_positions_file")
        self.assertFalse(audit["complete"])
        self.assertTrue(audit["portfolio_load_error"])

    def test_yf_cli_structures_non_object_portfolio_failure(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "invalid-root.json"
            path.write_text("[]", encoding="utf-8")
            output = io.StringIO()
            argv = [
                "yf.py",
                "AAPL",
                "--with-portfolio",
                "--positions-file",
                str(path),
                "--json",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(yf_module, "resolve_symbol", return_value="AAPL"),
                patch.object(
                    yf_module,
                    "get_stock_data",
                    return_value=(None, {"currentPrice": 100}, [], []),
                ),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                yf_module.main()
        self.assertEqual(exit_context.exception.code, 1)
        report = json.loads(output.getvalue())[0]["portfolio_batch_audit"]
        self.assertEqual(report["portfolio_load_status"], "invalid_positions_file")
        self.assertIn("portfolio root must be an object", report["portfolio_load_error"])

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

    def test_scenario_rejects_invalid_active_position_values(self):
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {"name": name, "asset_returns": {"AAPL": 0.0}, "assumption_source": "test"}
                for name in ["base", "bull", "bear"]
            ],
        }
        for field, value in [("quantity", -1), ("avg_cost", -1), ("current_weight", 0)]:
            with self.subTest(field=field):
                position = {"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD", "current_weight": 1.0}
                position[field] = value
                result = analyze_scenarios({"base_currency": "USD", "positions": [position]}, assumptions)
                self.assertFalse(result["valid"])
                self.assertTrue(any(field in item for item in result["errors"]))

    def test_scenario_excludes_zero_quantity_audit_record(self):
        portfolio = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": 1,
                    "avg_cost": 100,
                    "currency": "USD",
                    "current_weight": 1.0,
                },
                {
                    "symbol": "VOO",
                    "quantity": 0,
                    "avg_cost": 600,
                    "currency": "USD",
                },
            ],
        }
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {
                    "name": name,
                    "asset_returns": {"AAPL": 0.1},
                    "assumption_source": "test",
                }
                for name in ["base", "bull", "bear"]
            ],
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertTrue(result["valid"])
        self.assertEqual(result["inactive_zero_quantity_symbols"], ["VOO"])
        self.assertEqual(
            result["scenario_results"][0]["position_contributions"],
            {"AAPL": 0.1},
        )

    def test_scenario_rejects_nonzero_weight_on_zero_quantity_record(self):
        portfolio = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": 1,
                    "avg_cost": 100,
                    "currency": "USD",
                    "current_weight": 1.0,
                },
                {
                    "symbol": "VOO",
                    "quantity": 0,
                    "avg_cost": 600,
                    "currency": "USD",
                    "current_weight": 0.1,
                },
            ],
        }
        assumptions = {
            "base_currency": "USD",
            "scenarios": [
                {
                    "name": name,
                    "asset_returns": {"AAPL": 0.1},
                    "assumption_source": "test",
                }
                for name in ["base", "bull", "bear"]
            ],
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("current_weight must be 0 when quantity is 0" in error for error in result["errors"])
        )

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
        self.assertEqual(fit["constraint_status"], "within_configured_weight_range")
        self.assertNotIn("eligibility", fit)
        self.assertNotIn("constraint_impact", fit)

    def test_risk_categories_stay_unknown_without_explicit_profile(self):
        positions = [
            {
                "symbol": "AAPL",
                "current_weight": 1.0,
                "thesis": "quality",
                "days_to_liquidate": 1,
            }
        ]
        summary = build_portfolio_summary(positions)
        risk = build_portfolio_risk(summary)
        self.assertEqual(summary["concentration_bucket"], "unknown")
        self.assertEqual(risk["concentration_risk"], "未知")
        self.assertEqual(risk["market_exposure_risk"], "未知")
        self.assertEqual(risk["risk_profile_status"], "not_configured")

    def test_rebalance_without_policy_does_not_create_targets(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "CASH",
                                "market_type": "cash",
                                "quantity": 100,
                                "avg_cost": 1,
                                "currency": "USD",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = recalculate_all_weights(str(path))
        self.assertFalse(result["_rebalance"]["target_weights_computed"])
        self.assertNotIn("target_weight", result["positions"][0])
        self.assertNotIn("max_weight", result["positions"][0])

    def test_rebalance_excludes_zero_quantity_record_without_fetching_it(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "CASH",
                                "market_type": "CASH",
                                "quantity": 100,
                                "avg_cost": 1,
                                "currency": "USD",
                            },
                            {
                                "symbol": "VOO",
                                "market_type": "US",
                                "quantity": 0,
                                "avg_cost": 600,
                                "currency": "USD",
                                "current_weight": 0,
                                "target_weight": 0.2,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = recalculate_all_weights(str(path))
        inactive = result["positions"][1]
        self.assertEqual(inactive["current_weight"], 0.0)
        self.assertNotIn("target_weight", inactive)
        self.assertNotIn("max_weight", inactive)
        self.assertTrue(
            any("VOO" in warning for warning in result["_rebalance"]["warnings"])
        )

    def test_broker_import_with_missing_required_field_does_not_write(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            positions_path = root / "positions.json"
            csv_path = root / "broker.csv"
            original = json.dumps(
                {
                    "base_currency": "USD",
                    "positions": [
                        {
                            "symbol": "EXISTING",
                            "quantity": 1,
                            "avg_cost": 10,
                            "currency": "USD",
                            "market_type": "US",
                        }
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            positions_path.write_text(original, encoding="utf-8")
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market_type\n"
                "VALID,2,20,USD,US\n"
                "BROKEN,3,30,,US\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                sync_broker_data(str(csv_path), str(positions_path))
            self.assertEqual(positions_path.read_text(encoding="utf-8"), original)

    def test_broker_import_does_not_invent_optional_or_allocation_fields(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            positions_path = root / "positions.json"
            csv_path = root / "broker.csv"
            positions_path.write_text(
                json.dumps({"base_currency": "USD", "positions": []}),
                encoding="utf-8",
            )
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market_type\n"
                "TEST,2,10,USD,US\n",
                encoding="utf-8",
            )
            result = sync_broker_data(str(csv_path), str(positions_path))
            imported = result["positions"][0]
            for field in (
                "name",
                "opened_at",
                "thesis",
                "current_weight",
                "target_weight",
                "max_weight",
            ):
                self.assertNotIn(field, imported)

    def test_broker_zero_quantity_clears_derived_allocation_fields(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            positions_path = root / "positions.json"
            csv_path = root / "broker.csv"
            positions_path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "AAPL",
                                "name": "Apple",
                                "quantity": 2,
                                "avg_cost": 100,
                                "currency": "USD",
                                "market_type": "US",
                                "current_weight": 0.5,
                                "target_weight": 0.4,
                                "max_weight": 0.45,
                                "thesis": "quality",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market_type\n"
                "AAPL,0,100,USD,US\n",
                encoding="utf-8",
            )
            result = sync_broker_data(str(csv_path), str(positions_path))
        position = result["positions"][0]
        self.assertEqual(position["quantity"], 0)
        self.assertEqual(position["current_weight"], 0.0)
        self.assertNotIn("target_weight", position)
        self.assertNotIn("max_weight", position)
        self.assertEqual(position["name"], "Apple")
        self.assertEqual(position["thesis"], "quality")

    def test_zero_cash_update_clears_derived_allocation_fields(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            path = Path(tmpdir) / "positions.json"
            path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "CASH_USD",
                                "name": "Cash",
                                "quantity": 100,
                                "avg_cost": 1,
                                "currency": "USD",
                                "market_type": "CASH",
                                "current_weight": 0.2,
                                "target_weight": 0.1,
                                "max_weight": 0.15,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = sync_broker_data(None, str(path), cash_usd=0)
        cash = result["positions"][0]
        self.assertEqual(cash["quantity"], 0)
        self.assertEqual(cash["current_weight"], 0.0)
        self.assertNotIn("target_weight", cash)
        self.assertNotIn("max_weight", cash)

    def test_broker_update_validates_final_portfolio_before_write(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            positions_path = root / "positions.json"
            csv_path = root / "broker.csv"
            original = json.dumps(
                {"base_currency": "USD", "positions": []},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            positions_path.write_text(original, encoding="utf-8")
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market_type\n"
                "AAPL,1,0,USD,US\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                sync_broker_data(str(csv_path), str(positions_path))
            self.assertEqual(positions_path.read_text(encoding="utf-8"), original)

    def test_portfolio_contract_rejects_duplicates(self):
        payload = {
            "base_currency": "USD",
            "positions": [
                {"symbol": "AAPL", "quantity": 1, "avg_cost": 100, "currency": "USD"},
                {"symbol": "aapl", "quantity": 2, "avg_cost": 90, "currency": "USD"},
            ],
        }
        self.assertTrue(any("duplicate position symbol" in item for item in validate_portfolio_payload(payload)))

    def test_portfolio_contract_rejects_non_object_root(self):
        self.assertEqual(
            validate_portfolio_payload([]),
            ["portfolio root must be an object"],
        )

    def test_missing_cross_currency_rate_fails(self):
        with self.assertRaises(ValueError):
            get_exchange_rate("USD", {"base_currency": "CNY", "exchange_rates": {}})

    def test_missing_cross_currency_rate_fails_contract_validation(self):
        payload = {
            "base_currency": "CNY",
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": 1,
                    "avg_cost": 100,
                    "currency": "USD",
                }
            ],
        }
        self.assertTrue(
            any(
                "missing exchange rate for USD to CNY" in error
                for error in validate_portfolio_payload(payload)
            )
        )

    def test_inactive_cross_currency_record_does_not_require_fx_rate(self):
        payload = {
            "base_currency": "CNY",
            "positions": [
                {
                    "symbol": "600000.SS",
                    "quantity": 1,
                    "avg_cost": 10,
                    "currency": "CNY",
                    "market_type": "A_SHARE",
                },
                {
                    "symbol": "VOO",
                    "quantity": 0,
                    "avg_cost": 600,
                    "currency": "USD",
                    "market_type": "ETF",
                    "current_weight": 0,
                },
            ],
        }
        self.assertEqual(validate_portfolio_payload(payload), [])

    def test_nonpositive_cross_currency_rate_fails_contract_validation(self):
        payload = {
            "base_currency": "CNY",
            "exchange_rates": {"USD": -1},
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": 1,
                    "avg_cost": 100,
                    "currency": "USD",
                }
            ],
        }
        self.assertTrue(
            any("exchange_rates.USD" in error for error in validate_portfolio_payload(payload))
        )


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
        dashboard = valid_dashboard()
        entry = build_journal_entry(dashboard)
        self.assertEqual(entry["benchmark_symbol"], "SPY")
        self.assertEqual(entry["investment_horizon_days"], 90)
        self.assertEqual(len(entry["source_snapshot_hash"]), 64)
        self.assertEqual(entry["research_scope"], "research_only")
        self.assertEqual(entry["dashboard_schema_version"], "6.1")
        for forbidden in (
            "decision_type",
            "operation_advice",
            "position_direction",
            "stop_loss",
            "take_profit",
        ):
            self.assertNotIn(forbidden, entry)


if __name__ == "__main__":
    unittest.main()
