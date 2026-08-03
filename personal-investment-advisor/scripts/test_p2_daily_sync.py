import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import daily_sync


NOW_EPOCH = 1_800_000_000.0


def positions_payload():
    return {
        "base_currency": "CNY",
        "exchange_rates": {"USD": 7.2},
        "positions": [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "quantity": 2,
                "avg_cost": 100.0,
                "currency": "USD",
                "market_type": "US_STOCK",
            },
            {
                "symbol": "159516.SZ",
                "name": "半导体设备ETF国泰",
                "quantity": 100,
                "avg_cost": 0.737,
                "currency": "CNY",
                "market_type": "A股ETF",
            },
            {
                "symbol": "CASH_CNY",
                "name": "人民币现金",
                "quantity": 1_000,
                "avg_cost": 1.0,
                "currency": "CNY",
                "market_type": "CASH",
            },
            {
                "symbol": "VOO",
                "name": "inactive audit record",
                "quantity": 0,
                "avg_cost": 600.0,
                "currency": "USD",
                "market_type": "ETF",
            },
        ],
    }


def quote_record(
    symbol,
    *,
    price,
    currency,
    exchange,
    quote_type,
    quote_epoch=NOW_EPOCH - 60,
):
    return {
        "query": symbol,
        "symbol": symbol,
        "summary": {"last_close": round(price, 2)},
        "info": {
            "symbol": symbol,
            "regularMarketPrice": price,
            "exchange": exchange,
            "currency": currency,
            "quoteType": quote_type,
            "regularMarketTime": quote_epoch,
            "marketState": "CLOSED",
        },
        "data_sources": {
            "price": "Yahoo Finance",
            "price_locator": f"yfinance:{symbol}:quote",
        },
        "portfolio_context": {
            "position_status": "matched",
            "current_price": price,
            "currency": currency,
        },
    }


def quote_records():
    return [
        quote_record(
            "AAPL",
            price=110.1234,
            currency="USD",
            exchange="NMS",
            quote_type="EQUITY",
        ),
        quote_record(
            "159516.SZ",
            price=0.751,
            currency="CNY",
            exchange="SHZ",
            quote_type="EQUITY",
        ),
    ]


def supplied_audit(**overrides):
    audit = {
        "requested_count": 2,
        "result_record_count": 2,
        "resolved_symbol_count": 2,
        "unique_resolved_symbol_count": 2,
        "quote_success_count": 2,
        "portfolio_matched_count": 2,
        "returned_symbols": ["AAPL", "159516.SZ"],
        "quote_failed_symbols": [],
        "unmatched_symbols": [],
        "duplicate_requested_symbols": [],
        "expected_active_symbols": ["159516.SZ", "AAPL"],
        "missing_requested_symbols": [],
        "unexpected_requested_symbols": [],
        "coverage_complete": True,
        "portfolio_load_status": "ok",
        "portfolio_load_error": None,
        "strict_quote_contract": True,
        "complete": True,
        "status": "complete",
    }
    audit.update(overrides)
    return audit


class DailySyncTestCase(unittest.TestCase):
    def write_inputs(self, root, *, positions=None, quotes=None):
        positions_path = Path(root) / "positions.json"
        quotes_path = Path(root) / "quotes.json"
        positions_path.write_text(
            json.dumps(positions if positions is not None else positions_payload()),
            encoding="utf-8",
        )
        quotes_path.write_text(
            json.dumps(
                quotes
                if quotes is not None
                else {
                    "records": quote_records(),
                    "portfolio_batch_audit": supplied_audit(),
                }
            ),
            encoding="utf-8",
        )
        return positions_path, quotes_path

    def evaluate(self, positions_path, quotes_path):
        return daily_sync.evaluate_daily_sync(
            positions_file=str(positions_path),
            quotes_file=str(quotes_path),
            now_epoch=NOW_EPOCH,
        )


class CompleteOfflineSyncTests(DailySyncTestCase):
    def test_complete_package_is_deterministic_and_excludes_cash_and_inactive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            first = self.evaluate(positions_path, quotes_path)
            second = self.evaluate(positions_path, quotes_path)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "complete")
        self.assertTrue(first["completeness"]["complete"])
        self.assertEqual(first["requested"], 2)
        self.assertEqual(first["succeeded"], 2)
        self.assertEqual(first["matched"], 2)
        self.assertEqual(
            first["completeness"]["expected_symbols"],
            ["AAPL", "159516.SZ"],
        )
        self.assertEqual(
            [item["symbol"] for item in first["quote_snapshot"]],
            ["AAPL", "159516.SZ"],
        )
        self.assertEqual(first["quote_snapshot"][0]["current_price"], 110.1234)
        self.assertEqual(
            first["quote_snapshot"][0]["source_locator"],
            "yfinance:AAPL:quote",
        )
        self.assertEqual(first["thesis_red_team"]["status"], "not_assessed")
        self.assertEqual(
            first["thesis_red_team"]["evidence_status"],
            "insufficient_evidence",
        )

    def test_current_yf_list_with_repeated_identical_audit_is_accepted_as_legacy(self):
        records = quote_records()
        audit = supplied_audit()
        for record in records:
            record["portfolio_batch_audit"] = copy.deepcopy(audit)
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir, quotes=records)
            report = self.evaluate(positions_path, quotes_path)

        self.assertEqual(report["status"], "complete")
        self.assertIn(
            "legacy_repeated_identical_batch_audit",
            report["stages"][1]["warnings"],
        )


class FailClosedOfflineSyncTests(DailySyncTestCase):
    def test_missing_duplicate_extra_and_unmatched_universe_fail(self):
        cases = {}
        missing = quote_records()[:1]
        cases["missing"] = missing
        duplicate = quote_records()
        duplicate.append(copy.deepcopy(duplicate[0]))
        cases["duplicate"] = duplicate
        extra = quote_records()
        extra.append(
            quote_record(
                "MSFT",
                price=500,
                currency="USD",
                exchange="NMS",
                quote_type="EQUITY",
            )
        )
        cases["extra"] = extra
        unmatched = quote_records()
        unmatched[0]["portfolio_context"]["position_status"] = "not_found"
        cases["unmatched"] = unmatched

        for name, records in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(
                    tmpdir,
                    quotes={
                        "records": records,
                        "portfolio_batch_audit": supplied_audit(),
                    },
                )
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["complete"])

    def test_identity_currency_type_time_and_record_errors_fail(self):
        mutations = [
            ("currency", lambda r: r[0]["info"].update(currency="CNY")),
            ("exchange", lambda r: r[0]["info"].update(exchange="SHH")),
            ("type", lambda r: r[0]["info"].update(quoteType="ETF")),
            (
                "source",
                lambda r: r[0]["data_sources"].update(
                    price="arbitrary-nonempty-source"
                ),
            ),
            (
                "locator_missing",
                lambda r: r[0]["data_sources"].pop("price_locator"),
            ),
            (
                "locator_mismatch",
                lambda r: r[0]["data_sources"].update(
                    price_locator="yfinance:MSFT:quote"
                ),
            ),
            (
                "stale",
                lambda r: r[0]["info"].update(
                    regularMarketTime=NOW_EPOCH - 8 * 24 * 60 * 60
                ),
            ),
            ("errors", lambda r: r[0].update(errors=["partial provider response"])),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                records = quote_records()
                mutate(records)
                positions_path, quotes_path = self.write_inputs(
                    tmpdir,
                    quotes={
                        "records": records,
                        "portfolio_batch_audit": supplied_audit(),
                    },
                )
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["identity_complete"])

    def test_missing_or_incomplete_supplied_audit_fails_even_with_good_records(self):
        packages = [
            {"records": quote_records()},
            {
                "records": quote_records(),
                "portfolio_batch_audit": supplied_audit(
                    complete=False, status="incomplete"
                ),
            },
        ]
        for package in packages:
            with self.subTest(package=package), tempfile.TemporaryDirectory() as tmpdir:
                positions_path, quotes_path = self.write_inputs(tmpdir, quotes=package)
                report = self.evaluate(positions_path, quotes_path)
                self.assertEqual(report["status"], "incomplete")
                self.assertFalse(report["completeness"]["supplied_audit_complete"])

    def test_cli_failure_is_parseable_json_and_nonzero(self):
        package = {
            "records": quote_records()[:1],
            "portfolio_batch_audit": supplied_audit(),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir, quotes=package)
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

        report = json.loads(output.getvalue())
        self.assertNotEqual(exit_context.exception.code, 0)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["thesis_red_team"]["status"], "not_assessed")

    def test_cli_invalid_json_is_structured_and_uses_input_error_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path, quotes_path = self.write_inputs(tmpdir)
            quotes_path.write_text("{", encoding="utf-8")
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

        report = json.loads(output.getvalue())
        self.assertEqual(exit_context.exception.code, 2)
        self.assertEqual(report["status"], "invalid_input")
        self.assertTrue(report["errors"][0].startswith("quotes_file_json_error"))

    def test_missing_cli_arguments_also_emit_stable_json(self):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["daily_sync.py"]),
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as exit_context,
        ):
            daily_sync.main()

        report = json.loads(output.getvalue())
        self.assertEqual(exit_context.exception.code, 2)
        self.assertEqual(report["status"], "invalid_input")
        self.assertTrue(report["errors"][0].startswith("argument_error:"))


if __name__ == "__main__":
    unittest.main()
