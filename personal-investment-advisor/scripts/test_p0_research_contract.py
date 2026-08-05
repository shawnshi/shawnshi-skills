import copy
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from research_brief_gate import validate_research_brief


def valid_brief():
    return {
        "research_id": "R-P0-001",
        "instrument": {
            "symbol": "AAPL",
            "market": "US",
            "asset_type": "stock",
            "currency": "USD",
        },
        "as_of_date": "2026-07-22",
        "investment_horizon_days": 90,
        "benchmark": {"symbol": "SPY", "market": "US", "currency": "USD"},
        "method_profile": "quality_equity",
        "research_question": "Will gross margin remain above consensus?",
        "market_consensus": {
            "metric": "gross_margin",
            "value": 0.405,
            "unit": "ratio",
            "period_end": "2026-09-30",
            "source_locator": "https://www.nasdaq.com/market-activity/stocks/aapl/earnings",
            "as_of_date": "2026-07-22",
        },
        "core_hypothesis": {
            "statement": "Gross margin resilience is underestimated.",
            "metric": "gross_margin",
            "independent_estimate": {"value": 0.43, "unit": "ratio"},
            "expected_gap": {"absolute": 0.025, "direction": "above"},
            "falsified_when": {
                "operator": "<",
                "target": 0.40,
                "deadline": "2026-08-01",
            },
        },
        "falsification_conditions": ["Gross margin falls below the stated threshold"],
        "key_variables": ["gross_margin", "revenue_growth"],
        "source_policy": {
            "cutoff_date": "2026-07-22",
            "allowed_source_tiers": [
                "company_primary",
                "annual_audited_filing",
                "market_data",
            ],
            "primary_source_required": True,
        },
        "output_contract": {
            "decision_scope": "research_only",
            "required_scenarios": ["base", "bull", "bear"],
            "include_counterevidence": True,
            "transaction_cost_bps": 10,
            "dual_trigger_policy": "exclude",
        },
    }


class ResearchBriefP0ContractTests(unittest.TestCase):
    def test_schema_declares_structured_falsifiable_hypothesis(self):
        schema = json.loads(
            (ROOT / "references" / "research_brief_schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(schema["version"], "1.4")
        self.assertEqual(
            schema["required_core_hypothesis_fields"],
            ["statement", "metric", "independent_estimate", "expected_gap", "falsified_when"],
        )
        self.assertEqual(
            schema["required_hypothesis_falsifier_fields"],
            ["operator", "target", "deadline"],
        )
        self.assertEqual(
            schema["enums"]["hypothesis_operator"],
            [">=", ">", "<=", "<", "=="],
        )
        self.assertEqual(schema["enums"]["dual_trigger_policy"], ["exclude"])

    def test_valid_structured_hypothesis_passes(self):
        self.assertEqual(validate_research_brief(valid_brief()), [])

    def test_conservative_dual_trigger_policy_is_rejected_for_formal_brief(self):
        brief = valid_brief()
        brief["output_contract"]["dual_trigger_policy"] = "conservative"
        self.assertIn(
            "output_contract.dual_trigger_policy is invalid",
            validate_research_brief(brief),
        )

    def test_consensus_and_independent_gap_are_machine_checked(self):
        brief = valid_brief()
        brief["core_hypothesis"]["expected_gap"]["absolute"] = 0.01
        errors = validate_research_brief(brief)
        self.assertIn(
            "core_hypothesis.expected_gap.absolute must equal independent estimate minus consensus",
            errors,
        )

    def test_archive_only_source_tier_is_rejected_for_current_brief(self):
        brief = valid_brief()
        brief["source_policy"]["allowed_source_tiers"] = ["audited_filing"]
        errors = validate_research_brief(brief)
        self.assertTrue(any("archive-only" in error for error in errors), errors)

    def test_consensus_metric_and_unit_must_bind_to_hypothesis(self):
        brief = valid_brief()
        brief["market_consensus"]["metric"] = "revenue_growth"
        brief["core_hypothesis"]["independent_estimate"]["unit"] = "percent"
        errors = validate_research_brief(brief)
        self.assertIn("market_consensus.metric must match core_hypothesis.metric", errors)
        self.assertIn(
            "core_hypothesis.independent_estimate.unit must match market_consensus.unit",
            errors,
        )

    def test_future_as_of_and_cutoff_dates_fail_closed(self):
        brief = valid_brief()
        future = (date.today() + timedelta(days=1)).isoformat()
        brief["as_of_date"] = future
        brief["source_policy"]["cutoff_date"] = future
        errors = validate_research_brief(brief)
        self.assertIn("as_of_date cannot be in the future", errors)
        self.assertIn("source_policy.cutoff_date cannot be in the future", errors)

    def test_future_cutoff_date_is_rejected_independently(self):
        brief = valid_brief()
        brief["source_policy"]["cutoff_date"] = (
            date.today() + timedelta(days=1)
        ).isoformat()
        errors = validate_research_brief(brief)
        self.assertIn("source_policy.cutoff_date cannot be in the future", errors)

    def test_plain_string_hypothesis_is_rejected(self):
        brief = valid_brief()
        brief["core_hypothesis"] = "Gross margin resilience is underestimated."
        self.assertIn(
            "core_hypothesis must be an object",
            validate_research_brief(brief),
        )

    def test_hypothesis_requires_complete_machine_readable_falsifier(self):
        cases = [
            (("statement",), "", "core_hypothesis.statement"),
            (("metric",), "", "core_hypothesis.metric"),
            (("falsified_when",), "missing", "core_hypothesis.falsified_when"),
            (
                ("falsified_when", "operator"),
                "contains",
                "core_hypothesis.falsified_when.operator",
            ),
            (
                ("falsified_when", "target"),
                True,
                "core_hypothesis.falsified_when.target",
            ),
            (
                ("falsified_when", "deadline"),
                "not-a-date",
                "core_hypothesis.falsified_when.deadline",
            ),
        ]
        for path, value, expected in cases:
            with self.subTest(path=path):
                brief = copy.deepcopy(valid_brief())
                target = brief["core_hypothesis"]
                for key in path[:-1]:
                    target = target[key]
                if value == "missing":
                    target.pop(path[-1])
                else:
                    target[path[-1]] = value
                errors = validate_research_brief(brief)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_hypothesis_metric_must_bind_to_key_variables(self):
        brief = valid_brief()
        brief["core_hypothesis"]["metric"] = "operating_margin"
        self.assertIn(
            "core_hypothesis.metric must reference an item in key_variables",
            validate_research_brief(brief),
        )

    def test_hypothesis_deadline_must_fit_the_research_horizon(self):
        cases = [
            ("2026-07-21", "cannot be before as_of_date"),
            ("2026-12-31", "cannot be after the investment horizon"),
        ]
        for deadline, expected in cases:
            with self.subTest(deadline=deadline):
                brief = valid_brief()
                brief["core_hypothesis"]["falsified_when"]["deadline"] = deadline
                errors = validate_research_brief(brief)
                self.assertTrue(any(expected in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
