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
        from provider_runtime import is_retryable_error
        self.assertFalse(is_retryable_error(RuntimeError("curl: (35) invalid library")))

    def test_retry_keeps_transient_failure_behavior(self):
        from provider_runtime import is_retryable_error
        self.assertTrue(is_retryable_error(TimeoutError("temporary timeout")))

    def test_retry_stops_after_one_local_cache_permission_failure(self):
        from provider_runtime import is_retryable_error
        self.assertFalse(is_retryable_error(PermissionError("unable to open database file")))

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

    def test_default_daily_batch_is_serial_for_shared_cache_safety(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def fetch(symbol, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return None, {'symbol': symbol}, [], []

        receipt = {}
        with patch('yf.get_stock_data', side_effect=fetch):
            results = yf.fetch_daily_sync_batch(['AAPL', 'MSFT', 'GOOG'], receipt=receipt)
        self.assertEqual(peak, 1)
        self.assertEqual(receipt['workers'], 1)
        self.assertEqual(len(results), 3)

    def test_serial_batch_does_not_declare_outage_from_one_symbol(self):
        def fetch(symbol, **kwargs):
            if symbol == 'AAPL':
                return None, {}, [], ['Info fetch failed: HTTP 503 Service Unavailable']
            return None, {'symbol': symbol}, [], []

        with patch('yf.get_stock_data', side_effect=fetch) as calls:
            results = yf.fetch_daily_sync_batch(['AAPL', 'MSFT', 'GOOG'])
        self.assertEqual(calls.call_count, 3)
        self.assertEqual(results['MSFT'][1]['symbol'], 'MSFT')

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

        with patch("yf.yf.Ticker", return_value=FakeTicker()), patch("yf._call_yahoo", side_effect=yf._yahoo_provider):
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
            patch("yf._call_yahoo", side_effect=yf._yahoo_provider),
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


    def test_batch_receipt_separates_a_provider_outage_from_missing_data(self):
        def fake_get_stock_data(symbol, **_kwargs):
            if symbol == "HANG":
                raise RuntimeError("curl: (35) connection refused")
            if symbol == "EMPTY":
                return None, {}, [], []
            return None, {"symbol": symbol}, [], []

        receipt: dict = {}
        with patch("yf.get_stock_data", side_effect=fake_get_stock_data):
            results = yf.fetch_daily_sync_batch(
                ["OK", "HANG", "HANG", "EMPTY"], max_workers=1, receipt=receipt
            )

        self.assertEqual(len(results), 3)
        self.assertEqual(receipt["provider"], "yfinance")
        self.assertEqual(receipt["requested_count"], 3)
        self.assertEqual(receipt["outcomes"],
                         {"OK": "ok", "HANG": "error", "EMPTY": "no_data"})
        self.assertEqual(receipt["outcome_counts"]["error"], 1)
        self.assertIn("not that the security has no quote", receipt["statement"])

    def test_batch_receipt_records_the_circuit_breaker_skip_reason(self):
        def fake_get_stock_data(_symbol, **_kwargs):
            raise RuntimeError("curl: (35) connection refused")

        receipt: dict = {}
        with patch("yf.get_stock_data", side_effect=fake_get_stock_data):
            results = yf.fetch_daily_sync_batch(
                ["A", "B", "C", "D"], max_workers=1, receipt=receipt
            )

        self.assertEqual(len(results), 4)
        # Serial execution still requires two independent symbols to confirm an outage.
        self.assertEqual(receipt["outcome_counts"].get("error"), 2)
        self.assertEqual(receipt["outcome_counts"].get("skipped_circuit_open"), 2)
        self.assertEqual(receipt["circuit_breaker_signature"], "curl: (35)")
        self.assertEqual(receipt["transport_failures"]["curl: (35)"], 2)

    def test_batch_receipt_is_absent_unless_requested(self):
        with patch("yf.get_stock_data", return_value=(None, {"symbol": "OK"}, [], [])):
            results = yf.fetch_daily_sync_batch(["OK"], max_workers=1)

        self.assertEqual(results["OK"][1], {"symbol": "OK"})


def secondary_quote_record(symbol="GOOG", *, price=336.15, currency="USD",
                           exchange="NASDAQ", market_state="REGULAR",
                           observed_epoch=None, unverifiable=("quoteType", "timeliness")):
    import quote_fallback as qf
    observed = observed_epoch if observed_epoch is not None else time.time() - 60
    return {
        "tier": "secondary",
        "symbol": symbol,
        "source": qf.SOURCE_TENCENT,
        "source_url": qf.source_url(symbol),
        "source_locator": qf.source_locator(symbol),
        "price": price,
        "previous_close": 339.0,
        "currency": currency,
        "observed_at": "2026-09-29T10:16:20-04:00",
        "observed_epoch": observed,
        "retrieved_at": "2026-09-29T14:16:30+00:00",
        "market_state": market_state,
        "identity_verification": "echoed_venue_code_and_currency",
        "exchange": exchange,
        "exchange_evidence": "venue_suffix_echo" if exchange else None,
        "unverifiable": list(unverifiable),
        "echoed_symbol": f"{symbol}.OQ",
        "instrument_name": None,
        "primary_outcome": "error",
    }


class FakeFetcher:
    def __init__(self, results=None):
        self.results = results or {}
        self.requested = []

    def fetch_many(self, symbols, *, primary_outcomes=None, markets=None):
        self.requested = list(symbols)
        return {
            symbol: self.results.get(symbol, {"health": "broken", "record": None,
                                              "error": "no_secondary_record"})
            for symbol in symbols
        }


class QuoteFallbackTests(unittest.TestCase):
    """A secondary source may only replace a failed primary transport."""

    def receipt(self, outcomes):
        return {"provider": "yfinance", "operation": "daily_sync_quote_metadata",
                "outcomes": dict(outcomes),
                "outcome_counts": {value: list(outcomes.values()).count(value)
                                   for value in set(outcomes.values())}}

    def prefetch(self, symbols):
        return {symbol: (None, {}, [], []) for symbol in symbols}

    def test_only_transport_failures_trigger_the_secondary_source(self):
        outcomes = {"OK": "ok", "ERR": "error", "NODATA": "no_data",
                    "SKIPPED": "skipped_circuit_open"}
        receipt = self.receipt(outcomes)
        fetcher = FakeFetcher({"ERR": {"health": "ok", "record": secondary_quote_record("ERR")},
                               "SKIPPED": {"health": "ok", "record": secondary_quote_record("SKIPPED")}})
        tiers = yf.apply_quote_fallbacks(self.prefetch(outcomes), receipt, {}, fetcher=fetcher)
        self.assertEqual(fetcher.requested, ["ERR", "SKIPPED"])
        self.assertEqual(sorted(tiers), ["ERR", "SKIPPED"])
        fallback = receipt["fallback"]
        self.assertEqual(fallback["policy"], yf.FALLBACK_POLICY)
        self.assertEqual(fallback["attempted"], ["ERR", "SKIPPED"])
        self.assertEqual(fallback["used"], ["ERR", "SKIPPED"])
        self.assertEqual(fallback["coverage_tier"], "mixed")
        self.assertEqual(set(fallback["sources"].values()), {"Tencent Finance (secondary)"})

    def test_a_primary_no_data_answer_is_never_replaced(self):
        receipt = self.receipt({"A": "no_data", "B": "ok"})
        fetcher = FakeFetcher()
        tiers = yf.apply_quote_fallbacks(self.prefetch({"A": None, "B": None}), receipt, {},
                                         fetcher=fetcher)
        self.assertEqual(fetcher.requested, [])
        self.assertEqual(tiers, {})
        self.assertEqual(receipt["fallback"]["attempted"], [])
        self.assertEqual(receipt["fallback"]["coverage_tier"], "primary")

    def test_successful_fallback_injects_only_source_evidenced_metadata(self):
        receipt = self.receipt({"ERR": "error"})
        prefetch = self.prefetch({"ERR": None})
        record = secondary_quote_record("ERR")
        yf.apply_quote_fallbacks(prefetch, receipt, {},
                                 fetcher=FakeFetcher({"ERR": {"health": "ok", "record": record}}))
        history, info, news, errors = prefetch["ERR"]
        self.assertIsNone(history)
        self.assertEqual(errors, [])
        self.assertEqual(info["regularMarketPrice"], 336.15)
        self.assertEqual(info["currency"], "USD")
        self.assertEqual(info["exchange"], "NASDAQ")
        self.assertEqual(info["marketState"], "REGULAR")
        self.assertEqual(info["regularMarketTime"], record["observed_epoch"])
        # Not printed by the source, so it must not be invented.
        self.assertIsNone(info["quoteType"])
        self.assertEqual(info["exchangeTimezoneName"], "America/New_York")

    def test_failed_fallback_keeps_the_primary_failure_and_records_it(self):
        receipt = self.receipt({"ERR": "error"})
        prefetch = {"ERR": (None, {}, [], ["provider transport failed"])}
        tiers = yf.apply_quote_fallbacks(prefetch, receipt, {}, fetcher=FakeFetcher())
        self.assertEqual(tiers, {})
        self.assertEqual(prefetch["ERR"][3], ["provider transport failed"])
        self.assertEqual(receipt["fallback"]["outcomes"]["ERR"], "broken")
        self.assertEqual(receipt["fallback"]["used"], [])
        self.assertEqual(receipt["fallback"]["coverage_tier"], "primary_incomplete")


class SecondaryQuoteContractTests(unittest.TestCase):
    """A declared secondary quote is judged on what it evidenced, and nothing else."""

    def position(self, **overrides):
        payload = {"symbol": "GOOG", "currency": "USD", "market": "US",
                   "asset_type": "stock"}
        payload.update(overrides)
        return payload

    def result(self, record):
        record = dict(record)
        record["query"] = record["symbol"]
        record["info"] = yf._secondary_info(record["symbol"], record)
        record["quote_provenance"] = record
        return record

    def contract(self, record, position=None, *, now=None):
        return yf._quote_contract_report(
            self.result(record), position or self.position(),
            now_epoch=now if now is not None else time.time(),
            max_quote_age_seconds=yf.MAX_QUOTE_AGE_SECONDS,
        )

    def test_unprinted_type_is_a_named_gap_not_a_mismatch(self):
        contract = self.contract(secondary_quote_record())
        self.assertEqual(contract["status"], "matched")
        self.assertIn("secondary_quote_source", contract["warnings"])
        self.assertIn("unverifiable.secondary_source.quoteType", contract["warnings"])

    def test_missing_exchange_for_a_secondary_quote_is_a_named_gap(self):
        contract = self.contract(secondary_quote_record(exchange=None))
        self.assertEqual(contract["status"], "matched")
        self.assertIn("unverifiable.secondary_source.exchange", contract["warnings"])

    def test_a_primary_quote_still_needs_its_exchange_and_type(self):
        record = secondary_quote_record()
        record["tier"] = "primary"
        record["exchange"] = None
        contract = self.contract(record)
        self.assertEqual(contract["status"], "failed")
        self.assertIn("missing_info.exchange_or_exchangeName", contract["errors"])
        self.assertIn("missing_info.quoteType", contract["errors"])

    def test_secondary_currency_conflict_still_fails(self):
        contract = self.contract(secondary_quote_record(currency="HKD"))
        self.assertEqual(contract["status"], "failed")
        self.assertIn("identity_mismatch.currency", contract["errors"])

    def test_secondary_stale_timestamp_still_fails(self):
        stale = time.time() - 30 * 24 * 3600
        contract = self.contract(secondary_quote_record(observed_epoch=stale))
        self.assertEqual(contract["status"], "failed")
        self.assertIn("stale_info.regularMarketTime", contract["errors"])


if __name__ == "__main__":
    unittest.main()
