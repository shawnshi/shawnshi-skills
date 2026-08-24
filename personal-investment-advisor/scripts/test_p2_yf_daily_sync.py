import io
import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import yf


class YfDailySyncContractTests(unittest.TestCase):
    def test_retry_stops_after_one_permanent_transport_failure(self):
        calls = 0

        def fail():
            nonlocal calls
            calls += 1
            raise RuntimeError("curl: (35) OPENSSL_internal: invalid library (0)")

        with patch("yf.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "invalid library"):
                yf._retry(fail, retries=3, label="quote")

        self.assertEqual(calls, 1)
        sleep.assert_not_called()

    def test_retry_keeps_transient_failure_behavior(self):
        calls = 0

        def eventually_succeeds():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("temporary timeout")
            return "ok"

        with patch("yf.time.sleep"):
            result = yf._retry(eventually_succeeds, retries=2, label="quote")

        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    def test_retry_stops_after_one_local_cache_permission_failure(self):
        calls = 0

        def fail():
            nonlocal calls
            calls += 1
            raise PermissionError("unable to open database file")

        with patch("yf.time.sleep") as sleep:
            with self.assertRaisesRegex(PermissionError, "database"):
                yf._retry(fail, retries=3, label="quote")

        self.assertEqual(calls, 1)
        sleep.assert_not_called()

    def test_daily_sync_emits_one_batch_audit_and_no_derived_etf_history(self):
        positions = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": "QQQ",
                    "name": "Invesco QQQ Trust",
                    "quantity": 5,
                    "avg_cost": 710.146,
                    "currency": "USD",
                    "market": "US",
                    "asset_type": "etf",
                }
            ],
        }
        info = {
            "symbol": "QQQ",
            "longName": "Invesco QQQ Trust",
            "regularMarketPrice": 600.1234,
            "exchange": "NGM",
            "currency": "USD",
            "quoteType": "ETF",
            "regularMarketTime": time.time() - 60,
            "marketState": "CLOSED",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            positions_path = Path(tmpdir) / "positions.json"
            positions_path.write_text(json.dumps(positions), encoding="utf-8")
            stdout = io.StringIO()
            argv = [
                "yf.py",
                "QQQ",
                "--daily-sync",
                "--positions-file",
                str(positions_path),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch(
                    "yf.resolve_symbol",
                    side_effect=AssertionError(
                        "Daily Sync must not re-resolve a validated portfolio symbol"
                    ),
                ),
                patch("yf.get_stock_data", return_value=(None, info, [], [])) as fetch,
                patch(
                    "yf.configure_yfinance_cache",
                    return_value=str(Path(tmpdir) / "cache"),
                ) as cache,
                redirect_stdout(stdout),
                self.assertRaises(SystemExit) as raised,
            ):
                yf.main()

        self.assertEqual(raised.exception.code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(len(payload["records"]), 1)
        self.assertIn("portfolio_batch_audit", payload)
        binding = payload["portfolio_batch_audit"]["portfolio_snapshot_binding"]
        self.assertEqual(binding["active_position_count"], 1)
        self.assertEqual(binding["active_positions"][0]["quantity"], "5")
        self.assertEqual(len(binding["sha256"]), 64)
        record = payload["records"][0]
        self.assertNotIn("portfolio_batch_audit", record)
        self.assertNotIn("history", record)
        self.assertNotIn("summary", record)
        self.assertNotIn("news", record)
        self.assertEqual(record["portfolio_context"]["current_price"], 600.1234)
        self.assertEqual(record["data_sources"]["price"], "Yahoo Finance")
        self.assertEqual(record["data_sources"]["price_locator"], "yfinance:QQQ:quote")
        self.assertEqual(record["history_integrity"]["status"], "not_applicable")
        _, kwargs = fetch.call_args
        self.assertFalse(kwargs["fetch_price"])
        self.assertFalse(kwargs["fetch_news"])
        self.assertTrue(kwargs["fetch_info"])
        cache.assert_called_once_with(None, task_local_default=True)

    def test_daily_sync_batch_fetches_independent_symbols_concurrently(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fetch(symbol, **kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return None, {"symbol": symbol}, [], []

        with patch("yf.get_stock_data", side_effect=fetch) as get_data:
            results = yf.fetch_daily_sync_batch(
                ["AAPL", "MSFT", "QQQ", "GOOG"],
                max_workers=4,
            )

        self.assertEqual(set(results), {"AAPL", "MSFT", "QQQ", "GOOG"})
        self.assertGreaterEqual(max_active, 2)
        self.assertEqual(get_data.call_count, 4)
        for call in get_data.call_args_list:
            self.assertFalse(call.kwargs["fetch_price"])
            self.assertTrue(call.kwargs["fetch_info"])
            self.assertFalse(call.kwargs["fetch_news"])

    def test_daily_sync_batch_opens_circuit_on_repeated_systemic_tls_failure(self):
        symbols = ["AAPL", "MSFT", "QQQ", "GOOG", "AMZN", "META"]

        def fail(symbol, **kwargs):
            return (
                None,
                {},
                [],
                [f"Info fetch failed for {symbol}: curl: (35) invalid library"],
            )

        with patch("yf.get_stock_data", side_effect=fail) as get_data:
            results = yf.fetch_daily_sync_batch(symbols, max_workers=2)

        self.assertEqual(set(results), set(symbols))
        self.assertEqual(get_data.call_count, 2)
        skipped = [
            symbol
            for symbol, result in results.items()
            if any("circuit breaker" in error for error in result[3])
        ]
        self.assertEqual(len(skipped), 4)

    def test_explicit_cache_directory_is_created_and_bound_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "nested" / "yfinance"
            with patch("yf.yf.set_tz_cache_location") as set_location:
                resolved = yf.configure_yfinance_cache(str(cache_dir))

            self.assertTrue(cache_dir.is_dir())
            self.assertEqual(resolved, str(cache_dir.resolve()))
            set_location.assert_called_once_with(str(cache_dir.resolve()))

    def test_cache_preflight_rejects_existing_but_unwritable_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "yfinance"
            cache_dir.mkdir()
            with (
                patch("yf.os.open", side_effect=PermissionError("blocked")),
                patch("yf.yf.set_tz_cache_location") as set_location,
                self.assertRaisesRegex(RuntimeError, "yfinance_cache_unwritable"),
            ):
                yf.configure_yfinance_cache(str(cache_dir))

        set_location.assert_not_called()

    def test_regular_cli_uses_task_local_cache_default(self):
        stdout = io.StringIO()
        argv = ["yf.py", "AAPL", "--info-only", "--json"]
        with (
            patch.object(sys, "argv", argv),
            patch("yf.configure_yfinance_cache", return_value="cache") as cache,
            patch("yf.resolve_symbol", return_value=None),
            redirect_stdout(stdout),
            self.assertRaises(SystemExit),
        ):
            yf.main()

        cache.assert_called_once_with(None, task_local_default=True)

    def test_direct_ticker_metadata_is_reused_by_data_fetch(self):
        info_reads = 0
        info = {
            "symbol": "AAPL",
            "longName": "Apple Inc.",
            "quoteType": "EQUITY",
        }

        class FakeTicker:
            @property
            def info(self):
                nonlocal info_reads
                info_reads += 1
                return info

        with patch("yf.yf.Ticker", return_value=FakeTicker()):
            symbol, prefetched = yf.resolve_symbol("AAPL", return_info=True)
            _, fetched_info, _, errors = yf.get_stock_data(
                symbol,
                fetch_price=False,
                fetch_info=True,
                fetch_news=False,
                prefetched_info=prefetched,
            )

        self.assertEqual(symbol, "AAPL")
        self.assertIs(fetched_info, info)
        self.assertEqual(errors, [])
        self.assertEqual(info_reads, 1)

    def test_search_resolution_does_not_forge_an_empty_metadata_cache(self):
        info = {
            "symbol": "AAPL",
            "longName": "Apple Inc.",
            "quoteType": "EQUITY",
        }

        class FakeTicker:
            @property
            def info(self):
                return info

        with (
            patch("yf.search_symbol", return_value="AAPL"),
            patch("yf.yf.Ticker", return_value=FakeTicker()) as ticker,
        ):
            symbol, prefetched = yf.resolve_symbol(
                "Apple Incorporated", return_info=True
            )
            _, fetched_info, _, errors = yf.get_stock_data(
                symbol,
                fetch_price=False,
                fetch_info=True,
                fetch_news=False,
                prefetched_info=prefetched,
            )

        self.assertEqual(symbol, "AAPL")
        self.assertIsNone(prefetched)
        self.assertEqual(fetched_info, info)
        self.assertEqual(errors, [])
        ticker.assert_called_once_with("AAPL")

    def test_unwritable_cache_fails_before_any_quote_retry(self):
        stdout = io.StringIO()
        argv = ["yf.py", "QQQ", "--daily-sync", "--positions-file", "p.json"]
        with (
            patch.object(sys, "argv", argv),
            patch(
                "yf.configure_yfinance_cache",
                side_effect=RuntimeError("yfinance_cache_unwritable: blocked"),
            ),
            patch("yf.get_stock_data") as fetch,
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf.main()

        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")
        fetch.assert_not_called()

    def test_unwritable_cache_regular_json_is_parseable_and_skips_fetch(self):
        stdout = io.StringIO()
        argv = ["yf.py", "AAPL", "--info-only", "--json"]
        with (
            patch.object(sys, "argv", argv),
            patch(
                "yf.configure_yfinance_cache",
                side_effect=RuntimeError("yfinance_cache_unwritable: blocked"),
            ),
            patch("yf.resolve_symbol") as resolve,
            patch("yf.get_stock_data") as fetch,
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf.main()

        self.assertEqual(raised.exception.code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["status"], "failed")
        self.assertIn("yfinance_cache_unwritable", payload[0]["error"])
        resolve.assert_not_called()
        fetch.assert_not_called()

    def test_empty_info_only_metadata_is_not_reported_as_success(self):
        stdout = io.StringIO()
        argv = ["yf.py", "AAPL", "--info-only", "--json"]
        with (
            patch.object(sys, "argv", argv),
            patch("yf.configure_yfinance_cache", return_value="cache"),
            patch("yf.resolve_symbol", return_value="AAPL"),
            patch("yf.get_stock_data", return_value=(None, {}, [], [])),
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            yf.main()

        self.assertEqual(raised.exception.code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertIsNone(payload[0]["data_sources"]["info"])
        self.assertIn(
            "Info fetch failed: provider returned empty metadata",
            payload[0]["errors"],
        )


if __name__ == "__main__":
    unittest.main()
