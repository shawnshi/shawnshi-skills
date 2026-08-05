import copy
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dashboard_gate import validate_dashboard
from test_investment_controls import valid_dashboard


class DashboardPointInTimeContractTests(unittest.TestCase):
    def test_valid_strict_fixture_closes_dates_freshness_and_quote(self):
        self.assertEqual(
            validate_dashboard(valid_dashboard(), require_scenarios=True),
            [],
        )

    def test_scenario_date_must_equal_brief_date(self):
        payload = valid_dashboard()
        payload["scenario_analysis"]["as_of_date"] = "2026-07-21"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertIn(
            "scenario_analysis.as_of_date must equal research_brief.as_of_date "
            "for the strict current contract",
            errors,
        )

    def test_each_assumption_and_sensitivity_date_must_equal_brief_date(self):
        payload = valid_dashboard()
        payload["scenario_analysis"]["base"]["assumptions"][0][
            "as_of_date"
        ] = "2026-07-21"
        payload["scenario_analysis"]["sensitivity"][0][
            "as_of_date"
        ] = "2026-07-21"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(
            any(
                "base.assumptions[0].as_of_date must equal research_brief.as_of_date"
                in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "sensitivity[0].as_of_date must equal research_brief.as_of_date"
                in error
                for error in errors
            )
        )

    def test_valuation_inputs_after_cutoff_are_rejected(self):
        payload = valid_dashboard()
        payload["scenario_analysis"]["as_of_date"] = "2026-07-23"
        payload["scenario_analysis"]["base"]["assumptions"][0][
            "as_of_date"
        ] = "2026-07-23"
        payload["scenario_analysis"]["sensitivity"][0][
            "as_of_date"
        ] = "2026-07-23"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(any("scenario_analysis.as_of_date cannot be after" in e for e in errors))
        self.assertTrue(any("base.assumptions[0].as_of_date cannot be after" in e for e in errors))
        self.assertTrue(any("sensitivity[0].as_of_date cannot be after" in e for e in errors))

    def test_strict_freshness_statuses_must_match_derived_coverage(self):
        payload = valid_dashboard()
        payload["freshness_flags"]["price_data_status"] = "not_assessed"
        payload["freshness_flags"]["news_data_status"] = "fresh"
        payload["freshness_flags"]["stale_inputs"] = ["price_data"]
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertIn(
            "freshness_flags.price_data_status must equal derived status fresh",
            errors,
        )
        self.assertIn(
            "freshness_flags.news_data_status must equal derived status not_assessed",
            errors,
        )
        self.assertIn(
            "freshness_flags.stale_inputs must equal derived stale inputs []",
            errors,
        )

    def test_strict_contract_requires_actual_matching_quote_evidence(self):
        payload = valid_dashboard()
        payload["evidence_items"] = [payload["evidence_items"][0]]
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(any("timestamp-verified market_data quote" in e for e in errors))

        payload = valid_dashboard()
        quote = payload["evidence_items"][1]
        quote["symbol"] = "MSFT"
        quote["currency"] = "EUR"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(any("symbol must match" in e for e in errors))
        self.assertTrue(any("currency must match" in e for e in errors))

    def test_quote_timestamps_must_close_at_cutoff_and_within_state_threshold(self):
        payload = valid_dashboard()
        quote = payload["evidence_items"][1]
        quote["market_state"] = "REGULAR"
        quote["observed_at"] = "2026-07-22T19:00:00+00:00"
        quote["retrieved_at"] = "2026-07-22T20:05:01+00:00"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(any("quote age exceeds the strict REGULAR threshold" in e for e in errors))

        payload = valid_dashboard()
        quote = payload["evidence_items"][1]
        quote["observed_at"] = "2026-07-21T20:00:00+00:00"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(any("observed_at date must equal" in e for e in errors))

    def test_old_company_disclosure_is_allowed_only_as_historical_in_strict_mode(self):
        payload = valid_dashboard()
        self.assertEqual(
            validate_dashboard(payload, require_scenarios=True),
            [],
        )
        payload["evidence_items"][0]["freshness"] = "current"
        errors = validate_dashboard(payload, require_scenarios=True)
        self.assertTrue(
            any("company disclosure was published before the Brief cutoff" in e for e in errors)
        )

    def test_archive_read_keeps_explicit_legacy_compatibility(self):
        payload = valid_dashboard()
        payload["evidence_items"] = [copy.deepcopy(payload["evidence_items"][0])]
        payload["evidence_items"][0]["freshness"] = "current"
        payload["freshness_flags"] = {
            "price_data_fresh": "legacy-unverified",
            "info_data_fresh": "legacy-unverified",
            "news_data_fresh": "legacy-unverified",
            "portfolio_data_fresh": "legacy-unverified",
            "stale_inputs": [],
        }
        self.assertEqual(validate_dashboard(payload), [])


if __name__ == "__main__":
    unittest.main()
