import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import test_investment_controls as fixtures
from dashboard_gate import validate_dashboard
from live_evidence_probe import _recent_filings, probe_us_stock
from test_p0_quote_contracts import expected_position, quote_result
from test_p1_research_evidence_contracts import probe_fetcher
from yf import build_portfolio_batch_audit


NOW_EPOCH = 1_800_000_000.0
RESERVED_TEST_CONTACT = "PIA Research formal@research.example"


def quote_audit(*, market_state, age_seconds, cap_seconds=None):
    result = quote_result(
        market_state=market_state,
        quote_epoch=NOW_EPOCH - age_seconds,
    )
    kwargs = {}
    if cap_seconds is not None:
        kwargs["max_quote_age_seconds"] = cap_seconds
    return build_portfolio_batch_audit(
        [result],
        requested_count=1,
        expected_symbols=["AAPL"],
        portfolio_load_status="ok",
        expected_position_metadata={"AAPL": expected_position()},
        now_epoch=NOW_EPOCH,
        **kwargs,
    )


class EvidenceTierContractTests(unittest.TestCase):
    def test_sec_forms_have_distinct_current_tiers(self):
        submissions = {
            "cik": "0000320193",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"],
                    "filingDate": ["2026-01-01"] * 6,
                    "accessionNumber": ["a", "b", "c", "d", "e", "f"],
                    "primaryDocument": [f"document-{index}.htm" for index in range(6)],
                }
            },
        }
        filings = _recent_filings(submissions, limit=6)
        self.assertEqual(
            [item["source_tier"] for item in filings],
            [
                "annual_audited_filing",
                "annual_audited_filing",
                "quarterly_filing",
                "quarterly_filing",
                "current_report",
                "current_report",
            ],
        )
        self.assertNotIn("audited_filing", {item["source_tier"] for item in filings})

    def test_current_live_probe_never_emits_legacy_filing_tier(self):
        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            fetch_json=probe_fetcher(forms=["10-K", "10-Q", "8-K"]),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        disclosures = result["sources"]["company_disclosures"]
        self.assertEqual(disclosures["source_tier"], "regulator")
        self.assertEqual(
            {item["source_tier"] for item in disclosures["filings"]},
            {"annual_audited_filing", "quarterly_filing", "current_report"},
        )

    def test_primary_policy_requires_an_actual_matching_primary_item(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["research_brief"]["source_policy"]["allowed_source_tiers"] = [
            "annual_audited_filing",
            "market_data",
        ]
        dashboard["evidence_items"][0]["source_tier"] = "market_data"
        errors = validate_dashboard(dashboard)
        self.assertIn(
            "research_brief.source_policy.primary_source_required requires at least "
            "one matching primary evidence item",
            errors,
        )

    def test_legacy_tier_is_archive_readable_but_rejected_for_current_output(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["research_brief"]["source_policy"]["allowed_source_tiers"] = [
            "audited_filing",
            "market_data",
        ]
        dashboard["evidence_items"][0]["source_tier"] = "audited_filing"
        self.assertEqual(validate_dashboard(dashboard), [])
        strict_errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(any("archive-only" in error for error in strict_errors))
        self.assertTrue(any("matching primary evidence item" in error for error in strict_errors))


class MarketStateFreshnessTests(unittest.TestCase):
    def test_regular_market_uses_fifteen_minute_limit(self):
        self.assertTrue(quote_audit(market_state="REGULAR", age_seconds=899)["complete"])
        report = quote_audit(market_state="REGULAR", age_seconds=901)
        self.assertFalse(report["complete"])
        self.assertEqual(
            report["quote_freshness_contracts"]["AAPL"]["applied_max_age_seconds"],
            900.0,
        )

    def test_pre_and_post_market_use_twenty_four_hour_limit(self):
        for state in ("PREPRE", "PRE", "POST", "POSTPOST"):
            with self.subTest(state=state):
                self.assertTrue(
                    quote_audit(market_state=state, age_seconds=86_399)["complete"]
                )
                self.assertFalse(
                    quote_audit(market_state=state, age_seconds=86_401)["complete"]
                )

    def test_closed_market_uses_seventy_two_hour_limit_and_fails_long_holidays(self):
        self.assertTrue(quote_audit(market_state="CLOSED", age_seconds=259_199)["complete"])
        report = quote_audit(market_state="CLOSED", age_seconds=259_201)
        self.assertFalse(report["complete"])
        self.assertEqual(
            report["quote_freshness_policy"]["long_holiday_behavior"],
            "fail_closed_after_state_threshold",
        )
        self.assertFalse(report["quote_freshness_policy"]["calendar_aware"])

    def test_caller_cap_can_tighten_but_cannot_weaken_state_policy(self):
        stricter = quote_audit(
            market_state="CLOSED",
            age_seconds=3_601,
            cap_seconds=3_600,
        )
        self.assertFalse(stricter["complete"])
        cannot_weaken = quote_audit(
            market_state="CLOSED",
            age_seconds=259_201,
            cap_seconds=7 * 24 * 60 * 60,
        )
        self.assertFalse(cannot_weaken["complete"])
        self.assertEqual(
            cannot_weaken["quote_freshness_contracts"]["AAPL"]["applied_max_age_seconds"],
            259_200.0,
        )

    def test_live_probe_records_policy_and_fails_closed_when_regular_quote_is_stale(self):
        now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            fetch_json=probe_fetcher(
                market_state="REGULAR",
                quote_epoch=now.timestamp() - 901,
            ),
            now=now,
        )
        self.assertFalse(result["valid"])
        policy = result["sources"]["market_data"]["freshness_policy"]
        self.assertEqual(policy["max_age_seconds"], 900)
        self.assertEqual(policy["version"], "market-state-v1")

    def test_live_probe_fails_closed_when_market_state_is_missing(self):
        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            fetch_json=probe_fetcher(market_state=None),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertFalse(result["valid"])
        self.assertIn(
            "market state is missing or unsupported; quote freshness cannot be established",
            result["data_errors"],
        )
        self.assertIsNone(
            result["sources"]["market_data"]["freshness_policy"]["max_age_seconds"]
        )

    def test_live_probe_derives_closed_state_from_chart_trading_periods(self):
        now = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
        base_fetch = probe_fetcher(
            market_state=None,
            quote_epoch=now.timestamp() - 7 * 60 * 60,
        )

        def fetch(url, headers, timeout):
            payload, status, final_url = base_fetch(url, headers, timeout)
            if "query1.finance.yahoo.com" in url:
                payload["chart"]["result"][0]["meta"]["currentTradingPeriod"] = {
                    "pre": {
                        "start": now.timestamp() - 18 * 60 * 60,
                        "end": now.timestamp() - 12 * 60 * 60,
                    },
                    "regular": {
                        "start": now.timestamp() - 12 * 60 * 60,
                        "end": now.timestamp() - 8 * 60 * 60,
                    },
                    "post": {
                        "start": now.timestamp() - 8 * 60 * 60,
                        "end": now.timestamp() - 4 * 60 * 60,
                    },
                }
            return payload, status, final_url

        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            fetch_json=fetch,
            now=now,
        )
        market_data = result["sources"]["market_data"]
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(market_data["market_state"], "CLOSED")
        self.assertEqual(
            market_data["market_state_source"],
            "derived_from_current_trading_period",
        )


if __name__ == "__main__":
    unittest.main()
