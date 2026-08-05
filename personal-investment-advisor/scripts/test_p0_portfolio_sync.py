import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import daily_sync  # noqa: E402
import yf as yf_module  # noqa: E402
from broker_sync import sync_broker_data  # noqa: E402
from portfolio_loader import (  # noqa: E402
    build_position_context,
    is_cash_position,
    load_positions,
    validate_portfolio_payload,
)
from yf import build_portfolio_batch_audit  # noqa: E402
from quote_evidence_contract import build_portfolio_snapshot_binding  # noqa: E402


NOW_EPOCH = 1_800_000_000.0


def stock_position(**overrides):
    position = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "quantity": 2,
        "avg_cost": 100.0,
        "currency": "USD",
        "market": "US",
        "asset_type": "stock",
    }
    position.update(overrides)
    return position


def portfolio_payload(*positions):
    return {
        "base_currency": "USD",
        "positions": list(positions or (stock_position(),)),
    }


def quote_result(
    symbol="AAPL",
    *,
    exchange="NMS",
    currency="USD",
    quote_type="EQUITY",
):
    return {
        "query": symbol,
        "symbol": symbol,
        "info": {
            "symbol": symbol,
            "regularMarketPrice": 110.1234,
            "exchange": exchange,
            "currency": currency,
            "quoteType": quote_type,
            "regularMarketTime": NOW_EPOCH - 60,
            "marketState": "CLOSED",
        },
        "data_sources": {
            "price": "Yahoo Finance",
            "price_locator": f"yfinance:{symbol}:quote",
        },
        "portfolio_context": {
            "position_status": "matched",
            "current_price": 110.1234,
            "currency": currency,
        },
    }


def strict_audit(result, expected_position):
    symbol = result["symbol"]
    return build_portfolio_batch_audit(
        [result],
        requested_count=1,
        expected_symbols=[symbol],
        portfolio_load_status="ok",
        expected_position_metadata={symbol: expected_position},
        now_epoch=NOW_EPOCH,
    )


def supplied_audit(symbol="AAPL", *, positions=None):
    binding_positions = positions or [stock_position(symbol=symbol)]
    return {
        "requested_count": 1,
        "result_record_count": 1,
        "resolved_symbol_count": 1,
        "unique_resolved_symbol_count": 1,
        "quote_success_count": 1,
        "portfolio_matched_count": 1,
        "quote_contract_matched_count": 1,
        "quote_contract_failures": {},
        "returned_symbols": [symbol],
        "quote_failed_symbols": [],
        "unmatched_symbols": [],
        "duplicate_requested_symbols": [],
        "expected_active_symbols": [symbol],
        "missing_requested_symbols": [],
        "unexpected_requested_symbols": [],
        "result_error_symbols": [],
        "stale_quote_symbols": [],
        "coverage_complete": True,
        "portfolio_load_status": "ok",
        "portfolio_load_error": None,
        "strict_quote_contract": True,
        "portfolio_snapshot_binding": build_portfolio_snapshot_binding(
            {"positions": binding_positions}
        ),
        "complete": True,
        "status": "complete",
    }


class PortfolioIdentityContractTests(unittest.TestCase):
    def test_schema_and_example_use_clean_market_asset_contract(self):
        schema = json.loads(
            (SKILL_DIR / "references" / "portfolio_schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["required_position_fields"],
            ["symbol", "quantity", "avg_cost", "currency", "market", "asset_type"],
        )
        self.assertEqual(schema["allowed_markets"], ["CN", "HK", "US", "CASH"])
        self.assertEqual(
            schema["allowed_asset_types"],
            ["stock", "etf", "fund", "index", "cash", "other"],
        )
        example = json.loads(
            (SKILL_DIR / "references" / "portfolio_positions.example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_portfolio_payload(example), [])
        self.assertNotIn("market_type", example["positions"][0])

    def test_legacy_market_type_cannot_satisfy_identity_contract(self):
        legacy = stock_position()
        legacy.pop("market")
        legacy.pop("asset_type")
        legacy["market_type"] = "US_STOCK"

        errors = validate_portfolio_payload(portfolio_payload(legacy))

        self.assertTrue(any("missing fields: market, asset_type" in item for item in errors))
        self.assertTrue(any(".market must be" in item for item in errors))
        self.assertTrue(any(".asset_type must be" in item for item in errors))

    def test_market_asset_enums_and_cash_identity_fail_closed(self):
        cases = [
            (stock_position(market="美股"), ".market is not allowed"),
            (stock_position(asset_type="equity"), ".asset_type is not allowed"),
            (stock_position(symbol="CASH_USD", market="US", asset_type="cash"), "cash identity"),
            (stock_position(symbol="AAPL", market="CASH", asset_type="cash"), "cash identity"),
            (stock_position(symbol="CASH_USD", market="CASH", asset_type="stock"), "cash identity"),
        ]
        for position, expected in cases:
            with self.subTest(position=position):
                errors = validate_portfolio_payload(portfolio_payload(position))
                self.assertTrue(any(expected in item for item in errors), errors)
                self.assertFalse(is_cash_position(position))

        cash = stock_position(
            symbol="CASH_USD",
            name="USD cash",
            quantity=1_000,
            avg_cost=1.0,
            market="CASH",
            asset_type="cash",
        )
        self.assertEqual(validate_portfolio_payload(portfolio_payload(cash)), [])
        self.assertTrue(is_cash_position(cash))

    def test_zero_quantity_remains_auditable_but_inactive(self):
        inactive = stock_position(quantity=0, current_weight=0.0)
        cash = stock_position(
            symbol="CASH_USD",
            quantity=100,
            avg_cost=1.0,
            market="CASH",
            asset_type="cash",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "positions.json"
            path.write_text(
                json.dumps(portfolio_payload(inactive, cash)), encoding="utf-8"
            )
            loaded = load_positions(str(path))

        self.assertEqual([item["symbol"] for item in loaded["positions"]], ["CASH_USD"])
        self.assertEqual(loaded["_inactive_zero_quantity_symbols"], ["AAPL"])
        context = build_position_context("AAPL", current_price=None, payload=loaded)
        self.assertEqual(context["position_status"], "inactive_zero_quantity")
        self.assertEqual(context["market"], "US")
        self.assertEqual(context["asset_type"], "stock")


class BrokerImportContractTests(unittest.TestCase):
    def _write_positions(self, root):
        path = Path(root) / "positions.json"
        path.write_text(
            json.dumps({"base_currency": "USD", "positions": []}, indent=2),
            encoding="utf-8",
        )
        return path

    def test_broker_requires_market_and_asset_type_and_is_all_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = self._write_positions(tmpdir)
            csv_path = Path(tmpdir) / "broker.csv"
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market,asset_type,market_type\n"
                "AAPL,2,100,USD,US,stock,WRONG_DISPLAY\n"
                "QQQ,3,400,USD,US,,ETF\n",
                encoding="utf-8",
            )
            before = positions_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "missing required field asset_type"):
                sync_broker_data(str(csv_path), str(positions_path))

            self.assertEqual(positions_path.read_bytes(), before)

    def test_broker_persists_clean_identity_and_cash_semantics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = self._write_positions(tmpdir)
            csv_path = Path(tmpdir) / "broker.csv"
            csv_path.write_text(
                "symbol,quantity,avg_cost,currency,market,asset_type,market_type\n"
                "AAPL,2,100,usd,us,stock,WRONG_DISPLAY\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                synced = sync_broker_data(
                    str(csv_path), str(positions_path), cash_usd=50
                )

        by_symbol = {item["symbol"]: item for item in synced["positions"]}
        self.assertEqual(by_symbol["AAPL"]["market"], "US")
        self.assertEqual(by_symbol["AAPL"]["asset_type"], "stock")
        self.assertNotIn("market_type", by_symbol["AAPL"])
        self.assertEqual(by_symbol["CASH_USD"]["market"], "CASH")
        self.assertEqual(by_symbol["CASH_USD"]["asset_type"], "cash")


class StrictQuoteIdentityTests(unittest.TestCase):
    def test_yf_daily_sync_closes_clean_portfolio_batch(self):
        info = quote_result()["info"]
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = Path(tmpdir) / "positions.json"
            positions_path.write_text(
                json.dumps(portfolio_payload(stock_position())), encoding="utf-8"
            )
            output = io.StringIO()
            argv = [
                "yf.py",
                "AAPL",
                "--daily-sync",
                "--positions-file",
                str(positions_path),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch(
                    "yf.resolve_symbol",
                    side_effect=AssertionError(
                        "Daily Sync must use the validated portfolio symbol"
                    ),
                ),
                patch("yf.get_stock_data", return_value=(None, info, [], [])),
                patch("yf.time.time", return_value=NOW_EPOCH),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                yf_module.main()

        result = json.loads(output.getvalue())
        self.assertEqual(exit_context.exception.code, 0)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["portfolio_batch_audit"]["complete"])
        self.assertEqual(
            result["portfolio_batch_audit"]["quote_contract_matched_count"], 1
        )
        self.assertEqual(result["records"][0]["portfolio_context"]["market"], "US")
        self.assertEqual(
            result["records"][0]["portfolio_context"]["asset_type"], "stock"
        )

    def test_explicit_market_and_asset_type_close_identity(self):
        audit = strict_audit(quote_result(), stock_position())
        self.assertTrue(audit["complete"])
        self.assertTrue(audit["strict_quote_contract"])

    def test_legacy_metadata_and_symbol_shape_cannot_replace_explicit_identity(self):
        legacy = {
            "symbol": "AAPL",
            "currency": "USD",
            "market_type": "US_STOCK",
            "name": "Apple stock",
        }

        audit = strict_audit(quote_result(), legacy)

        self.assertFalse(audit["complete"])
        self.assertIn("missing_position.market", audit["quote_contract_failures"]["AAPL"])
        self.assertIn(
            "missing_position.asset_type",
            audit["quote_contract_failures"]["AAPL"],
        )

    def test_legacy_market_type_cannot_override_explicit_market(self):
        expected = stock_position(market="CN", market_type="US_STOCK")

        audit = strict_audit(quote_result(exchange="NMS"), expected)

        self.assertFalse(audit["complete"])
        self.assertIn("identity_mismatch.exchange", audit["quote_contract_failures"]["AAPL"])

    def test_explicit_asset_type_controls_provider_quote_type(self):
        audit = strict_audit(quote_result(quote_type="ETF"), stock_position())
        self.assertFalse(audit["complete"])
        self.assertIn("identity_mismatch.quoteType", audit["quote_contract_failures"]["AAPL"])

    def test_cn_etf_provider_alias_requires_explicit_cn_etf_contract(self):
        symbol = "159516.SZ"
        result = quote_result(
            symbol=symbol,
            exchange="SHZ",
            currency="CNY",
            quote_type="EQUITY",
        )
        expected = stock_position(
            symbol=symbol,
            currency="CNY",
            market="CN",
            asset_type="etf",
        )

        audit = strict_audit(result, expected)

        self.assertTrue(audit["complete"])
        self.assertEqual(
            audit["quote_contract_warnings"][symbol],
            ["provider_quote_type_alias.cn_etf_as_equity"],
        )


class DailySyncWorkflowTests(unittest.TestCase):
    def test_legacy_list_and_inline_audit_packages_are_rejected(self):
        positions = portfolio_payload(stock_position())
        record = quote_result()
        packages = [
            (
                "list_root",
                [{**record, "portfolio_batch_audit": supplied_audit()}],
            ),
        ]
        for label, inline_value in (
            ("dict", supplied_audit()),
            ("null", None),
            ("string", "legacy"),
            ("list", []),
        ):
            packages.append(
                (
                    f"inline_{label}",
                    {
                        "records": [
                            {**record, "portfolio_batch_audit": inline_value}
                        ],
                        "portfolio_batch_audit": supplied_audit(),
                    },
                )
            )
        for label, package in packages:
            with self.subTest(package=label), tempfile.TemporaryDirectory() as tmpdir:
                positions_path = Path(tmpdir) / "positions.json"
                quotes_path = Path(tmpdir) / "quotes.json"
                positions_path.write_text(json.dumps(positions), encoding="utf-8")
                quotes_path.write_text(json.dumps(package), encoding="utf-8")

                report = daily_sync.evaluate_daily_sync(
                    positions_file=str(positions_path),
                    quotes_file=str(quotes_path),
                    now_epoch=NOW_EPOCH,
                )

            self.assertFalse(report["completeness"]["complete"])
            self.assertEqual(report["status"], "incomplete")
            self.assertTrue(report["stages"][1]["errors"])

    def test_quote_batch_can_close_but_workflow_waits_for_thesis_red_team(self):
        positions = portfolio_payload(
            stock_position(),
            stock_position(
                symbol="CASH_USD",
                quantity=100,
                avg_cost=1.0,
                market="CASH",
                asset_type="cash",
            ),
            stock_position(symbol="VOO", quantity=0, current_weight=0.0, asset_type="etf"),
        )
        quotes = {
            "records": [quote_result()],
            "portfolio_batch_audit": supplied_audit(
                positions=[
                    position
                    for position in positions["positions"]
                    if position["quantity"] > 0
                ]
            ),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = Path(tmpdir) / "positions.json"
            quotes_path = Path(tmpdir) / "quotes.json"
            positions_path.write_text(json.dumps(positions), encoding="utf-8")
            quotes_path.write_text(json.dumps(quotes), encoding="utf-8")
            report = daily_sync.evaluate_daily_sync(
                positions_file=str(positions_path),
                quotes_file=str(quotes_path),
                now_epoch=NOW_EPOCH,
            )
            output = io.StringIO()
            argv = [
                "daily_sync.py",
                "--positions-file",
                str(positions_path),
                "--quotes-file",
                str(quotes_path),
                "--now-epoch",
                str(NOW_EPOCH),
            ]
            with (
                patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                daily_sync.main()
            cli_report = json.loads(output.getvalue())

        self.assertTrue(report["completeness"]["complete"])
        self.assertFalse(report["completeness"]["thesis_assessment_complete"])
        self.assertEqual(report["stages"][3]["status"], "complete")
        self.assertEqual(report["thesis_red_team"]["status"], "not_assessed")
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("thesis_red_team_incomplete", report["errors"])
        self.assertEqual(report["requested"], 1)
        self.assertEqual(report["quote_snapshot"][0]["position_market"], "US")
        self.assertEqual(report["quote_snapshot"][0]["position_asset_type"], "stock")
        self.assertNotIn("position_market_type", report["quote_snapshot"][0])
        self.assertEqual(exit_context.exception.code, 1)
        self.assertEqual(cli_report["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
