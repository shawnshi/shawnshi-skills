"""Contract tests for the non-cash denominator (cash design A).

The user-confirmed 80/20 rule measures its denominator on non-cash market value,
while the policy schema used to require every active symbol in exactly one bucket
and exactly one cash position per cash bucket.  With two cash lines (or with
core+satellite already summing to 1.0) the two contracts could not both hold, so
the experiment was unreachable.  The opt-in ``denominator`` form closes that gap
without inventing a cash target or a fake zero variance for cash.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rebalance_optimizer  # noqa: E402

POSITIONS = [
    {"symbol": "AAA", "quantity": 10, "avg_cost": 1.0, "currency": "CNY",
     "market": "CN", "asset_type": "stock"},
    {"symbol": "BBB", "quantity": 10, "avg_cost": 1.0, "currency": "CNY",
     "market": "CN", "asset_type": "stock"},
    {"symbol": "CASH_CNY", "quantity": 100, "avg_cost": 1.0, "currency": "CNY",
     "market": "CASH", "asset_type": "cash"},
    {"symbol": "CASH_USD", "quantity": 10, "avg_cost": 1.0, "currency": "USD",
     "market": "CASH", "asset_type": "cash"},
]


def observation(volatility: float) -> dict:
    return {"annualized_volatility": volatility, "observation_count": 233,
            "window_start": "2025-09-26", "window_end": "2026-09-24",
            "as_of": "2026-09-26", "source": "fixture",
            "source_locator": "dataset://pia/tasks/x/raw/vol.json"}


def policy(**overrides) -> dict:
    payload = {
        "schema_version": "pia_inverse_volatility_policy_v1",
        "experiment": "inverse_volatility_allocation",
        "decision_scope": "research_only",
        "as_of": "2026-09-27",
        "bucket_targets": {"core": 0.8, "satellite": 0.2},
        "bucket_members": {"core": ["AAA"], "satellite": ["BBB"]},
        "volatility_observations": {"AAA": observation(0.25), "BBB": observation(0.5)},
        "denominator": "active_non_cash_market_value",
        "excluded_policy_symbols": {
            "CASH_CNY": "excluded from the policy denominator by the user-confirmed 80/20 rule",
            "CASH_USD": "excluded from the policy denominator by the user-confirmed 80/20 rule",
        },
    }
    payload.update(overrides)
    return payload


class NonCashDenominatorTests(unittest.TestCase):
    def test_declared_scope_computes_weights_for_non_cash_only(self):
        report = rebalance_optimizer.run_inverse_volatility_experiment(
            POSITIONS, policy(), today=__import__("datetime").date(2026, 9, 27))
        self.assertEqual(report["status"], "complete", report)
        weights = {row["symbol"]: row["experimental_weight"]
                   for row in report["experimental_weights"]}
        self.assertEqual(sorted(weights), ["AAA", "BBB"])
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=9)
        # each bucket normalises within itself: core has only AAA, satellite only BBB
        self.assertAlmostEqual(weights["AAA"], 0.8, places=9)
        self.assertAlmostEqual(weights["BBB"], 0.2, places=9)
        self.assertEqual([row["calculation"] for row in report["bucket_results"]],
                         ["inverse_annualized_volatility", "inverse_annualized_volatility"])
        self.assertEqual(report["denominator"], "active_non_cash_market_value")
        self.assertEqual(sorted(report["excluded_policy_symbols"]), ["CASH_CNY", "CASH_USD"])
        self.assertEqual(report["scope_symbols"], ["AAA", "BBB"])

    def test_excluding_a_non_cash_symbol_is_refused(self):
        broken = policy()
        broken["excluded_policy_symbols"].pop("CASH_USD")
        broken["excluded_policy_symbols"]["BBB"] = "not allowed"
        errors = rebalance_optimizer._validate_policy(broken, POSITIONS)
        self.assertTrue(any("may only exclude cash positions" in error for error in errors), errors)

    def test_every_cash_position_must_be_listed(self):
        broken = policy()
        broken["excluded_policy_symbols"].pop("CASH_USD")
        errors = rebalance_optimizer._validate_policy(broken, POSITIONS)
        self.assertTrue(any("must list every active cash position" in error for error in errors), errors)

    def test_reason_is_required(self):
        broken = policy()
        broken["excluded_policy_symbols"]["CASH_USD"] = "   "
        errors = rebalance_optimizer._validate_policy(broken, POSITIONS)
        self.assertTrue(any("must state a non-empty reason" in error for error in errors), errors)

    def test_unknown_denominator_is_refused(self):
        errors = rebalance_optimizer._validate_policy(policy(denominator="whatever"), POSITIONS)
        self.assertTrue(any("policy.denominator must equal" in error for error in errors), errors)

    def test_membership_is_checked_against_the_declared_scope(self):
        broken = policy(bucket_members={"core": ["AAA"]})
        errors = rebalance_optimizer._validate_policy(broken, POSITIONS)
        self.assertTrue(any("missing active symbols: BBB" in error for error in errors), errors)

    def test_legacy_policy_without_a_denominator_is_unchanged(self):
        legacy = {
            "schema_version": "pia_inverse_volatility_policy_v1",
            "experiment": "inverse_volatility_allocation",
            "decision_scope": "research_only",
            "as_of": "2026-09-27",
            "bucket_targets": {"risk": 0.7, "cash": 0.3},
            "bucket_members": {"risk": ["AAA"], "cash": ["CASH_CNY"]},
            "volatility_observations": {"AAA": observation(0.2), "BBB": observation(0.4)},
        }
        errors = rebalance_optimizer._validate_policy(legacy, POSITIONS)
        # BBB is active but not required by membership, and CASH_USD is unlisted: the
        # legacy contract used every active symbol, so this partial legacy policy fails.
        self.assertTrue(any("missing active symbols" in error for error in errors), errors)
        full_legacy = dict(legacy)
        full_legacy["bucket_targets"] = {"risk": 0.5, "cash_cny": 0.3, "cash_usd": 0.2}
        full_legacy["bucket_members"] = {"risk": ["AAA", "BBB"], "cash_cny": ["CASH_CNY"],
                                        "cash_usd": ["CASH_USD"]}
        self.assertEqual(rebalance_optimizer._validate_policy(full_legacy, POSITIONS), [])

    def test_declared_scope_without_exclusions_is_refused(self):
        broken = policy()
        broken.pop("excluded_policy_symbols")
        errors = rebalance_optimizer._validate_policy(broken, POSITIONS)
        self.assertTrue(any("excluded_policy_symbols must list" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
