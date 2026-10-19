"""Derivation tests: every emitted number must trace to a goal or a formula."""

import copy
import math
import unittest

import pia_goal_policy as policy

RISK_POLICY = {
    "schema_version": "pia_risk_bounds_policy_v1",
    "confirmed_at": "2026-09-28",
    "source_locator": "dataset://test/policy",
    "rules": {
        "max_single_position_weight": {"value": 0.3, "denominator": "portfolio_total_market_value_base"},
        "max_single_position_loss": {"value": 0.15},
        "upside_cost_multiple": {"value": 1.5},
    },
    "proximity": {"value": 0.02},
}

POSITIONS = {
    "base_currency": "CNY",
    "positions": [
        {"symbol": "AAA", "asset_type": "stock", "quantity": 10, "currency": "CNY",
         "allocation_bucket": "core", "days_to_liquidate": 2},
        {"symbol": "BBB", "asset_type": "stock", "quantity": 5, "currency": "CNY",
         "allocation_bucket": "satellite", "days_to_liquidate": 30},
        {"symbol": "CASH_CNY", "asset_type": "cash", "quantity": 1000, "currency": "CNY",
         "allocation_bucket": "core"},
    ],
}

WEIGHTS = {"AAA": 0.6, "BBB": 0.4}


def closes(seed: float, count: int = 60) -> list:
    return [seed * (1 + 0.01 * math.sin(index / 3)) for index in range(count)]


def series() -> dict:
    return {"AAA": {"closes": closes(10.0)}, "BBB": {"closes": closes(20.0, 80)}}


class GoalExtractionTests(unittest.TestCase):
    def test_policy_values_come_from_the_confirmed_file(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        self.assertEqual(goals["max_single_position_loss"], 0.15)
        self.assertEqual(goals["upside_cost_multiple"], 1.5)
        self.assertEqual(goals["proximity"], 0.02)
        self.assertEqual(goals["core_target_cap"], 0.7)

    def test_review_cadence_is_grounded_in_liquidation_days(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        self.assertEqual(goals["review_horizon_months"], 2)
        self.assertIn("liquidation", goals["authority"]["review_horizon_source"])

    def test_bad_goal_numbers_are_refused(self):
        for goals in ({"core_target_cap": 0}, {"core_target_cap": 1.2}, {}):
            with self.assertRaises(policy.DerivationError):
                policy.load_goals(POSITIONS, RISK_POLICY, goals)

    def test_missing_risk_policy_rule_is_refused(self):
        broken = copy.deepcopy(RISK_POLICY)
        del broken["rules"]["max_single_position_loss"]
        with self.assertRaises(policy.DerivationError):
            policy.load_goals(POSITIONS, broken, {"core_target_cap": 0.7})


class BucketTests(unittest.TestCase):
    def test_satellite_is_the_remainder_and_cash_is_excluded(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        buckets = policy.derive_bucket_targets(goals, POSITIONS)
        self.assertEqual(buckets["bucket_targets"], {"core": 0.7, "satellite": 0.3})
        self.assertEqual(buckets["bucket_members"], {"core": ["AAA"], "satellite": ["BBB"]})
        self.assertEqual(buckets["excluded_policy_symbols"], ["CASH_CNY"])
        self.assertAlmostEqual(sum(buckets["bucket_targets"].values()), 1.0)

    def test_unassigned_position_blocks_the_policy(self):
        broken = copy.deepcopy(POSITIONS)
        broken["positions"][1]["allocation_bucket"] = None
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        with self.assertRaises(policy.DerivationError):
            policy.derive_bucket_targets(goals, broken)


class AlphaPolicyTests(unittest.TestCase):
    def test_breakeven_and_sample_size_trace_to_goals_and_record(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        derived = policy.derive_alpha_policy(goals, {"hit_rate": 0.3881}, annual_vol=0.25)
        promotion = derived["promotion_policy"]
        self.assertAlmostEqual(promotion["basis"]["breakeven_hit_rate"], 0.15 / 0.65, places=6)
        self.assertEqual(promotion["max_drawdown_fraction"], 0.15)
        self.assertEqual(promotion["max_annual_turnover"], 6.0)
        self.assertEqual(promotion["min_net_information_ratio"], 0.16)
        self.assertGreater(promotion["min_oos_observations"], 0)
        self.assertTrue(promotion["min_oos_observations"] % goals["review_horizon_months"] == 0)

    def test_hit_rate_below_breakeven_yields_a_gap_not_a_number(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        derived = policy.derive_alpha_policy(goals, {"hit_rate": 0.2}, annual_vol=0.25)
        self.assertIsNone(derived["promotion_policy"]["min_oos_observations"])
        self.assertTrue(any("break-even" in gap for gap in derived["gaps"]))

    def test_missing_volatility_and_record_are_reported_as_gaps(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        derived = policy.derive_alpha_policy(goals, None, annual_vol=None)
        self.assertIsNone(derived["promotion_policy"]["min_net_information_ratio"])
        self.assertEqual(len(derived["gaps"]), 3)  # volatility, record, cost snapshot
        self.assertEqual(derived["authority_status"], policy.DERIVED)


class StressTests(unittest.TestCase):
    def test_scenarios_are_negative_and_ordered(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        portfolio = {"weights": WEIGHTS, "positions": POSITIONS["positions"],
                     "base_currency": "CNY"}
        stress = policy.derive_stress_scenarios(goals, portfolio, series())
        rows = {row["name"]: row for row in stress["assumptions"]["scenarios"]}
        for symbol in WEIGHTS:
            self.assertLess(rows["mild"]["asset_returns"][symbol], 0)
            self.assertLess(rows["severe"]["asset_returns"][symbol],
                            rows["mild"]["asset_returns"][symbol])
        self.assertEqual(stress["gaps"], [])
        self.assertIn("not a forecast", rows["mild"]["assumption_source"])

    def test_short_history_and_missing_fx_are_named(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        positions = copy.deepcopy(POSITIONS["positions"])
        positions[0]["currency"] = "USD"
        portfolio = {"weights": WEIGHTS, "positions": positions, "base_currency": "CNY"}
        partial = {"AAA": {"closes": closes(10.0)[:5]}, "BBB": {"closes": closes(20.0, 80)}}
        stress = policy.derive_stress_scenarios(goals, portfolio, partial)
        self.assertTrue(any("AAA" in gap for gap in stress["gaps"]))
        self.assertEqual(sorted(stress["assumptions"]["scenarios"][0]["asset_returns"]), ["BBB"])

    def test_fx_shock_is_applied_when_history_exists(self):
        goals = policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})
        positions = copy.deepcopy(POSITIONS["positions"])
        positions[0]["currency"] = "USD"
        portfolio = {"weights": {"AAA": 1.0}, "positions": positions, "base_currency": "CNY"}
        data = {"AAA": {"closes": closes(10.0), "fx_pair": "USD/CNY"}}
        stress = policy.derive_stress_scenarios(
            goals, portfolio, data, {"USD/CNY": {"closes": closes(7.0, 70)}})
        self.assertEqual(stress["gaps"], [])
        self.assertLess(stress["assumptions"]["scenarios"][1]["asset_returns"]["AAA"], -0.05)


class DeriveAllTests(unittest.TestCase):
    def test_bundle_is_authority_tagged_and_orderless(self):
        result = policy.derive_all(POSITIONS, RISK_POLICY, WEIGHTS,
                                   {"hit_rate": 0.3881}, series(),
                                   goals={"core_target_cap": 0.7})
        self.assertEqual(result["authority_status"], policy.DERIVED)
        self.assertIn("never place", result["not_an_order"])
        self.assertAlmostEqual(sum(result["bucket_policy"]["bucket_targets"].values()), 1.0)
        self.assertTrue(result["alpha_policy"]["promotion_policy"]["min_net_information_ratio"] > 0)


if __name__ == "__main__":
    unittest.main()
