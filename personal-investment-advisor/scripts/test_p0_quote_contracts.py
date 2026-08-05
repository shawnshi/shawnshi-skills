import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portfolio_loader import build_position_context
from yf import build_portfolio_batch_audit, select_portfolio_current_price
import yf as yf_module


NOW_EPOCH = 1_800_000_000.0


def quote_result(
    symbol="AAPL",
    *,
    exchange="NMS",
    currency="USD",
    quote_type="EQUITY",
    quote_epoch=NOW_EPOCH - 60,
    market_state="CLOSED",
    errors=None,
):
    result = {
        "symbol": symbol,
        "summary": {"last_close": 110.12},
        "info": {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "quoteType": quote_type,
            "regularMarketPrice": 110.1234,
            "regularMarketTime": quote_epoch,
            "marketState": market_state,
        },
        "portfolio_context": {"position_status": "matched"},
    }
    if errors is not None:
        result["errors"] = errors
    return result


def expected_position(
    symbol="AAPL",
    *,
    currency="USD",
    market="US",
    asset_type="stock",
    name="Apple Inc.",
):
    return {
        "symbol": symbol,
        "currency": currency,
        "market": market,
        "asset_type": asset_type,
        "name": name,
    }


def strict_audit(result, position, *, now_epoch=NOW_EPOCH):
    symbol = result["symbol"]
    return build_portfolio_batch_audit(
        [result],
        requested_count=1,
        expected_symbols=[symbol],
        portfolio_load_status="ok",
        expected_position_metadata={symbol: position},
        now_epoch=now_epoch,
    )


class RawPricePrecisionTests(unittest.TestCase):
    def test_portfolio_valuation_uses_unrounded_history_close(self):
        history = pd.DataFrame({"Close": [3.02, 3.033]})
        price = select_portfolio_current_price(history, {})
        position = {
            "symbol": "510050.SS",
            "name": "上证50ETF华夏",
            "quantity": 87_300,
            "avg_cost": 3.028,
            "currency": "CNY",
            "market": "CN",
            "asset_type": "etf",
        }
        payload = {
            "_status": "ok",
            "_path": "portfolio.json",
            "_positions_dict": {"510050.SS": position},
            "positions": [position],
            "base_currency": "CNY",
            "exchange_rates": {},
        }

        context = build_position_context(
            "510050.SS", current_price=price, payload=payload
        )

        self.assertEqual(price, 3.033)
        self.assertEqual(context["current_price"], 3.033)
        self.assertEqual(context["market_value"], 264_780.90)

    def test_raw_provider_price_precedes_rounded_summary_path(self):
        history = pd.DataFrame({"Close": [3.02, 3.031]})
        price = select_portfolio_current_price(
            history,
            {"regularMarketPrice": 3.0334, "currentPrice": 3.03},
        )
        self.assertEqual(price, 3.0334)


class StrictBatchQuoteContractTests(unittest.TestCase):
    def test_portfolio_cli_enables_strict_contract_and_preserves_raw_price(self):
        history = pd.DataFrame(
            {
                "Close": [110.0, 110.1234],
                "High": [111.0, 111.5],
                "Low": [109.0, 109.5],
                "Volume": [1_000, 1_100],
            }
        )
        info = quote_result(
            quote_epoch=time.time() - 60,
        )["info"]
        info["regularMarketPrice"] = 110.1234

        with tempfile.TemporaryDirectory() as tmpdir:
            portfolio_path = Path(tmpdir) / "portfolio.json"
            portfolio_path.write_text(
                json.dumps(
                    {
                        "base_currency": "USD",
                        "positions": [
                            {
                                "symbol": "AAPL",
                                "name": "Apple Inc.",
                                "quantity": 2,
                                "avg_cost": 100,
                                "currency": "USD",
                                "market": "US",
                                "asset_type": "stock",
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
                str(portfolio_path),
                "--json",
                "--lean",
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(yf_module, "resolve_symbol", return_value="AAPL"),
                patch.object(
                    yf_module,
                    "get_stock_data",
                    return_value=(history, info, [], []),
                ),
                contextlib.redirect_stdout(output),
                self.assertRaises(SystemExit) as exit_context,
            ):
                yf_module.main()

        payload = json.loads(output.getvalue())
        audit = payload[0]["portfolio_batch_audit"]
        self.assertEqual(exit_context.exception.code, 0)
        self.assertTrue(audit["strict_quote_contract"])
        self.assertTrue(audit["complete"])
        self.assertEqual(
            payload[0]["portfolio_context"]["current_price"], 110.1234
        )

    def test_complete_requires_a_fully_matched_fresh_quote_contract(self):
        audit = strict_audit(quote_result(), expected_position())

        self.assertTrue(audit["complete"])
        self.assertEqual(audit["quote_contract_matched_count"], 1)
        self.assertEqual(audit["quote_contract_failures"], {})

    def test_any_record_error_forces_incomplete(self):
        audit = strict_audit(
            quote_result(errors=["provider returned a partial response"]),
            expected_position(),
        )

        self.assertFalse(audit["complete"])
        self.assertEqual(audit["result_error_symbols"], ["AAPL"])
        self.assertIn(
            "result_errors_present", audit["quote_contract_failures"]["AAPL"]
        )

    def test_missing_required_info_field_forces_incomplete(self):
        result = quote_result()
        result["info"].pop("marketState")

        audit = strict_audit(result, expected_position())

        self.assertFalse(audit["complete"])
        self.assertIn(
            "missing_info.marketState", audit["quote_contract_failures"]["AAPL"]
        )

    def test_rounded_summary_cannot_replace_raw_current_quote(self):
        result = quote_result()
        result["info"].pop("regularMarketPrice")

        audit = strict_audit(result, expected_position())

        self.assertFalse(audit["complete"])
        self.assertIn(
            "missing_info.current_market_price",
            audit["quote_contract_failures"]["AAPL"],
        )

    def test_exchange_name_can_satisfy_the_exchange_identity_field(self):
        result = quote_result()
        result["info"].pop("exchange")
        result["info"]["exchangeName"] = "Nasdaq Global Select Market"

        audit = strict_audit(result, expected_position())

        self.assertTrue(audit["complete"])

    def test_stale_quote_forces_incomplete(self):
        result = quote_result(quote_epoch=NOW_EPOCH - 8 * 24 * 60 * 60)

        audit = strict_audit(result, expected_position())

        self.assertFalse(audit["complete"])
        self.assertEqual(audit["stale_quote_symbols"], ["AAPL"])

    def test_identity_currency_exchange_and_type_conflicts_are_detected(self):
        cases = [
            (quote_result(symbol="AAPL", exchange="SHH"), "identity_mismatch.exchange"),
            (quote_result(currency="CNY"), "identity_mismatch.currency"),
            (quote_result(quote_type="ETF"), "identity_mismatch.quoteType"),
        ]
        for result, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                audit = strict_audit(result, expected_position())
                self.assertFalse(audit["complete"])
                self.assertIn(
                    expected_error, audit["quote_contract_failures"]["AAPL"]
                )

    def test_cn_etf_equity_provider_alias_is_accepted_only_with_closed_identity(self):
        symbol = "159516.SZ"
        audit = strict_audit(
            quote_result(
                symbol=symbol,
                exchange="SHZ",
                currency="CNY",
                quote_type="EQUITY",
            ),
            expected_position(
                symbol=symbol,
                currency="CNY",
                market="CN",
                asset_type="etf",
                name="半导体设备ETF国泰",
            ),
        )

        self.assertTrue(audit["complete"])
        self.assertEqual(
            audit["quote_contract_warnings"][symbol],
            ["provider_quote_type_alias.cn_etf_as_equity"],
        )

    def test_cn_stock_reported_as_etf_is_a_real_identity_conflict(self):
        symbol = "601088.SS"
        audit = strict_audit(
            quote_result(
                symbol=symbol,
                exchange="SHH",
                currency="CNY",
                quote_type="ETF",
            ),
            expected_position(
                symbol=symbol,
                currency="CNY",
                market="CN",
                asset_type="stock",
                name="中国神华",
            ),
        )

        self.assertFalse(audit["complete"])
        self.assertIn(
            "identity_mismatch.quoteType",
            audit["quote_contract_failures"][symbol],
        )


if __name__ == "__main__":
    unittest.main()
