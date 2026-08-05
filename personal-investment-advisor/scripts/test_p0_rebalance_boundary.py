import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rebalance_optimizer import run_inverse_volatility_experiment
from rebalance_weights import recalculate_all_weights
from portfolio_loader import load_positions
from quote_evidence_contract import (
    build_portfolio_snapshot_binding,
    canonical_json_binding,
)


def stock(symbol, *, quantity=1, currency="USD", market="US"):
    return {
        "symbol": symbol,
        "quantity": quantity,
        "avg_cost": 10,
        "currency": currency,
        "market": market,
        "asset_type": "stock",
    }


def cash(*, quantity=100, currency="USD"):
    return {
        "symbol": "CASH",
        "quantity": quantity,
        "avg_cost": 1,
        "currency": currency,
        "market": "CASH",
        "asset_type": "cash",
    }


def daily_sync_report(positions_path, snapshots):
    symbols = sorted(snapshot["symbol"] for snapshot in snapshots)
    raw_quotes_path = Path(positions_path).with_name("raw-quotes.json").resolve()
    raw_quotes = {"records": [], "portfolio_batch_audit": {}}
    raw_quotes_path.write_text(json.dumps(raw_quotes), encoding="utf-8")
    portfolio_binding = build_portfolio_snapshot_binding(
        load_positions(str(positions_path))
    )
    return {
        "schema_version": "pia_daily_sync_offline_v3",
        "status": "incomplete",
        "decision_scope": "research_only",
        "operation_mode": "read_only_offline",
        "evaluation_epoch": 1785859200,
        "inputs": {
            "positions_file": str(Path(positions_path).resolve()),
            "quotes_file": str(raw_quotes_path),
        },
        "stages": [
            {"stage": "positions_validation", "status": "complete"},
            {"stage": "quote_package_validation", "status": "complete"},
            {"stage": "quote_contract_validation", "status": "complete"},
            {"stage": "completeness", "status": "complete"},
            {"stage": "thesis_red_team", "status": "not_assessed"},
        ],
        "completeness": {"complete": True},
        "recomputed_portfolio_batch_audit": {
            "complete": True,
            "strict_quote_contract": True,
            "expected_active_symbols": symbols,
            "quote_contract_failures": {},
            "quote_failed_symbols": [],
            "result_error_symbols": [],
            "stale_quote_symbols": [],
            "unmatched_symbols": [],
        },
        "quote_snapshot": snapshots,
        "input_bindings": {
            "portfolio_snapshot": portfolio_binding,
            "quote_package": canonical_json_binding(raw_quotes),
            "quote_snapshot": canonical_json_binding(snapshots),
        },
        "errors": ["thesis_red_team_incomplete"],
    }


def quote_snapshot(position, price):
    symbol = position["symbol"]
    return {
        "symbol": symbol,
        "current_price": price,
        "currency": position["currency"],
        "position_currency": position["currency"],
        "position_market": position["market"],
        "position_asset_type": position["asset_type"],
        "market_state": "CLOSED",
        "identity_status": "matched",
        "identity_errors": [],
        "record_status": "success",
        "as_of": "2026-08-04T08:00:00Z",
        "quote_age_seconds": 28800,
        "source": "Yahoo Finance",
        "source_locator": f"yfinance:{symbol}:quote",
    }


def valid_policy():
    return {
        "schema_version": "pia_inverse_volatility_policy_v1",
        "experiment": "inverse_volatility_allocation",
        "decision_scope": "research_only",
        "as_of": "2026-08-04",
        "bucket_targets": {"risk_assets": 0.8, "reserve": 0.2},
        "bucket_members": {"risk_assets": ["AAPL", "MSFT"], "reserve": ["CASH"]},
        "volatility_observations": {
            "AAPL": {
                "annualized_volatility": 0.4,
                "observation_count": 252,
                "window_start": "2025-08-04",
                "window_end": "2026-08-03",
                "as_of": "2026-08-04",
                "source": "validated_total_return_dataset",
                "source_locator": "dataset://aapl",
            },
            "MSFT": {
                "annualized_volatility": 0.2,
                "observation_count": 252,
                "window_start": "2025-08-04",
                "window_end": "2026-08-03",
                "as_of": "2026-08-04",
                "source": "validated_total_return_dataset",
                "source_locator": "dataset://msft",
            },
        },
    }


class RebalanceBoundaryTests(unittest.TestCase):
    def write_json(self, root, name, payload):
        path = Path(root) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_current_weights_use_validated_daily_sync_report_and_do_not_mutate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL", quantity=2)
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl, cash(quantity=100)]},
            )
            original = portfolio_path.read_bytes()
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)]),
            )
            result = recalculate_all_weights(
                str(portfolio_path), quotes_file=str(report_path), now_epoch=1785859200
            )
            self.assertEqual(result["status"], "complete")
            self.assertTrue(result["research_only"])
            self.assertFalse(result["mutation_performed"])
            self.assertEqual(portfolio_path.read_bytes(), original)
            weights = {row["symbol"]: row["current_weight"] for row in result["current_weights"]}
            self.assertEqual(weights, {"AAPL": 0.5, "CASH": 0.5})
            serialized = json.dumps(result)
            self.assertNotIn("target_weight", serialized)
            self.assertNotIn("max_weight", serialized)

    def test_non_cash_current_weights_fail_closed_without_daily_sync_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [stock("AAPL")]},
            )
            result = recalculate_all_weights(str(portfolio_path))
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["detail_status"], "validated_daily_sync_report_required")
        self.assertTrue(result["fail_closed"]["triggered"])

    def test_raw_quote_package_cannot_masquerade_as_daily_sync_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            quote_path = self.write_json(
                tmpdir,
                "quotes.json",
                {"records": [], "portfolio_batch_audit": {"complete": True}},
            )
            result = recalculate_all_weights(
                str(portfolio_path), quotes_file=str(quote_path), now_epoch=1785859200
            )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["detail_status"], "daily_sync_quote_contract_failed")

    def test_v2_daily_sync_archive_is_not_accepted_for_weight_calculation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            payload = daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)])
            payload["schema_version"] = "pia_daily_sync_offline_v2"
            report_path = self.write_json(tmpdir, "daily-sync-v2.json", payload)
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200,
            )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn(
            "daily_sync_report.schema_version must equal pia_daily_sync_offline_v3",
            result["errors"],
        )

    def test_current_runtime_path_rechecks_the_same_bindings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            payload = daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)])
            report_path = self.write_json(tmpdir, "daily-sync.json", payload)
            Path(payload["inputs"]["quotes_file"]).write_text(
                json.dumps({"changed": "after-daily-sync"}), encoding="utf-8"
            )
            with patch("rebalance_weights.time.time", return_value=1785859200):
                result = recalculate_all_weights(
                    str(portfolio_path), quotes_file=str(report_path)
                )

        self.assertEqual(result["time_basis"], "current_runtime")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn(
            "daily_sync_report quote package binding does not match current input",
            result["errors"],
        )

    def test_malformed_daily_sync_audit_fails_as_structured_evidence_gap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            payload = daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)])
            payload["recomputed_portfolio_batch_audit"]["expected_active_symbols"] = None
            quote_path = self.write_json(tmpdir, "daily-sync.json", payload)
            result = recalculate_all_weights(
                str(portfolio_path), quotes_file=str(quote_path), now_epoch=1785859200
            )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertTrue(any("expected_active_symbols" in error for error in result["errors"]))

    def test_daily_sync_report_cannot_be_replayed_as_current_after_freshness_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)]),
            )
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200 + 901,
            )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn(
            "daily_sync_report is stale for current-weight calculation",
            result["errors"],
        )
        self.assertEqual(result["time_basis"], "explicit_point_in_time_replay")

    def test_market_state_age_is_recomputed_even_when_audit_claims_no_stale_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            snapshot = quote_snapshot(aapl, 50)
            snapshot.update(
                {
                    "market_state": "REGULAR",
                    "as_of": "2026-08-04T15:44:59Z",
                    "quote_age_seconds": 901,
                }
            )
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [snapshot]),
            )
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200,
            )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn("AAPL: quote is stale for market_state REGULAR", result["errors"])

    def test_missing_or_unknown_market_state_and_excess_future_skew_fail_closed(self):
        cases = [
            (None, "2026-08-04T16:00:00Z", 0, "market_state is missing"),
            ("HALTED", "2026-08-04T16:00:00Z", 0, "market_state is unknown"),
            (
                "CLOSED",
                "2026-08-04T17:00:01Z",
                -3601,
                "exceeds allowed future skew",
            ),
        ]
        for state, as_of, age, expected_error in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmpdir:
                aapl = stock("AAPL")
                portfolio_path = self.write_json(
                    tmpdir,
                    "portfolio.json",
                    {"base_currency": "USD", "positions": [aapl]},
                )
                snapshot = quote_snapshot(aapl, 50)
                snapshot.update(
                    {
                        "market_state": state,
                        "as_of": as_of,
                        "quote_age_seconds": age,
                    }
                )
                report_path = self.write_json(
                    tmpdir,
                    "daily-sync.json",
                    daily_sync_report(portfolio_path, [snapshot]),
                )
                result = recalculate_all_weights(
                    str(portfolio_path),
                    quotes_file=str(report_path),
                    now_epoch=1785859200,
                )
            self.assertTrue(
                any(expected_error in error for error in result["errors"]),
                result["errors"],
            )

    def test_same_path_quantity_change_breaks_portfolio_snapshot_binding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL", quantity=1)
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)]),
            )
            aapl["quantity"] = 3
            portfolio_path.write_text(
                json.dumps({"base_currency": "USD", "positions": [aapl]}),
                encoding="utf-8",
            )
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200,
            )

        self.assertNotEqual(result["status"], "complete")
        self.assertTrue(
            any("portfolio snapshot" in error for error in result["errors"]),
            result["errors"],
        )

    def test_same_path_quote_package_change_breaks_input_binding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            aapl = stock("AAPL")
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {"base_currency": "USD", "positions": [aapl]},
            )
            payload = daily_sync_report(portfolio_path, [quote_snapshot(aapl, 50)])
            report_path = self.write_json(tmpdir, "daily-sync.json", payload)
            raw_quote_path = Path(payload["inputs"]["quotes_file"])
            raw_quote_path.write_text(json.dumps({"tampered": True}), encoding="utf-8")
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200,
            )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIn(
            "daily_sync_report quote package binding does not match current input",
            result["errors"],
        )

    def test_stale_fx_snapshot_fails_current_weight_calculation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            holding = stock("0700.HK", currency="HKD", market="HK")
            payload = {
                "base_currency": "USD",
                "exchange_rates": {"HKD": 0.128},
                "exchange_rate_metadata": {
                    "HKD": {
                        "pair": "HKD/USD",
                        "as_of": "2026-07-01",
                        "source": "central_bank_reference_rate",
                        "source_locator": "central-bank://hkd-usd/2026-07-01",
                        "retrieved_at": "2026-07-01T09:00:00Z",
                    }
                },
                "positions": [holding],
            }
            portfolio_path = self.write_json(tmpdir, "portfolio.json", payload)
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [quote_snapshot(holding, 100)]),
            )
            result = recalculate_all_weights(
                str(portfolio_path),
                quotes_file=str(report_path),
                now_epoch=1785859200,
            )

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertTrue(any("snapshot is stale" in error for error in result["errors"]))

    def test_cross_currency_requires_dated_source_labelled_fx(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sap = stock("0700.HK", currency="HKD", market="HK")
            payload = {
                "base_currency": "USD",
                "exchange_rates": {"HKD": 0.128},
                "positions": [sap],
            }
            portfolio_path = self.write_json(tmpdir, "portfolio.json", payload)
            report_path = self.write_json(
                tmpdir,
                "daily-sync.json",
                daily_sync_report(portfolio_path, [quote_snapshot(sap, 100)]),
            )
            failed = recalculate_all_weights(
                str(portfolio_path), quotes_file=str(report_path), now_epoch=1785859200
            )
            self.assertEqual(failed["status"], "insufficient_evidence")
            self.assertEqual(failed["detail_status"], "market_value_evidence_incomplete")

            payload["exchange_rate_metadata"] = {
                "HKD": {
                    "pair": "HKD/USD",
                    "as_of": "2026-08-04",
                    "source": "central_bank_reference_rate",
                    "source_locator": "central-bank://hkd-usd/2026-08-04",
                    "retrieved_at": "2026-08-04T09:00:00Z",
                }
            }
            portfolio_path.write_text(json.dumps(payload), encoding="utf-8")
            passed = recalculate_all_weights(
                str(portfolio_path), quotes_file=str(report_path), now_epoch=1785859200
            )
        self.assertEqual(passed["status"], "complete")
        self.assertEqual(
            passed["current_weights"][0]["fx_to_base"]["data_status"],
            "dated_snapshot",
        )

    def test_policy_root_error_is_structured_and_fail_closed(self):
        result = run_inverse_volatility_experiment(
            [stock("AAPL")], ["not", "an", "object"]
        )
        self.assertEqual(result["status"], "invalid_input")
        self.assertEqual(result["detail_status"], "policy_validation_failed")
        self.assertIn("policy root must be an object", result["errors"])
        self.assertTrue(result["fail_closed"]["triggered"])

    def test_embedded_legacy_rebalance_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            portfolio_path = self.write_json(
                tmpdir,
                "portfolio.json",
                {
                    "base_currency": "USD",
                    "positions": [cash()],
                    "rebalance_policy": {
                        "bucket_targets": {"reserve": 1.0},
                        "max_weight_buffer": 0.01,
                        "history_period": "1y",
                        "min_history_points": 20,
                    },
                },
            )
            result = recalculate_all_weights(str(portfolio_path))
        self.assertEqual(result["status"], "invalid_input")
        self.assertEqual(result["detail_status"], "embedded_rebalance_policy_prohibited")

    def test_inverse_volatility_is_named_as_research_experiment(self):
        result = run_inverse_volatility_experiment(
            [stock("AAPL"), stock("MSFT"), cash()], valid_policy()
        )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["method"], "inverse_volatility_allocation")
        self.assertFalse(result["risk_parity_claim"])
        self.assertTrue(result["research_only"])
        weights = {
            item["symbol"]: item["experimental_weight"]
            for item in result["experimental_weights"]
        }
        self.assertAlmostEqual(weights["AAPL"], 0.8 / 3, places=9)
        self.assertAlmostEqual(weights["MSFT"], 1.6 / 3, places=9)
        self.assertEqual(weights["CASH"], 0.2)

    def test_volatility_evidence_must_have_source_locator(self):
        policy = valid_policy()
        policy["volatility_observations"]["AAPL"]["source_locator"] = ""
        result = run_inverse_volatility_experiment(
            [stock("AAPL"), stock("MSFT"), cash()], policy
        )
        self.assertEqual(result["status"], "invalid_input")
        self.assertTrue(
            any("source_locator" in error for error in result["errors"])
        )

    def test_future_or_reserved_volatility_evidence_is_rejected(self):
        future = valid_policy()
        future["as_of"] = "2099-01-01"
        result = run_inverse_volatility_experiment(
            [stock("AAPL"), stock("MSFT"), cash()],
            future,
            today=date(2026, 8, 5),
        )
        self.assertEqual(result["status"], "invalid_input")
        self.assertIn("policy.as_of cannot be in the future", result["errors"])

        reserved = valid_policy()
        reserved["volatility_observations"]["AAPL"]["source_locator"] = (
            "https://example.test/aapl"
        )
        result = run_inverse_volatility_experiment(
            [stock("AAPL"), stock("MSFT"), cash()],
            reserved,
            today=date(2026, 8, 5),
        )
        self.assertTrue(any("reserved test locator" in error for error in result["errors"]))

    def test_cli_has_no_write_switch_and_source_has_no_network_client(self):
        script_dir = Path(__file__).resolve().parent
        for name in ("rebalance_weights.py", "rebalance_optimizer.py"):
            source = (script_dir / name).read_text(encoding="utf-8")
            self.assertNotIn("import yfinance", source)
            self.assertNotIn("import pandas", source)
            self.assertNotIn("requests.", source)
            self.assertNotIn('"--write"', source)
        process = subprocess.run(
            [sys.executable, str(script_dir / "rebalance_weights.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0)
        self.assertNotIn("--write", process.stdout)


if __name__ == "__main__":
    unittest.main()
