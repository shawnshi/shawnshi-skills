import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dashboard_gate import _validate_scenario_analysis
from dashboard_math_gate import validate_math_consistency


def valuation_case(per_share_value: float):
    shares = 100.0
    equity = per_share_value * shares
    net_debt = 20.0
    return {
        "assumptions": [
            {
                "name": "normalized_ebitda",
                "value": 10.0,
                "unit": "USD million",
                "source_locator": "https://www.sec.gov/Archives/edgar/data/1/filing.htm",
                "as_of_date": date.today().isoformat(),
            }
        ],
        "enterprise_value": equity + net_debt,
        "net_debt": net_debt,
        "equity_value": equity,
        "diluted_shares": shares,
        "per_share_value": per_share_value,
        "falsification_conditions": ["Normalized EBITDA falls below 8"],
    }


def valid_valuation():
    return {
        "valuation_contract_version": "2.0",
        "valuation_method": "enterprise_value_bridge",
        "as_of_date": date.today().isoformat(),
        "currency": "USD",
        "base": valuation_case(10.0),
        "bull": valuation_case(12.0),
        "bear": valuation_case(8.0),
        "sensitivity": [
            {
                "parameter": "normalized_ebitda",
                "low": 8.0,
                "base": 10.0,
                "high": 12.0,
                "unit": "USD million",
                "source_locator": "https://www.sec.gov/Archives/edgar/data/1/filing.htm",
                "as_of_date": date.today().isoformat(),
            }
        ],
    }


class ValuationContractTests(unittest.TestCase):
    def test_strict_contract_rejects_legacy_free_text_scenarios(self):
        legacy = {
            "valuation_method": "narrative",
            "base": {"assumptions": ["x"], "result": "x", "falsification_conditions": ["x"]},
            "bull": {"assumptions": ["x"], "result": "x", "falsification_conditions": ["x"]},
            "bear": {"assumptions": ["x"], "result": "x", "falsification_conditions": ["x"]},
            "sensitivity": ["x"],
        }
        errors = _validate_scenario_analysis(
            {"scenario_analysis": legacy}, required=True
        )
        self.assertTrue(any("valuation_contract_version" in error for error in errors))

    def test_math_gate_recomputes_bridge_and_per_share_value(self):
        valuation = valid_valuation()
        self.assertEqual(
            validate_math_consistency({"scenario_analysis": valuation}), []
        )
        valuation["base"]["equity_value"] += 5
        errors = validate_math_consistency({"scenario_analysis": valuation})
        self.assertTrue(any("enterprise_value - net_debt" in error for error in errors))
        self.assertTrue(any("equity_value / diluted_shares" in error for error in errors))

    def test_math_gate_rejects_non_monotonic_cases(self):
        valuation = valid_valuation()
        valuation["bull"] = valuation_case(7.0)
        errors = validate_math_consistency({"scenario_analysis": valuation})
        self.assertIn(
            "scenario per_share_value must be monotonic: bull >= base >= bear",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
