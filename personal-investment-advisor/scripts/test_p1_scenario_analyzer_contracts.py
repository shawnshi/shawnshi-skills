import contextlib
import copy
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

from portfolio_scenario_analyzer import analyze_scenarios, main


def sourced_weight_snapshot(market_values, fx_rates=None):
    snapshot = {
        "as_of": "2026-08-02T09:30:00+08:00",
        "source": "test quote package",
        "source_locator": "fixture:quotes:2026-08-02",
        "valuation_basis": "base_currency_market_value",
        "market_values_base_currency": market_values,
    }
    if fx_rates is not None:
        snapshot.update(
            {
                "fx_as_of": "2026-08-02T09:30:00+08:00",
                "fx_source": "test FX package",
                "fx_source_locator": "fixture:fx:2026-08-02",
                "fx_rates": fx_rates,
            }
        )
    return snapshot


def single_position_portfolio(weight=1.0):
    return {
        "base_currency": "USD",
        "positions": [
            {
                "symbol": "AAPL",
                "quantity": 1,
                "avg_cost": 100,
                "currency": "USD",
                "current_weight": weight,
            }
        ],
    }


def single_position_assumptions(asset_return=0.1):
    return {
        "scenario_contract_version": "2.0",
        "base_currency": "USD",
        "weight_snapshot": sourced_weight_snapshot({"AAPL": 1.0}),
        "scenarios": [
            {
                "name": "global_recession",
                "asset_returns": {"AAPL": asset_return},
                "assumption_source": "user-approved test assumption",
            }
        ],
    }


def two_position_portfolio():
    return {
        "base_currency": "USD",
        "positions": [
            {
                "symbol": "AAA",
                "quantity": 1,
                "avg_cost": 100,
                "currency": "USD",
                "current_weight": 0.6,
            },
            {
                "symbol": "BBB",
                "quantity": 1,
                "avg_cost": 100,
                "currency": "USD",
                "current_weight": 0.4,
            },
        ],
    }


def two_position_assumptions():
    return {
        "scenario_contract_version": "2.0",
        "base_currency": "USD",
        "weight_snapshot": sourced_weight_snapshot({"AAA": 0.6, "BBB": 0.4}),
        "scenarios": [
            {
                "name": "severe_recession_liquidity",
                "asset_returns": {"AAA": 0.1, "BBB": 0.1},
                "assumption_source": "user-approved test assumption",
            }
        ],
    }


class ScenarioAnalyzerStrictContractTests(unittest.TestCase):
    def test_rejects_coercible_types_and_non_string_identifiers(self):
        cases = []

        portfolio = single_position_portfolio()
        portfolio["positions"][0]["symbol"] = 123
        cases.append((portfolio, single_position_assumptions(), "positions[0].symbol"))

        portfolio = single_position_portfolio()
        portfolio["positions"][0]["currency"] = 840
        cases.append((portfolio, single_position_assumptions(), "positions[0].currency"))

        for field, value in [
            ("quantity", "1"),
            ("avg_cost", True),
            ("current_weight", "1.0"),
        ]:
            portfolio = single_position_portfolio()
            portfolio["positions"][0][field] = value
            cases.append((portfolio, single_position_assumptions(), f"positions[0].{field}"))

        cases.append(
            (
                single_position_portfolio(),
                single_position_assumptions("0.1"),
                "asset_returns.AAPL",
            )
        )

        assumptions = single_position_assumptions()
        assumptions["constraints"] = {"max_single_weight": "1.0"}
        cases.append(
            (single_position_portfolio(), assumptions, "constraints.max_single_weight")
        )

        assumptions = single_position_assumptions()
        assumptions["transaction_cost_bps"] = True
        assumptions["assumed_turnover"] = 1
        cases.append((single_position_portfolio(), assumptions, "transaction_cost_bps"))

        for portfolio, assumptions, expected_path in cases:
            with self.subTest(expected_path=expected_path):
                result = analyze_scenarios(portfolio, assumptions)
                self.assertFalse(result["valid"])
                self.assertEqual(result["scenario_results"], [])
                self.assertTrue(
                    any(expected_path in error for error in result["errors"]),
                    result["errors"],
                )

    def test_active_weights_must_close(self):
        for weight in (0.5, 0.99, 1.01):
            with self.subTest(weight=weight):
                result = analyze_scenarios(
                    single_position_portfolio(weight),
                    single_position_assumptions(),
                )
                self.assertFalse(result["valid"])
                self.assertEqual(result["scenario_results"], [])
                self.assertTrue(
                    any(
                        "weights must sum to 1.0" in error
                        or "current_weight must be positive and at most 1" in error
                        for error in result["errors"]
                    )
                )

    def test_v2_requires_sourced_weight_snapshot_and_reconciles_weights(self):
        missing = single_position_assumptions()
        del missing["weight_snapshot"]
        result = analyze_scenarios(single_position_portfolio(), missing)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("weight_snapshot is required" in error for error in result["errors"])
        )

        mismatched = two_position_assumptions()
        mismatched["weight_snapshot"]["market_values_base_currency"] = {
            "AAA": 0.5,
            "BBB": 0.5,
        }
        result = analyze_scenarios(two_position_portfolio(), mismatched)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("weight mismatch" in error for error in result["errors"]),
            result["errors"],
        )

        untyped = single_position_assumptions()
        untyped["weight_snapshot"]["market_values_base_currency"]["AAPL"] = "1.0"
        result = analyze_scenarios(single_position_portfolio(), untyped)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                "weight_snapshot.market_values_base_currency.AAPL" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

        foreign_portfolio = single_position_portfolio()
        foreign_portfolio["base_currency"] = "CNY"
        foreign_portfolio["positions"][0]["symbol"] = "GOOG"
        foreign_portfolio["positions"][0]["currency"] = "USD"
        foreign_assumptions = single_position_assumptions()
        foreign_assumptions["base_currency"] = "CNY"
        foreign_assumptions["scenarios"][0]["asset_returns"] = {"GOOG": 0.1}
        foreign_assumptions["weight_snapshot"]["market_values_base_currency"] = {
            "GOOG": 1.0
        }
        result = analyze_scenarios(foreign_portfolio, foreign_assumptions)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("weight_snapshot.fx_rates" in error for error in result["errors"]),
            result["errors"],
        )

    def test_scenario_return_keys_exactly_match_active_universe(self):
        missing = single_position_assumptions()
        missing["scenarios"][0]["asset_returns"] = {}
        extra = single_position_assumptions()
        extra["scenarios"][0]["asset_returns"]["MSFT"] = 0.2
        for assumptions, expected in [
            (missing, "missing explicit returns"),
            (extra, "contains non-active symbols"),
        ]:
            with self.subTest(expected=expected):
                result = analyze_scenarios(single_position_portfolio(), assumptions)
                self.assertFalse(result["valid"])
                self.assertTrue(any(expected in error for error in result["errors"]))

    def test_v2_accepts_arbitrary_unique_names_and_rejects_duplicates(self):
        valid = analyze_scenarios(
            single_position_portfolio(), single_position_assumptions()
        )
        self.assertTrue(valid["valid"], valid["errors"])
        duplicate = single_position_assumptions()
        duplicate["scenarios"].append(copy.deepcopy(duplicate["scenarios"][0]))
        duplicate["scenarios"][1]["name"] = " GLOBAL_RECESSION "
        result = analyze_scenarios(single_position_portfolio(), duplicate)
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate scenario name" in error for error in result["errors"]))

    def test_local_currency_return_requires_complete_explicit_fx(self):
        portfolio = {
            "base_currency": "CNY",
            "positions": [
                {
                    "symbol": "GOOG",
                    "quantity": 1,
                    "avg_cost": 300,
                    "currency": "USD",
                    "current_weight": 1.0,
                }
            ],
        }
        assumptions = {
            "scenario_contract_version": "2.0",
            "base_currency": "CNY",
            "weight_snapshot": sourced_weight_snapshot(
                {"GOOG": 1.0}, {"USD/CNY": 7.0}
            ),
            "scenarios": [
                {
                    "name": "global_recession",
                    "asset_returns": {
                        "GOOG": {
                            "basis": "local_total_return",
                            "return": -0.22,
                            "currency": "USD",
                            "fx_pair": "USD/CNY",
                        }
                    },
                    "fx_returns": {
                        "USD/CNY": {
                            "return": 0.05,
                            "as_of": "2026-08-02",
                            "source": "user-approved stress assumption",
                            "source_locator": "prompt:fx:USD/CNY",
                        }
                    },
                    "assumption_source": "user-approved test assumption",
                }
            ],
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertTrue(result["valid"], result["errors"])
        scenario = result["scenario_results"][0]
        self.assertAlmostEqual(scenario["portfolio_return_before_cost"], -0.181)
        decomposition = scenario["return_decomposition"]["GOOG"]
        self.assertEqual(decomposition["local_return"], -0.22)
        self.assertEqual(decomposition["fx_return"], 0.05)
        self.assertAlmostEqual(decomposition["base_currency_return"], -0.181)

        missing_fx = copy.deepcopy(assumptions)
        missing_fx["scenarios"][0]["fx_returns"] = {}
        invalid = analyze_scenarios(portfolio, missing_fx)
        self.assertFalse(invalid["valid"])
        self.assertTrue(any("missing required pairs" in error for error in invalid["errors"]))

        wrong_pair = copy.deepcopy(assumptions)
        wrong_pair["scenarios"][0]["asset_returns"]["GOOG"]["fx_pair"] = "USD/HKD"
        invalid = analyze_scenarios(portfolio, wrong_pair)
        self.assertFalse(invalid["valid"])
        self.assertTrue(any("must equal USD/CNY" in error for error in invalid["errors"]))


class ScenarioAnalyzerConstraintAndRiskTests(unittest.TestCase):
    def _region_portfolio(self, cn_weight=0.4, us_weight=0.1, cash_weight=0.5):
        return {
            "base_currency": "CNY",
            "positions": [
                {
                    "symbol": "CN_EQ",
                    "quantity": 1,
                    "avg_cost": 1,
                    "currency": "CNY",
                    "current_weight": cn_weight,
                },
                {
                    "symbol": "US_EQ",
                    "quantity": 1,
                    "avg_cost": 1,
                    "currency": "USD",
                    "current_weight": us_weight,
                },
                {
                    "symbol": "CASH_CNY",
                    "quantity": 1,
                    "avg_cost": 1,
                    "currency": "CNY",
                    "current_weight": cash_weight,
                },
            ],
        }

    def _region_assumptions(self):
        return {
            "scenario_contract_version": "2.0",
            "base_currency": "CNY",
            "weight_snapshot": sourced_weight_snapshot(
                {"CN_EQ": 0.4, "US_EQ": 0.1, "CASH_CNY": 0.5},
                {"USD/CNY": 7.0},
            ),
            "scenarios": [
                {
                    "name": "base_case",
                    "asset_returns": {"CN_EQ": 0.0, "US_EQ": 0.0, "CASH_CNY": 0.0},
                    "assumption_source": "user-approved test assumption",
                }
            ],
            "constraints": {
                "bucket_policies": [
                    {
                        "id": "equity_region_80_20",
                        "source": "user policy",
                        "source_locator": "prompt:equity-policy",
                        "scope_symbols": ["CN_EQ", "US_EQ"],
                        "excluded_symbols": {"CASH_CNY": "cash excluded by policy"},
                        "tolerance": 0.000001,
                        "buckets": [
                            {"id": "CN", "symbols": ["CN_EQ"], "target_weight": 0.8},
                            {"id": "US", "symbols": ["US_EQ"], "target_weight": 0.2},
                        ],
                    }
                ]
            },
        }

    def test_equity_80_20_policy_excludes_cash_and_reports_both_deviations(self):
        assumptions = self._region_assumptions()
        exact = analyze_scenarios(self._region_portfolio(), assumptions)
        self.assertTrue(exact["valid"], exact["errors"])
        self.assertEqual(exact["constraint_violations"], [])
        policy = exact["bucket_policy_results"][0]
        self.assertEqual(policy["scope_weight"], 0.5)
        self.assertEqual(policy["buckets"][0]["weight_within_scope"], 0.8)
        self.assertEqual(policy["buckets"][1]["weight_within_scope"], 0.2)

        violated_assumptions = self._region_assumptions()
        violated_assumptions["weight_snapshot"]["market_values_base_currency"] = {
            "CN_EQ": 0.435,
            "US_EQ": 0.065,
            "CASH_CNY": 0.5,
        }
        violated = analyze_scenarios(
            self._region_portfolio(cn_weight=0.435, us_weight=0.065),
            violated_assumptions,
        )
        self.assertTrue(violated["valid"], violated["errors"])
        violations = violated["constraint_violations"]
        self.assertEqual(len(violations), 2)
        self.assertEqual({item["bucket_id"] for item in violations}, {"CN", "US"})

        uncovered = self._region_assumptions()
        uncovered["constraints"]["bucket_policies"][0]["excluded_symbols"] = {}
        invalid = analyze_scenarios(self._region_portfolio(), uncovered)
        self.assertFalse(invalid["valid"])
        self.assertTrue(
            any("leaves active symbols unclassified" in error for error in invalid["errors"])
        )

    def test_asset_level_costs_are_weighted_and_reconciled(self):
        assumptions = two_position_assumptions()
        assumptions["scenarios"][0]["cost_model"] = {
            "source": "user-approved cost assumptions",
            "source_locator": "prompt:costs",
            "as_of": "2026-08-02",
            "by_symbol": {
                "AAA": {"transaction_cost_bps": 10, "assumed_turnover": 0.5},
                "BBB": {"transaction_cost_bps": 50, "assumed_turnover": 1.0},
            },
        }
        result = analyze_scenarios(two_position_portfolio(), assumptions)
        self.assertTrue(result["valid"], result["errors"])
        scenario = result["scenario_results"][0]
        self.assertAlmostEqual(scenario["transaction_cost_contributions"]["AAA"], 0.0003)
        self.assertAlmostEqual(scenario["transaction_cost_contributions"]["BBB"], 0.002)
        self.assertAlmostEqual(scenario["transaction_cost_total"], 0.0023)
        self.assertAlmostEqual(scenario["portfolio_return_before_cost"], 0.1)
        self.assertAlmostEqual(scenario["portfolio_return_after_cost"], 0.0977)
        self.assertIsNone(result["transaction_cost_estimate"])
        self.assertEqual(result["transaction_cost_summary"]["status"], "ok")
        self.assertEqual(
            result["transaction_cost_summary"]["detail_status"],
            "explicit_scenario_costs_calculated",
        )
        self.assertAlmostEqual(
            result["transaction_cost_summary"]["by_scenario"]
            ["severe_recession_liquidity"],
            0.0023,
        )

        incomplete = copy.deepcopy(assumptions)
        del incomplete["scenarios"][0]["cost_model"]["by_symbol"]["BBB"]
        invalid = analyze_scenarios(two_position_portfolio(), incomplete)
        self.assertFalse(invalid["valid"])
        self.assertTrue(any("missing active symbols" in error for error in invalid["errors"]))

    def test_optional_correlation_risk_contribution_contract(self):
        assumptions = two_position_assumptions()
        without_risk = analyze_scenarios(two_position_portfolio(), assumptions)
        self.assertTrue(without_risk["valid"], without_risk["errors"])
        self.assertEqual(without_risk["risk_diagnostics"]["status"], "not_calculated")

        assumptions["risk_model"] = {
            "type": "explicit_volatility_correlation",
            "units": "decimal_annualized",
            "as_of": "2026-08-02",
            "observation_window": "252 trading days",
            "frequency": "daily",
            "source": "user-approved risk packet",
            "source_locator": "risk-packet:2026-08-02",
            "scope_symbols": ["AAA", "BBB"],
            "zero_volatility_symbols": [],
            "volatilities": {"AAA": 0.2, "BBB": 0.3},
            "correlations": {
                "AAA": {"AAA": 1.0, "BBB": 0.5},
                "BBB": {"AAA": 0.5, "BBB": 1.0},
            },
        }
        result = analyze_scenarios(two_position_portfolio(), assumptions)
        self.assertTrue(result["valid"], result["errors"])
        risk = result["risk_diagnostics"]
        self.assertEqual(risk["status"], "calculated")
        self.assertAlmostEqual(risk["portfolio_volatility"], math.sqrt(0.0432), places=9)
        risk_share = sum(
            item["share_of_portfolio_variance"]
            for item in risk["risk_contributions"].values()
        )
        self.assertAlmostEqual(risk_share, 1.0, places=9)
        self.assertIn("not risk parity", risk["model_boundary"])

        asymmetric = copy.deepcopy(assumptions)
        asymmetric["risk_model"]["correlations"]["BBB"]["AAA"] = 0.4
        invalid = analyze_scenarios(two_position_portfolio(), asymmetric)
        self.assertFalse(invalid["valid"])
        self.assertTrue(any("must be symmetric" in error for error in invalid["errors"]))

    def test_non_positive_semidefinite_risk_matrix_fails(self):
        portfolio = {
            "base_currency": "USD",
            "positions": [
                {
                    "symbol": symbol,
                    "quantity": 1,
                    "avg_cost": 1,
                    "currency": "USD",
                    "current_weight": weight,
                }
                for symbol, weight in [("AAA", 0.34), ("BBB", 0.33), ("CCC", 0.33)]
            ],
        }
        assumptions = {
            "scenario_contract_version": "2.0",
            "base_currency": "USD",
            "weight_snapshot": sourced_weight_snapshot(
                {"AAA": 0.34, "BBB": 0.33, "CCC": 0.33}
            ),
            "scenarios": [
                {
                    "name": "stress",
                    "asset_returns": {"AAA": 0, "BBB": 0, "CCC": 0},
                    "assumption_source": "test",
                }
            ],
            "risk_model": {
                "type": "explicit_volatility_correlation",
                "units": "decimal_annualized",
                "as_of": "2026-08-02",
                "observation_window": "252 trading days",
                "frequency": "daily",
                "source": "test",
                "source_locator": "test:non-psd",
                "scope_symbols": ["AAA", "BBB", "CCC"],
                "zero_volatility_symbols": [],
                "volatilities": {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2},
                "correlations": {
                    "AAA": {"AAA": 1, "BBB": 0.9, "CCC": 0.9},
                    "BBB": {"AAA": 0.9, "BBB": 1, "CCC": -0.9},
                    "CCC": {"AAA": 0.9, "BBB": -0.9, "CCC": 1},
                },
            },
        }
        result = analyze_scenarios(portfolio, assumptions)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("positive semidefinite" in error for error in result["errors"]),
            result["errors"],
        )


class ScenarioAnalyzerCliTests(unittest.TestCase):
    def _invoke(self, argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def test_cli_errors_are_always_structured_json(self):
        exit_code, payload = self._invoke([])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["detail_status"], "cli_usage_error")

        exit_code, payload = self._invoke(["missing.json", "also-missing.json"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "data_error")
        self.assertEqual(payload["detail_status"], "input_read_failed")

        temporary_root = None
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            root = Path(tmpdir)
            portfolio_path = root / "portfolio.json"
            assumptions_path = root / "assumptions.json"
            portfolio_path.write_text(
                json.dumps(single_position_portfolio()), encoding="utf-8"
            )

            assumptions_path.write_text("{not-json", encoding="utf-8")
            exit_code, payload = self._invoke(
                [str(portfolio_path), str(assumptions_path)]
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["detail_status"], "invalid_json")

            assumptions_path.write_text(
                '{"scenario_contract_version":"2.0","base_currency":"USD",'
                '"scenarios":[{"name":"stress","assumption_source":"test",'
                '"asset_returns":{"AAPL":0.1,"AAPL":0.2}}]}',
                encoding="utf-8",
            )
            exit_code, payload = self._invoke(
                [str(portfolio_path), str(assumptions_path)]
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["detail_status"], "invalid_json")
            self.assertTrue(any("duplicate JSON key" in error for error in payload["errors"]))

            portfolio_path.write_text("[]", encoding="utf-8")
            assumptions_path.write_text(
                json.dumps(single_position_assumptions()), encoding="utf-8"
            )
            exit_code, payload = self._invoke(
                [str(portfolio_path), str(assumptions_path)]
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["detail_status"], "portfolio_root_invalid")

            portfolio_path.write_text(
                json.dumps(single_position_portfolio()), encoding="utf-8"
            )
            exit_code, payload = self._invoke(
                [str(portfolio_path), str(assumptions_path), "--output", str(root)]
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["detail_status"], "output_write_failed")


if __name__ == "__main__":
    unittest.main()
