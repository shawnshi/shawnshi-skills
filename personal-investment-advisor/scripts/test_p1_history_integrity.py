import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from history_integrity_gate import evaluate_history_integrity, main as history_gate_main
from yf import detect_market_type, history_integrity_decision, main as yf_main


def event(factor="2:1"):
    return {
        "event_type": "split",
        "effective_date": "2026-07-15",
        "factor": factor,
    }


def packet(*, official=None, provider=None, result_count=1, control_count=2):
    return {
        "symbol": "159516.SZ",
        "asset_type": "etf",
        "as_of_date": "2026-07-31",
        "official_coverage": {
            "source_locator": "https://www.szse.cn/disclosure/fund/notice/index.html",
            "retrieved_at": "2026-07-31T10:00:00+08:00",
            "coverage_status": "complete",
            "result_count": result_count,
            "control_query_count": control_count,
        },
        "official_events": [event()] if official is None else official,
        "provider_events": [event()] if provider is None else provider,
        "provider_source": "Yahoo Finance",
        "provider_source_locator": "yfinance:159516.SZ:history",
        "provider_adjustment": "provider_default",
    }


def history_frame(*, end="2026-07-31"):
    history = pd.DataFrame(
        {
            "Open": [1.0, 1.1],
            "High": [1.2, 1.3],
            "Low": [0.9, 1.0],
            "Close": [1.1, 1.2],
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2026-07-30", end]),
    )
    history.index.name = "Date"
    history.attrs["pia_source"] = "Yahoo Finance"
    history.attrs["pia_source_locator"] = "yfinance:159516.SZ:history"
    history.attrs["pia_adjustment"] = "provider_default"
    return history


class HistoryIntegrityContractTests(unittest.TestCase):
    def test_matching_events_verify_packet_but_do_not_authorize_unbound_series(self):
        report = evaluate_history_integrity(packet())
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["detail_status"], "packet_verified")
        self.assertTrue(report["packet_verified"])
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertEqual(report["authorization_scope"], "packet_only")

    def test_standalone_cli_success_is_packet_only_not_metric_authority(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = Path(tmpdir) / "packet.json"
            packet_path.write_text(json.dumps(packet()), encoding="utf-8")
            with (
                patch.object(
                    sys,
                    "argv",
                    ["history_integrity_gate.py", str(packet_path)],
                ),
                redirect_stdout(stdout),
            ):
                exit_code = history_gate_main()

        report = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["packet_verified"])
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertEqual(report["authorization_scope"], "packet_only")

    def test_event_mismatch_blocks_metrics(self):
        report = evaluate_history_integrity(packet(provider=[event("10:1")]))
        self.assertEqual(report["status"], "invalid")
        self.assertEqual(report["detail_status"], "corporate_action_conflict")
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertTrue(report["event_mismatches"])

    def test_stale_coverage_and_future_events_fail_closed(self):
        stale = packet(official=[], provider=[], result_count=0, control_count=2)
        stale["as_of_date"] = "2026-08-02"
        stale["official_coverage"]["retrieved_at"] = "2025-01-01T10:00:00+08:00"
        report = evaluate_history_integrity(stale)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertIn(
            "official_coverage.retrieved_at cannot be before as_of_date",
            report["errors"],
        )

        future = packet()
        future["official_events"][0]["effective_date"] = "2099-01-01"
        future["provider_events"][0]["effective_date"] = "2099-01-01"
        report = evaluate_history_integrity(future)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertTrue(
            any("effective_date cannot be after as_of_date" in error for error in report["errors"])
        )

    def test_zero_results_require_a_nonzero_control_query(self):
        report = evaluate_history_integrity(
            packet(official=[], provider=[], result_count=0, control_count=0)
        )
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["technical_metrics_allowed"])
        self.assertIn("zero_result_control_missing", report["errors"])

    def test_etf_history_is_blocked_without_verified_packet(self):
        blocked = history_integrity_decision(
            "159516.SZ",
            {"quoteType": "EQUITY"},
            {"market": "CN", "asset_type": "etf", "name": "半导体设备ETF国泰"},
            {},
        )
        self.assertFalse(blocked["technical_metrics_allowed"])
        self.assertEqual(blocked["status"], "insufficient_data")

        verified_packet = packet()
        allowed = history_integrity_decision(
            "159516.SZ",
            {"quoteType": "EQUITY"},
            {"market": "CN", "asset_type": "etf", "name": "半导体设备ETF国泰"},
            {"159516.SZ": verified_packet},
            history_frame(),
        )
        self.assertTrue(allowed["technical_metrics_allowed"])
        self.assertEqual(allowed["detail_status"], "series_bound_verified")
        self.assertEqual(
            allowed["authorization_scope"], "packet_and_runtime_series"
        )
        self.assertEqual(allowed["history_binding"]["history_end_date"], "2026-07-31")

    def test_verified_packet_must_bind_to_exact_history_series(self):
        verified_packet = packet()
        future_history = history_frame(end="2026-08-01")
        blocked = history_integrity_decision(
            "159516.SZ",
            {"quoteType": "EQUITY"},
            {"market": "CN", "asset_type": "etf", "name": "半导体设备ETF国泰"},
            {"159516.SZ": verified_packet},
            future_history,
        )
        self.assertFalse(blocked["technical_metrics_allowed"])
        self.assertEqual(blocked["detail_status"], "history_series_binding_mismatch")
        self.assertIn(
            "history_integrity_packet_does_not_cover_series_end",
            blocked["errors"],
        )

        wrong_source = history_frame()
        wrong_source.attrs["pia_source_locator"] = "akshare:stock_zh_a_hist"
        blocked = history_integrity_decision(
            "159516.SZ",
            {"quoteType": "EQUITY"},
            {"market": "CN", "asset_type": "etf", "name": "半导体设备ETF国泰"},
            {"159516.SZ": verified_packet},
            wrong_source,
        )
        self.assertFalse(blocked["technical_metrics_allowed"])
        self.assertIn(
            "history_integrity_provider_source_locator_mismatch",
            blocked["errors"],
        )

    def test_cn_etf_name_blocks_metrics_even_without_portfolio_context(self):
        report = history_integrity_decision(
            "159516.SZ",
            {
                "quoteType": "EQUITY",
                "longName": "国泰中证半导体材料设备主题交易型开放式指数证券投资基金",
                "shortName": "半导体设备ETF国泰",
            },
            None,
            {},
        )
        self.assertEqual(report["status"], "insufficient_data")
        self.assertFalse(report["technical_metrics_allowed"])

    def test_cn_etf_provider_equity_without_bound_identity_fails_closed(self):
        report = history_integrity_decision(
            "159516.SZ",
            {"quoteType": "EQUITY"},
            None,
            {},
        )
        self.assertEqual(report["status"], "insufficient_evidence")
        self.assertEqual(report["detail_status"], "asset_identity_unknown")
        self.assertFalse(report["technical_metrics_allowed"])

    def test_operating_company_history_is_not_subject_to_etf_gate(self):
        report = history_integrity_decision(
            "AAPL",
            {"quoteType": "EQUITY"},
            {"market": "US", "asset_type": "stock", "name": "Apple Inc."},
            {},
        )
        self.assertEqual(report["status"], "not_applicable")
        self.assertEqual(report["detail_status"], "verified_non_etf_identity")
        self.assertTrue(report["technical_metrics_allowed"])

    def test_currency_history_uses_unambiguous_provider_identity(self):
        report = history_integrity_decision(
            "CNY=X",
            {},
            None,
            {},
            history_frame(),
        )
        self.assertEqual(report["status"], "not_applicable")
        self.assertEqual(
            report["detail_status"],
            "verified_non_etf_provider_identity",
        )
        self.assertTrue(report["technical_metrics_allowed"])
        self.assertEqual(detect_market_type("CNY=X"), "外汇")

    def test_price_only_empty_identity_fails_closed(self):
        history = history_frame()
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["yf.py", "QQQ", "--json", "--price-only"]),
            patch("yf.resolve_symbol", return_value="QQQ"),
            patch(
                "yf.get_stock_data", return_value=(history, {}, [], [])
            ) as mocked_fetch,
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf_main()

        self.assertEqual(raised.exception.code, 1)
        self.assertTrue(mocked_fetch.call_args.kwargs["fetch_info"])
        record = json.loads(stdout.getvalue())[0]
        self.assertEqual(record["history"], [])
        self.assertIsNone(record["summary"])
        self.assertTrue(record["history_suppressed"])
        self.assertEqual(record["history_integrity"]["status"], "insufficient_evidence")
        self.assertEqual(
            record["history_integrity"]["detail_status"], "asset_identity_unknown"
        )

    def test_price_only_allows_operating_company_with_bound_identity(self):
        history = history_frame()
        info = {
            "symbol": "AAPL",
            "quoteType": "EQUITY",
            "longName": "Apple Inc.",
            "regularMarketPrice": 200.0,
        }
        stdout = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "yf.py",
                    "AAPL",
                    "--json",
                    "--price-only",
                    "--market",
                    "US",
                    "--asset-type",
                    "stock",
                ],
            ),
            patch("yf.resolve_symbol", return_value="AAPL"),
            patch(
                "yf.get_stock_data", return_value=(history, info, [], [])
            ) as mocked_fetch,
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf_main()

        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(mocked_fetch.call_args.kwargs["fetch_info"])
        record = json.loads(stdout.getvalue())[0]
        self.assertFalse(record.get("history_suppressed", False))
        self.assertEqual(len(record["history"]), 2)
        self.assertIsNotNone(record["summary"])
        self.assertEqual(record["history_integrity"]["status"], "not_applicable")
        self.assertEqual(
            record["history_integrity"]["detail_status"],
            "verified_non_etf_identity",
        )

    def test_cli_suppresses_etf_history_and_summary_without_packet(self):
        history = history_frame()
        info = {
            "symbol": "QQQ",
            "quoteType": "ETF",
            "regularMarketPrice": 1.2,
        }
        stdout = io.StringIO()
        with (
            patch.object(sys, "argv", ["yf.py", "QQQ", "--json", "--price-only"]),
            patch("yf.resolve_symbol", return_value="QQQ"),
            patch("yf.get_stock_data", return_value=(history, info, [], [])),
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf_main()

        self.assertEqual(raised.exception.code, 1)
        record = json.loads(stdout.getvalue())[0]
        self.assertEqual(record["history"], [])
        self.assertIsNone(record["summary"])
        self.assertTrue(record["history_suppressed"])
        self.assertEqual(record["history_integrity"]["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
