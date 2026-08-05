import sys
import unittest
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quality_screener import evaluate_metrics, extract_yf_metrics, load_profiles


class QualityMethodologyTests(unittest.TestCase):
    def test_configured_screen_requires_minimum_observation_count(self):
        profile = load_profiles()["profiles"]["quality_equity"]
        metrics = {metric: 1.0 for metric in profile["thresholds"]}
        observations = {metric: 1 for metric in profile["thresholds"]}
        result = evaluate_metrics(metrics, profile, observations)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(
            set(result["insufficient_period_metrics"]), set(profile["thresholds"])
        )

    def test_fcf_uses_positive_period_ratio_not_absolute_company_size(self):
        columns = pd.to_datetime(
            ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
        )
        income = pd.DataFrame(
            {
                columns[0]: [10, 12, 100, 40, 4, 10],
                columns[1]: [9, 11, 90, 36, 4, 10],
                columns[2]: [8, 10, 80, 32, 4, 10],
                columns[3]: [7, 9, 70, 28, 4, 10],
            },
            index=[
                "Net Income",
                "EBIT",
                "Total Revenue",
                "Gross Profit",
                "Interest Expense",
                "Basic Average Shares",
            ],
        )
        cashflow = pd.DataFrame(
            {
                columns[0]: [12, 5],
                columns[1]: [11, -1],
                columns[2]: [10, 4],
                columns[3]: [9, 3],
            },
            index=["Operating Cash Flow", "Free Cash Flow"],
        )
        balance = pd.DataFrame(
            {column: [50] for column in columns}, index=["Stockholders Equity"]
        )
        metrics, observations = extract_yf_metrics(
            income, cashflow, balance, include_observations=True
        )
        self.assertEqual(metrics["fcf_positive_ratio"], 0.75)
        self.assertEqual(observations["fcf_positive_ratio"], 4)
        self.assertAlmostEqual(metrics["roe_avg"], (8 / 50 + 9 / 50 + 10 / 50) / 3)

    def test_financial_institution_profile_routes_to_industry_evidence(self):
        profile = load_profiles()["profiles"]["financial_institution"]
        self.assertEqual(profile["screening_mode"], "evidence_only")
        self.assertIn("regulatory_capital_or_solvency", profile["required_evidence_checks"])
        self.assertEqual(profile["thresholds"], {})


if __name__ == "__main__":
    unittest.main()
