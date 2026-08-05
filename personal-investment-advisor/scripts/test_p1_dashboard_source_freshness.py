import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import test_investment_controls as fixtures
from dashboard_gate import validate_dashboard


class DashboardSourceLocatorContractTests(unittest.TestCase):
    def test_strict_dashboard_rejects_short_test_private_and_unregistered_locators(self):
        bad_locators = (
            "paragraph 3",
            "http://localhost/filing",
            "https://example.test/filing",
            "http://127.0.0.1/filing",
            "https://intranet/filing",
            "dataset://unregistered/filing",
            "dataset://pia/%2e%2e/private",
            "sec://accession/not-an-accession",
        )
        for locator in bad_locators:
            with self.subTest(locator=locator):
                dashboard = fixtures.valid_dashboard()
                dashboard["evidence_items"][0]["source_locator"] = locator
                errors = validate_dashboard(dashboard, require_scenarios=True)
                self.assertTrue(
                    any(
                        "evidence_items[0].source_locator must be a public HTTP(S) URL"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_strict_dashboard_accepts_registered_sec_and_dataset_locators_by_type(self):
        for locator in (
            "sec://accession/0000320193-26-000001",
            "sec://cik/0000320193",
        ):
            with self.subTest(locator=locator):
                dashboard = fixtures.valid_dashboard()
                dashboard["evidence_items"][0]["source_locator"] = locator
                self.assertEqual(
                    validate_dashboard(dashboard, require_scenarios=True), []
                )

        dashboard = fixtures.valid_dashboard()
        dashboard["evidence_items"][1][
            "source_locator"
        ] = "dataset://validated-market-data/aapl/2026-07-22"
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])

        dashboard["evidence_items"][1][
            "source_locator"
        ] = "sec://cik/0000320193"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(
            any("evidence_items[1].source_locator must be a public HTTP(S) URL" in e for e in errors)
        )

    def test_strict_sources_require_timestamped_retrieval_and_content_digest(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["evidence_items"][0].pop("content_sha256")
        dashboard["evidence_items"][1]["retrieved_at"] = "2026-07-22"
        dashboard["scenario_analysis"]["base"]["assumptions"][0].pop(
            "content_sha256"
        )
        dashboard["scenario_analysis"]["sensitivity"][0][
            "retrieved_at"
        ] = "2026-07-22"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(any("evidence_items[0].content_sha256" in e for e in errors))
        self.assertTrue(any("evidence_items[1].retrieved_at must be a timezone-aware" in e for e in errors))
        self.assertTrue(any("base.assumptions[0].content_sha256" in e for e in errors))
        self.assertTrue(any("sensitivity[0].retrieved_at must be a timezone-aware" in e for e in errors))

    def test_valuation_input_locators_cannot_be_free_text(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["scenario_analysis"]["base"]["assumptions"][0][
            "source_locator"
        ] = "filing paragraph 3"
        dashboard["scenario_analysis"]["sensitivity"][0][
            "source_locator"
        ] = "localhost model"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(any("base.assumptions[0].source_locator must be a public" in e for e in errors))
        self.assertTrue(any("sensitivity[0].source_locator must be a public" in e for e in errors))

    def test_monitoring_policy_locator_is_controlled_in_strict_mode(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["monitoring_boundaries"] = fixtures.valid_monitoring_boundaries()
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])
        dashboard["monitoring_boundaries"]["boundaries"][0][
            "source_locator"
        ] = "user policy paragraph 3"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(
            any("must be a controlled dataset URI" in error for error in errors)
        )


class DashboardDerivedFreshnessTests(unittest.TestCase):
    def test_portfolio_freshness_is_derived_from_snapshot_provenance(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["portfolio_context"] = {
            "has_position": True,
            "quantity": 1,
            "avg_cost": 100,
            "current_price": 100,
            "currency": "USD",
            "base_currency": "USD",
            "fx_rate_to_base": 1,
            "market_value": 100,
            "cost_basis": 100,
            "unrealized_pnl": 0,
            "unrealized_pnl_pct": 0,
            "position_status": "matched",
            "snapshot_as_of": "2026-07-22",
            "retrieved_at": "2026-07-22T20:05:00+00:00",
            "source_locator": "dataset://pia/portfolio-snapshot/2026-07-22",
            "content_sha256": "7" * 64,
        }
        dashboard["holding_assessment"] = {
            "holding_context": "existing position",
            "cost_basis_context": "user-authorized portfolio snapshot",
            "risk_evidence": "research-only observation",
            "monitoring_conditions": ["verify the next filing"],
        }
        dashboard["freshness_flags"]["portfolio_data_status"] = "fresh"
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])

        dashboard["portfolio_context"]["snapshot_as_of"] = "2026-07-21"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertIn(
            "freshness_flags.portfolio_data_status must equal derived status historical",
            errors,
        )

    def test_missing_news_and_portfolio_are_not_assessed_or_not_applicable(self):
        dashboard = fixtures.valid_dashboard()
        flags = dashboard["freshness_flags"]
        self.assertEqual(flags["price_data_status"], "fresh")
        self.assertEqual(flags["info_data_status"], "historical")
        self.assertEqual(flags["news_data_status"], "not_assessed")
        self.assertEqual(flags["portfolio_data_status"], "not_applicable")
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])

        dashboard["freshness_flags"]["news_data_status"] = "fresh"
        dashboard["freshness_flags"]["portfolio_data_status"] = "fresh"
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertIn(
            "freshness_flags.news_data_status must equal derived status not_assessed",
            errors,
        )
        self.assertIn(
            "freshness_flags.portfolio_data_status must equal derived status not_applicable",
            errors,
        )

    def test_news_status_becomes_fresh_only_when_matching_evidence_exists(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["research_brief"]["source_policy"]["allowed_source_tiers"].append(
            "secondary"
        )
        dashboard["evidence_items"].append(
            {
                "fact": "The company published a dated product update.",
                "connection": "The update is relevant to the monitored catalyst.",
                "deduction": "The event requires follow-up evidence.",
                "source_type": "news",
                "source_tier": "secondary",
                "source_locator": "https://www.reuters.com/technology/company-update",
                "published_at": "2026-07-22T10:00:00+00:00",
                "retrieved_at": "2026-07-22T10:05:00+00:00",
                "content_sha256": "6" * 64,
                "as_of_date": "2026-07-22",
                "freshness": "current",
                "confidence": "medium",
                "independent_source_count": 1,
            }
        )
        dashboard["freshness_flags"]["news_data_status"] = "fresh"
        self.assertEqual(validate_dashboard(dashboard, require_scenarios=True), [])

    def test_boolean_freshness_claims_are_not_current_contract_statuses(self):
        dashboard = fixtures.valid_dashboard()
        dashboard["freshness_flags"] = {
            "price_data_fresh": True,
            "info_data_fresh": True,
            "news_data_fresh": True,
            "portfolio_data_fresh": True,
            "stale_inputs": [],
        }
        errors = validate_dashboard(dashboard, require_scenarios=True)
        self.assertTrue(any("missing freshness_flags field: price_data_status" in e for e in errors))
        self.assertTrue(any("must equal derived status not_assessed" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
