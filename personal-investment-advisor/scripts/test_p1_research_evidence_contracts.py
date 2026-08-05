import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlparse

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import live_evidence_probe as live_probe_module
import quality_screener as quality_module
import test_investment_controls as fixtures
from live_evidence_probe import probe_us_stock
from quality_screener import evaluate_ticker, load_profiles
from research_brief_gate import validate_research_brief


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
RESERVED_TEST_CONTACT = "PIA Research formal@research.example"


def financial_frames():
    columns = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    income = pd.DataFrame(
        {
            columns[0]: [12.0, 15.0, -2.0, 100.0, 40.0, 100.0],
            columns[1]: [10.0, 13.0, -2.0, 90.0, 35.0, 98.0],
        },
        index=[
            "Net Income",
            "EBIT",
            "Interest Expense",
            "Total Revenue",
            "Gross Profit",
            "Basic Average Shares",
        ],
    )
    cashflow = pd.DataFrame(
        {
            columns[0]: [15.0, 10.0],
            columns[1]: [13.0, 8.0],
        },
        index=["Operating Cash Flow", "Free Cash Flow"],
    )
    balance = pd.DataFrame(
        {
            columns[0]: [80.0],
            columns[1]: [75.0],
        },
        index=["Stockholders Equity"],
    )
    return income, cashflow, balance


def probe_fetcher(
    *,
    quote_instrument_type="EQUITY",
    company_name="Apple Inc. Common Stock",
    forms=None,
    market_state="CLOSED",
    quote_epoch=None,
):
    forms = forms or ["10-Q"]
    filing_dates = ["2026-05-01"] * len(forms)
    accessions = [f"0000320193-26-{index + 1:06d}" for index in range(len(forms))]
    documents = [f"document-{index + 1}.htm" for index in range(len(forms))]
    quote_epoch = quote_epoch or datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc).timestamp()

    def fetch(url, headers, timeout):
        hostname = urlparse(url).hostname
        if hostname == "query1.finance.yahoo.com":
            payload = {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": "AAPL",
                                "instrumentType": quote_instrument_type,
                                "regularMarketTime": quote_epoch,
                                "regularMarketPrice": 200.0,
                                "currency": "USD",
                                "exchangeName": "NMS",
                                "marketState": market_state,
                            }
                        }
                    ]
                }
            }
        elif hostname == "api.nasdaq.com":
            payload = {
                "data": {
                    "symbol": "AAPL",
                    "companyName": company_name,
                    "exchange": "NASDAQ-GS",
                    "marketStatus": "Closed",
                    "assetClass": "STOCKS",
                }
            }
        elif "company_tickers_exchange" in url:
            payload = {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [[320193, company_name, "AAPL", "Nasdaq"]],
            }
        elif "data.sec.gov/submissions" in url:
            payload = {
                "cik": "0000320193",
                "name": company_name,
                "tickers": ["AAPL"],
                "exchanges": ["Nasdaq"],
                "filings": {
                    "recent": {
                        "form": forms,
                        "filingDate": filing_dates,
                        "accessionNumber": accessions,
                        "primaryDocument": documents,
                    }
                },
            }
        else:
            raise AssertionError(f"unexpected URL: {url}")
        return payload, 200, url

    return fetch


class ResearchBriefStrongTypeTests(unittest.TestCase):
    def test_rejects_non_string_identifiers_text_and_list_items(self):
        cases = [
            (("instrument", "symbol"), 123, "instrument.symbol"),
            (("instrument", "currency"), 999, "instrument.currency"),
            (("benchmark", "symbol"), False, "benchmark.symbol"),
            (("research_question",), True, "research_question"),
            (("market_consensus",), {}, "market_consensus"),
            (("core_hypothesis",), 1, "core_hypothesis"),
            (("falsification_conditions",), ["valid", 2], "falsification_conditions"),
            (("key_variables",), [False], "key_variables"),
        ]
        for path, value, expected in cases:
            with self.subTest(path=path):
                brief = copy.deepcopy(fixtures.valid_brief())
                target = brief
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                errors = validate_research_brief(brief)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_horizon_rejects_boolean_and_float(self):
        for value in (True, 1.5, "90", 0, -1):
            with self.subTest(value=value):
                brief = copy.deepcopy(fixtures.valid_brief())
                brief["investment_horizon_days"] = value
                self.assertTrue(
                    any(
                        "investment_horizon_days must be a positive integer" in error
                        for error in validate_research_brief(brief)
                    )
                )

    def test_decision_scope_is_fixed_to_research_only(self):
        brief = copy.deepcopy(fixtures.valid_brief())
        brief["output_contract"]["decision_scope"] = "portfolio_context"
        self.assertIn(
            "output_contract.decision_scope must be research_only",
            validate_research_brief(brief),
        )

    def test_market_currency_and_profile_market_are_closed(self):
        brief = copy.deepcopy(fixtures.valid_brief())
        brief["instrument"]["currency"] = "CNY"
        errors = validate_research_brief(brief)
        self.assertTrue(any("must be USD for market US" in error for error in errors))

        brief = copy.deepcopy(fixtures.valid_brief())
        brief["method_profile"] = "a_share_basic"
        errors = validate_research_brief(brief)
        self.assertTrue(any("does not apply to market US" in error for error in errors))

    def test_financial_institution_requires_bank_or_insurance_identity(self):
        brief = copy.deepcopy(fixtures.valid_brief())
        brief["method_profile"] = "financial_institution"
        errors = validate_research_brief(brief)
        self.assertTrue(any("requires instrument.industry_type" in error for error in errors))

        brief["instrument"]["industry_type"] = "bank"
        self.assertEqual(validate_research_brief(brief), [])

    def test_non_object_root_fails_closed(self):
        self.assertEqual(
            validate_research_brief([]),
            ["research brief payload must be an object"],
        )


class QualityMethodContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = load_profiles()
        cls.profiles = cls.payload["profiles"]

    def test_profile_metadata_binds_market_asset_and_industry(self):
        self.assertEqual(self.profiles["a_share_basic"]["applicable_markets"], ["CN"])
        self.assertEqual(
            self.profiles["financial_institution"]["applicable_industry_types"],
            ["bank", "insurance"],
        )
        for profile in self.profiles.values():
            self.assertTrue(profile["profile_version"])
            self.assertTrue(profile["applicable_markets"])
            self.assertTrue(profile["applicable_asset_types"])

    def test_wrong_profile_context_returns_insufficient_evidence_without_fetch(self):
        cases = [
            ("AAPL", "a_share_basic", "US", "stock"),
            ("AAPL", "etf_research", "US", "stock"),
            ("QQQ", "quality_equity", "US", "etf"),
        ]
        with patch.object(quality_module, "fetch_yf_data") as fetch:
            for symbol, profile_name, market, asset_type in cases:
                with self.subTest(profile=profile_name):
                    result = evaluate_ticker(
                        symbol,
                        profile_name,
                        self.profiles[profile_name],
                        market=market,
                        asset_type=asset_type,
                        as_of_date="2026-07-22",
                        now=NOW,
                    )
                    self.assertEqual(result["status"], "insufficient_evidence")
            fetch.assert_not_called()

    def test_financial_profile_requires_industry_type(self):
        result = evaluate_ticker(
            "JPM",
            "financial_institution",
            self.profiles["financial_institution"],
            market="US",
            asset_type="stock",
            as_of_date="2026-07-22",
            now=NOW,
        )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertTrue(any("industry_type" in item for item in result["applicability_errors"]))

    def test_evidence_only_profile_is_not_applicable_only_for_matching_etf(self):
        result = evaluate_ticker(
            "QQQ",
            "etf_research",
            self.profiles["etf_research"],
            market="US",
            asset_type="etf",
            as_of_date="2026-07-22",
            now=NOW,
        )
        self.assertEqual(result["status"], "not_applicable")
        self.assertEqual(result["profile_version"], "3.0")
        self.assertIsNone(result["source_locator"])

    def test_successful_screen_carries_provenance_and_data_period(self):
        income, cashflow, balance = financial_frames()
        with patch.object(
            quality_module,
            "fetch_yf_data",
            return_value=(object(), income, cashflow, balance),
        ):
            result = evaluate_ticker(
                "AAPL",
                "quality_equity",
                self.profiles["quality_equity"],
                market="US",
                asset_type="stock",
                as_of_date="2026-07-30",
                profile_version=self.payload["version"],
                now=NOW,
            )

        self.assertEqual(result["profile_version"], "3.0")
        self.assertEqual(result["data_period"]["end"], "2025-12-31")
        self.assertEqual(result["retrieved_at"], NOW.isoformat())
        self.assertEqual(result["as_of_date"], "2026-07-30")
        self.assertTrue(result["source_locator"].startswith("https://finance.yahoo.com/"))
        self.assertIn(result["status"], {"pass", "fail", "insufficient_data"})

    def test_unknown_profile_cli_returns_stable_json(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "quality_screener.py"),
                "--tickers",
                "AAPL",
                "--profile",
                "does_not_exist",
                "--market",
                "US",
                "--asset-type",
                "stock",
                "--as-of-date",
                "2026-07-22",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["status"], "insufficient_evidence")
        self.assertIn("unknown profile", payload[0]["reason"])
        self.assertNotIn("error:", result.stderr.lower())


class LiveEvidenceContractTests(unittest.TestCase):
    def test_explicit_cik_skips_blocked_ticker_mapping_and_uses_submissions_identity(self):
        base_fetch = probe_fetcher()
        requested_urls = []

        def fetch(url, headers, timeout):
            requested_urls.append(url)
            if "company_tickers_exchange" in url:
                raise AssertionError("explicit CIK must skip the SEC ticker mapping")
            return base_fetch(url, headers, timeout)

        with patch.object(
            live_probe_module, "_formal_sec_contact_allowed", return_value=True
        ):
            result = probe_us_stock(
                "AAPL",
                RESERVED_TEST_CONTACT,
                cik="320193",
                fetch_json=fetch,
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertTrue(result["formal_use_allowed"])
        self.assertTrue(all(result["cross_checks"].values()))
        self.assertEqual(
            result["sources"]["regulator_identity"]["association_mode"],
            "explicit_cik",
        )
        self.assertEqual(result["sources"]["regulator_identity"]["cik"], "0000320193")
        self.assertFalse(any("company_tickers_exchange" in url for url in requested_urls))

    def test_explicit_cik_mismatch_fails_closed(self):
        base_fetch = probe_fetcher()

        def fetch(url, headers, timeout):
            payload, status, final_url = base_fetch(url, headers, timeout)
            if "data.sec.gov/submissions" in url:
                payload = copy.deepcopy(payload)
                payload["cik"] = "0000789019"
            return payload, status, final_url

        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            cik="320193",
            fetch_json=fetch,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

        self.assertFalse(result["identity_valid"])
        self.assertFalse(result["formal_use_allowed"])
        self.assertIn(
            "cross-check failed: submissions_cik_match",
            result["identity_errors"],
        )

    def test_invalid_explicit_cik_fails_before_network(self):
        fetch = Mock()

        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            cik="12345678901",
            fetch_json=fetch,
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "identity_invalid")
        self.assertFalse(result["formal_use_allowed"])
        self.assertTrue(any("1 to 10 digits" in item for item in result["identity_errors"]))
        fetch.assert_not_called()

    def test_explicit_cik_never_bypasses_real_contact_gate(self):
        result = probe_us_stock(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            cik="320193",
            fetch_json=probe_fetcher(),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

        self.assertTrue(result["identity_valid"])
        self.assertTrue(result["valid"])
        self.assertFalse(result["formal_use_allowed"])
        self.assertEqual(result["status"], "formal_use_blocked")

    def test_identity_status_and_source_tiers_are_schema_compatible(self):
        with patch.object(
            live_probe_module, "_formal_sec_contact_allowed", return_value=True
        ):
            result = probe_us_stock(
                "AAPL",
                RESERVED_TEST_CONTACT,
                fetch_json=probe_fetcher(),
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )
        self.assertTrue(result["identity_valid"])
        self.assertTrue(result["valid"])
        self.assertTrue(result["formal_use_allowed"])
        self.assertEqual(result["status"], "complete")
        tiers = {source["source_tier"] for source in result["sources"].values()}
        self.assertEqual(tiers, {"market_data", "exchange", "regulator"})
        filing_tiers = {
            filing["source_tier"]
            for filing in result["sources"]["company_disclosures"]["filings"]
        }
        self.assertEqual(filing_tiers, {"quarterly_filing"})
        self.assertNotIn("audited_filing", filing_tiers)

    def test_test_contact_preserves_identity_but_blocks_formal_use(self):
        result = probe_us_stock(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            fetch_json=probe_fetcher(),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertTrue(result["identity_valid"])
        self.assertTrue(result["valid"])
        self.assertFalse(result["formal_use_allowed"])
        self.assertEqual(result["status"], "formal_use_blocked")

    def test_adr_and_foreign_issuer_forms_fail_identity(self):
        result = probe_us_stock(
            "AAPL",
            RESERVED_TEST_CONTACT,
            fetch_json=probe_fetcher(
                quote_instrument_type="ADR",
                company_name="Example PLC American Depositary Shares",
                forms=["20-F", "6-K"],
            ),
            now=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )
        self.assertFalse(result["identity_valid"])
        self.assertFalse(result["formal_use_allowed"])
        self.assertEqual(result["status"], "identity_invalid")
        self.assertTrue(any("foreign issuer" in item for item in result["identity_errors"]))
        self.assertTrue(any("depositary" in item.lower() for item in result["identity_errors"]))

    def test_missing_sec_user_agent_is_structured_json(self):
        stdout = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            sys,
            "argv",
            ["live_evidence_probe.py", "--symbol", "AAPL"],
        ), contextlib.redirect_stdout(stdout):
            return_code = live_probe_module.main()
        self.assertEqual(return_code, 2)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "configuration_error")
        self.assertFalse(result["identity_valid"])
        self.assertFalse(result["formal_use_allowed"])

    def test_cli_success_is_bound_to_formal_use_allowed(self):
        blocked = {
            "status": "formal_use_blocked",
            "identity_valid": True,
            "valid": True,
            "formal_use_allowed": False,
            "errors": [],
        }
        stdout = io.StringIO()
        with patch.object(live_probe_module, "probe_us_stock", return_value=blocked), patch.object(
            sys,
            "argv",
            [
                "live_evidence_probe.py",
                "--symbol",
                "AAPL",
                "--sec-user-agent",
                "PersonalInvestmentAdvisor/1.0 (test)",
            ],
        ), contextlib.redirect_stdout(stdout):
            return_code = live_probe_module.main()
        self.assertEqual(return_code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["formal_use_allowed"])

    def test_cli_passes_explicit_cik_to_probe(self):
        blocked = {
            "status": "formal_use_blocked",
            "identity_valid": True,
            "valid": True,
            "formal_use_allowed": False,
            "errors": [],
        }
        stdout = io.StringIO()
        with patch.object(
            live_probe_module, "probe_us_stock", return_value=blocked
        ) as probe, patch.object(
            sys,
            "argv",
            [
                "live_evidence_probe.py",
                "--symbol",
                "AAPL",
                "--cik",
                "320193",
                "--sec-user-agent",
                "PersonalInvestmentAdvisor/1.0 (test)",
            ],
        ), contextlib.redirect_stdout(stdout):
            return_code = live_probe_module.main()

        self.assertEqual(return_code, 1)
        probe.assert_called_once_with(
            "AAPL",
            "PersonalInvestmentAdvisor/1.0 (test)",
            timeout=20,
            cik="320193",
        )


if __name__ == "__main__":
    unittest.main()
