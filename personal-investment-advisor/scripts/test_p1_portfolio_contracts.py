import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portfolio_loader import (
    build_position_context,
    is_cash_position,
    load_positions,
    validate_portfolio_payload,
)


def stock_position(**overrides):
    position = {
        "symbol": "AAPL",
        "quantity": 2,
        "avg_cost": 100.0,
        "currency": "USD",
        "market_type": "US_STOCK",
    }
    position.update(overrides)
    return position


def cross_currency_portfolio(**overrides):
    payload = {
        "base_currency": "CNY",
        "exchange_rates": {"USD": 7.2},
        "positions": [stock_position()],
    }
    payload.update(overrides)
    return payload


class StrongPositionContractTests(unittest.TestCase):
    def test_symbol_currency_and_market_type_are_strong_strings(self):
        cases = [
            ("symbol", 123, ".symbol must be a non-empty string"),
            ("currency", 840, ".currency must be a three-letter string"),
            ("market_type", 123, ".market_type must be a non-empty string"),
        ]
        for field, value, expected_error in cases:
            with self.subTest(field=field):
                position = stock_position(**{field: value})
                errors = validate_portfolio_payload(
                    cross_currency_portfolio(positions=[position])
                )
                self.assertTrue(any(expected_error in error for error in errors))

    def test_position_numbers_reject_bools_and_numeric_strings(self):
        cases = [
            ("quantity", True),
            ("quantity", "2"),
            ("avg_cost", False),
            ("avg_cost", "100.0"),
            ("current_weight", True),
            ("current_weight", "0.25"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                position = stock_position(**{field: value})
                errors = validate_portfolio_payload(
                    cross_currency_portfolio(positions=[position])
                )
                self.assertTrue(any(field in error for error in errors))
                self.assertTrue(
                    any("bool and numeric string are prohibited" in error for error in errors)
                )

    def test_exchange_rates_reject_bools_and_numeric_strings(self):
        for value in (True, "7.2"):
            with self.subTest(value=value):
                errors = validate_portfolio_payload(
                    cross_currency_portfolio(exchange_rates={"USD": value})
                )
                self.assertTrue(any("exchange_rates.USD" in error for error in errors))

    def test_market_type_is_required_and_current_values_are_allowed(self):
        missing = stock_position()
        missing.pop("market_type")
        errors = validate_portfolio_payload(
            cross_currency_portfolio(positions=[missing])
        )
        self.assertTrue(any("missing fields: market_type" in error for error in errors))

        allowed_positions = [
            stock_position(symbol="600750.SS", currency="CNY", market_type="A_SHARE"),
            stock_position(symbol="510050.SS", currency="CNY", market_type="A股ETF"),
            stock_position(market_type="US_STOCK"),
            stock_position(symbol="QQQ", market_type="ETF"),
            stock_position(symbol="CASH_USD", market_type="CASH"),
            stock_position(symbol="MSFT", market_type="US"),
        ]
        for position in allowed_positions:
            with self.subTest(market_type=position["market_type"]):
                payload = {
                    "base_currency": position["currency"],
                    "positions": [position],
                }
                self.assertEqual(validate_portfolio_payload(payload), [])

    def test_cash_identity_requires_both_symbol_and_market_type(self):
        pseudo_cash = stock_position(symbol="AAPL", market_type="CASH")
        disguised_cash = stock_position(symbol="CASH_USD", market_type="US_STOCK")
        for position in (pseudo_cash, disguised_cash):
            with self.subTest(position=position):
                errors = validate_portfolio_payload(
                    {
                        "base_currency": "USD",
                        "positions": [position],
                    }
                )
                self.assertTrue(any("cash identity requires both" in error for error in errors))
                self.assertFalse(is_cash_position(position))

        valid_cash = stock_position(symbol="CASH_USD", market_type="cash")
        self.assertEqual(
            validate_portfolio_payload(
                {"base_currency": "USD", "positions": [valid_cash]}
            ),
            [],
        )
        self.assertTrue(is_cash_position(valid_cash))


class ExchangeRateProvenanceTests(unittest.TestCase):
    def test_legacy_flat_rate_loads_but_is_explicitly_undated_static(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(
                json.dumps(cross_currency_portfolio()), encoding="utf-8"
            )
            loaded = load_positions(str(path))

        context = build_position_context("AAPL", current_price=110, payload=loaded)
        self.assertEqual(loaded["_exchange_rate_data_status"]["USD"], "undated_static")
        self.assertEqual(context["fx_data_status"], "undated_static")
        self.assertIsNone(context["fx_as_of"])
        self.assertIsNone(context["fx_source"])

    def test_dated_metadata_flows_into_position_context(self):
        payload = cross_currency_portfolio(
            exchange_rate_metadata={
                "USD": {
                    "pair": "USD/CNY",
                    "as_of": "2026-08-02T08:00:00+08:00",
                    "source": "primary market-data snapshot",
                    "retrieved_at": "2026-08-02T08:01:00+08:00",
                }
            }
        )
        self.assertEqual(validate_portfolio_payload(payload), [])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "portfolio.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_positions(str(path))

        context = build_position_context("AAPL", current_price=110, payload=loaded)
        self.assertEqual(loaded["_exchange_rate_data_status"]["USD"], "dated_snapshot")
        self.assertEqual(context["fx_data_status"], "dated_snapshot")
        self.assertEqual(context["fx_as_of"], "2026-08-02T08:00:00+08:00")
        self.assertEqual(context["fx_source"], "primary market-data snapshot")
        self.assertEqual(context["fx_retrieved_at"], "2026-08-02T08:01:00+08:00")

    def test_invalid_metadata_pair_dates_source_and_orphan_are_rejected(self):
        valid_metadata = {
            "USD": {
                "pair": "USD/CNY",
                "as_of": "2026-08-02",
                "source": "market-data snapshot",
                "retrieved_at": "2026-08-02T08:01:00Z",
            }
        }
        mutations = [
            ("pair", "CNY/USD", ".pair must equal USD/CNY"),
            ("as_of", "not-a-date", ".as_of must be an ISO"),
            ("source", 123, ".source must be a non-empty string"),
            ("retrieved_at", "yesterday", ".retrieved_at must be an ISO"),
        ]
        for field, value, expected_error in mutations:
            with self.subTest(field=field):
                metadata = copy.deepcopy(valid_metadata)
                metadata["USD"][field] = value
                errors = validate_portfolio_payload(
                    cross_currency_portfolio(exchange_rate_metadata=metadata)
                )
                self.assertTrue(any(expected_error in error for error in errors))

        orphan_errors = validate_portfolio_payload(
            {
                "base_currency": "CNY",
                "positions": [
                    stock_position(symbol="600750.SS", currency="CNY", market_type="A_SHARE")
                ],
                "exchange_rate_metadata": valid_metadata,
            }
        )
        self.assertTrue(any("no matching numeric exchange_rates" in error for error in orphan_errors))

    def test_base_currency_uses_identity_status_not_a_realtime_claim(self):
        position = stock_position(
            symbol="600750.SS", currency="CNY", market_type="A_SHARE"
        )
        payload = {
            "_status": "ok",
            "_path": "portfolio.json",
            "_positions_dict": {"600750.SS": position},
            "_inactive_positions_dict": {},
            "positions": [position],
            "base_currency": "CNY",
        }
        context = build_position_context(
            "600750.SS", current_price=25, payload=payload
        )
        self.assertEqual(context["fx_data_status"], "base_currency_identity")
        self.assertEqual(context["fx_source"], "currency_identity")
        self.assertIsNone(context["fx_as_of"])


if __name__ == "__main__":
    unittest.main()
