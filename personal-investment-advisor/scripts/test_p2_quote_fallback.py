"""Tests for the labelled secondary quote source (P0-2b).

The adapter only runs after a primary transport failure, so the tests pin down what
keeps that safe: identity from what the vendor echoed, currency/venue taken from the
payload rather than from the portfolio, structural garbage classified as broken
(never as a price), and a cache that cannot hide a fresh read when it matters.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import quote_fallback as qf  # noqa: E402


def _wrap(key: str, fields: list[str]) -> str:
    return f'v_{key}="{"~".join(fields)}";'


def cn_payload(key: str = "sh601899", name: str = "紫金矿业", code: str = "601899",
               price: str = "29.460", stamp: str = "20260929161454") -> str:
    fields = ["1", name, code, price, "29.420", "29.010"]
    fields += [""] * (30 - len(fields))
    fields += [stamp, "0.04", "0.14", "29.620", "29.010"]
    assert len(fields) == 35, len(fields)
    return _wrap(key, fields)


def us_payload(key: str = "usGOOG", venue_code: str = "GOOG.OQ", price: str = "336.150",
               stamp: str = "2026-09-29 10:16:20", currency: str = "USD") -> str:
    fields = ["200", "谷歌-C", venue_code, price, "339.160", "338.540"]
    fields += [""] * (30 - len(fields))
    fields += [stamp, "-3.01", "-0.89", "339.630", "336.350", currency]
    assert len(fields) == 36, len(fields)
    return _wrap(key, fields)


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url, headers):
        self.calls.append(url)
        return self.responses.get(url, (404, ""))


class ParseTests(unittest.TestCase):
    def test_cn_quote_keeps_source_currency_and_echoed_code(self):
        parsed = qf.parse_payload(cn_payload(), "601899.SS", "CN")
        self.assertEqual(parsed["price"], 29.46)
        self.assertEqual(parsed["currency"], "CNY")
        self.assertEqual(parsed["echoed_symbol"], "601899")
        self.assertEqual(parsed["exchange"], "SSE")
        self.assertEqual(parsed["identity_verification"], "echoed_instrument_key_and_code")
        self.assertEqual(parsed["market_state"], "CLOSED")
        # Cannot be evidenced by this source, so it is named rather than invented.
        self.assertIn("quoteType", parsed["unverifiable"])
        self.assertIn("timeliness", parsed["unverifiable"])

    def test_us_quote_takes_currency_and_venue_from_the_payload(self):
        parsed = qf.parse_payload(us_payload(), "GOOG", "US")
        self.assertEqual(parsed["price"], 336.15)
        self.assertEqual(parsed["currency"], "USD")
        self.assertEqual(parsed["exchange"], "NASDAQ")
        self.assertEqual(parsed["exchange_evidence"], "venue_suffix_echo")
        self.assertEqual(parsed["market_state"], "REGULAR")
        self.assertEqual(parsed["observed_at"], "2026-09-29T10:16:20-04:00")

    def test_us_unknown_venue_suffix_stays_unverifiable(self):
        parsed = qf.parse_payload(us_payload(venue_code="GOOG.ZZ"), "GOOG", "US")
        self.assertIsNone(parsed["exchange"])
        self.assertIsNone(parsed["exchange_evidence"])
        self.assertIn("exchange", parsed["unverifiable"])

    def test_cn_after_hours_is_labelled_closed(self):
        parsed = qf.parse_payload(cn_payload(stamp="20260929153000"), "601899.SS", "CN")
        self.assertEqual(parsed["market_state"], "CLOSED")

    def test_cn_weekend_is_labelled_closed(self):
        # 2026-09-26 is a Saturday.
        parsed = qf.parse_payload(cn_payload(stamp="20260926103000"), "601899.SS", "CN")
        self.assertEqual(parsed["market_state"], "CLOSED")

    def test_cn_code_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "echoed_code_mismatch"):
            qf.parse_payload(cn_payload(code="600000"), "601899.SS", "CN")

    def test_cn_zero_price_is_not_a_quote(self):
        with self.assertRaisesRegex(ValueError, "invalid_price"):
            qf.parse_payload(cn_payload(price="0.000"), "601899.SS", "CN")

    def test_cn_missing_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unparseable_timestamp"):
            qf.parse_payload(cn_payload(stamp=""), "601899.SS", "CN")

    def test_us_ticker_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "echoed_code_mismatch"):
            qf.parse_payload(us_payload(venue_code="MSFT.OQ"), "GOOG", "US")

    def test_us_non_currency_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_currency"):
            qf.parse_payload(us_payload(currency="7"), "GOOG", "US")

    def test_etf_uses_the_same_cn_path(self):
        parsed = qf.parse_payload(cn_payload(key="sh515650", name="消费50ETF富国",
                                             code="515650", price="1.036"),
                                  "515650.SS", "CN")
        self.assertEqual(parsed["price"], 1.036)
        self.assertEqual(parsed["exchange"], "SSE")


class ClassificationTests(unittest.TestCase):
    def test_html_shell_is_broken_not_empty(self):
        self.assertEqual(qf.classify("<!DOCTYPE html><html></html>", 200), qf.HEALTH_BROKEN)

    def test_http_error_is_broken(self):
        self.assertEqual(qf.classify("Forbidden", 403), qf.HEALTH_BROKEN)

    def test_blank_body_is_empty(self):
        self.assertEqual(qf.classify("   ", 200), qf.HEALTH_EMPTY)

    def test_vendor_no_match_answer_is_empty(self):
        self.assertEqual(qf.classify('v_pv_none_match="1";', 200), qf.HEALTH_EMPTY)

    def test_lowercase_key_is_still_recognised(self):
        self.assertEqual(qf.classify(us_payload(), 200, key="usGOOG"), qf.HEALTH_OK)

    def test_unrelated_payload_is_broken(self):
        self.assertEqual(qf.classify('v_something_else="1";', 200, key="usGOOG"),
                         qf.HEALTH_BROKEN)

    def test_real_shapes_are_ok(self):
        self.assertEqual(qf.classify(cn_payload(), 200), qf.HEALTH_OK)
        self.assertEqual(qf.classify(us_payload(), 200), qf.HEALTH_OK)


class FetcherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_is_marked_secondary_and_never_primary(self):
        transport = FakeTransport({qf.source_url("601899.SS"): (200, cn_payload())})
        fetcher = qf.FallbackFetcher(http_get=transport, cache_dir=self.cache_dir,
                                     now=lambda: 1000.0)
        result = fetcher.fetch("601899.SS", primary_outcome="error")
        self.assertEqual(result["health"], qf.HEALTH_OK)
        record = result["record"]
        self.assertEqual(record["tier"], "secondary")
        self.assertEqual(record["source"], qf.SOURCE_TENCENT)
        self.assertEqual(record["source_locator"], "fallback:tencent:601899.SS")
        self.assertEqual(record["primary_outcome"], "error")
        self.assertEqual(record["retrieved_at"], "1970-01-01T00:16:40+00:00")
        self.assertNotIn("Yahoo", json.dumps(record, ensure_ascii=False))
        # The observed timestamp comes from the source, never from now().
        self.assertEqual(record["observed_at"], "2026-09-29T16:14:54+08:00")

    def test_us_record_carries_venue_and_currency_evidence(self):
        transport = FakeTransport({qf.source_url("GOOG"): (200, us_payload())})
        fetcher = qf.FallbackFetcher(http_get=transport, now=lambda: 1.0)
        record = fetcher.fetch("GOOG", primary_outcome="skipped_circuit_open")["record"]
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["exchange"], "NASDAQ")
        self.assertEqual(record["primary_outcome"], "skipped_circuit_open")

    def test_cache_is_used_then_bypassed(self):
        url = qf.source_url("GOOG")
        transport = FakeTransport({url: (200, us_payload())})
        fetcher = qf.FallbackFetcher(http_get=transport, cache_dir=self.cache_dir,
                                     now=lambda: 500.0)
        first = fetcher.fetch("GOOG")
        second = fetcher.fetch("GOOG")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(first["fetched_via"], "network")
        self.assertEqual(second["fetched_via"], "cache")
        fetcher.bypass_cache = True
        third = fetcher.fetch("GOOG")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(third["fetched_via"], "network")
        self.assertEqual(third["record"]["price"], 336.15)

    def test_expired_cache_is_not_reused(self):
        url = qf.source_url("GOOG")
        transport = FakeTransport({url: (200, us_payload())})
        clock = {"now": 0.0}
        fetcher = qf.FallbackFetcher(http_get=transport, cache_dir=self.cache_dir,
                                     ttl_seconds=60.0, now=lambda: clock["now"])
        fetcher.fetch("GOOG")
        clock["now"] = 61.0
        result = fetcher.fetch("GOOG")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(result["fetched_via"], "network")

    def test_transport_exception_is_reported_not_raised(self):
        def boom(url, headers):
            raise OSError("network down")

        fetcher = qf.FallbackFetcher(http_get=boom, cache_dir=self.cache_dir, now=lambda: 1.0)
        result = fetcher.fetch("GOOG")
        self.assertEqual(result["health"], qf.HEALTH_BROKEN)
        self.assertIsNone(result["record"])
        self.assertIn("secondary_response_broken", result["error"])

    def test_unsupported_market_has_no_fallback(self):
        fetcher = qf.FallbackFetcher(http_get=FakeTransport({}), now=lambda: 1.0)
        result = fetcher.fetch("0700.HK")
        self.assertIsNone(result["record"])
        self.assertEqual(result["health"], qf.HEALTH_EMPTY)
        self.assertEqual(result["error"], "no_secondary_source_for_symbol")

    def test_parse_failure_is_broken_not_a_price(self):
        transport = FakeTransport({qf.source_url("601899.SS"):
                                   (200, cn_payload(code="600000"))})
        fetcher = qf.FallbackFetcher(http_get=transport, now=lambda: 1.0)
        result = fetcher.fetch("601899.SS")
        self.assertEqual(result["health"], qf.HEALTH_BROKEN)
        self.assertIsNone(result["record"])
        self.assertIn("secondary_parse_failed", result["error"])

    def test_fetch_many_preserves_order_and_outcomes(self):
        transport = FakeTransport({qf.source_url("601899.SS"): (200, cn_payload()),
                                   qf.source_url("GOOG"): (200, us_payload())})
        fetcher = qf.FallbackFetcher(http_get=transport, now=lambda: 1.0)
        results = fetcher.fetch_many(["GOOG", "601899.SS"],
                                     primary_outcomes={"GOOG": "skipped_circuit_open"})
        self.assertEqual(list(results), ["GOOG", "601899.SS"])
        self.assertEqual(results["GOOG"]["record"]["primary_outcome"], "skipped_circuit_open")
        self.assertEqual(results["601899.SS"]["record"]["primary_outcome"], "error")


class RegistryTests(unittest.TestCase):
    def test_supported_markets_are_cn_and_us_only(self):
        self.assertEqual(sorted(qf.MARKET_SOURCES), ["CN", "US"])
        self.assertIsNone(qf.fallback_source_for("0700.HK"))
        self.assertIsNone(qf.fallback_source_for("0700.HK", "HK"))
        self.assertEqual(qf.fallback_source_for("601899.SS", "US"), None)
        self.assertEqual(qf.instrument_key("601899.SS"), "sh601899")
        self.assertEqual(qf.instrument_key("300253.SZ"), "sz300253")
        self.assertEqual(qf.instrument_key("GOOG"), "usGOOG")
        self.assertIsNone(qf.instrument_key("0700.HK"))


if __name__ == "__main__":
    unittest.main()
