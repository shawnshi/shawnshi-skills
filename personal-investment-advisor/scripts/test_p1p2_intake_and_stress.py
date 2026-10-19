"""Intake and derivation contract tests."""

import json
import math
import tempfile
import unittest
from pathlib import Path

import pia_evidence_intake as intake
import pia_goal_policy as policy

NOW = "2026-10-19T12:00:00+08:00"


def closes(seed: float, count: int = 80, wobble: float = 0.01) -> list:
    return [seed * (1 + wobble * math.sin(index / 3) + 0.002 * (index % 5)) for index in range(count)]


class EvidenceIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=__import__("os").environ.get("PIA_TEST_TMP") or None)
        self.root = Path(self.tmp.name)
        (self.root / "notice.txt").write_text("dividend announcement", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, **overrides):
        entry = {"evidence_id": "EV1", "local_path": "notice.txt", "source_tier": "issuer",
                 "source_locator": "https://example.invalid/notice.pdf",
                 "published_at": "2026-10-18T00:00:00+08:00", "claim": "fund announced a distribution"}
        entry.update(overrides)
        return {"evidence": [entry]}

    def test_valid_document_is_hashed_and_marked_operator_supplied(self):
        bundle = intake.build_evidence(self.manifest(), self.root, retrieved_at=NOW)
        item = bundle["evidence_items"][0]
        self.assertEqual(len(item["content_sha256"]), 64)
        self.assertEqual(item["local_path"], "notice.txt")
        self.assertEqual(bundle["rejected"], [])

    def test_unsourced_or_unsupported_entries_are_rejected(self):
        cases = {
            "tier": self.manifest(source_tier="blog"),
            "locator": self.manifest(source_locator="local-file.pdf"),
            "escape": self.manifest(local_path="../outside.txt"),
            "missing": self.manifest(local_path="absent.txt"),
            "timezone": self.manifest(published_at="2026-10-18T00:00:00"),
            "claim": self.manifest(claim=""),
        }
        for label, manifest in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(intake.IntakeError):
                    intake.build_evidence(manifest, self.root, retrieved_at=NOW)

    def test_partial_manifest_keeps_the_valid_item(self):
        manifest = {"evidence": [
            {"evidence_id": "BAD", "local_path": "absent.txt", "source_tier": "issuer",
             "source_locator": "https://example.invalid/x", "published_at": NOW, "claim": "x"},
            {"evidence_id": "OK", "local_path": "notice.txt", "source_tier": "issuer",
             "source_locator": "https://example.invalid/y", "published_at": NOW, "claim": "y"},
        ]}
        bundle = intake.build_evidence(manifest, self.root, retrieved_at=NOW)
        self.assertEqual([item["evidence_id"] for item in bundle["evidence_items"]], ["OK"])
        self.assertEqual(len(bundle["rejected"]), 1)

    def test_duplicate_ids_are_rejected(self):
        manifest = {"evidence": [self.manifest()["evidence"][0], self.manifest()["evidence"][0]]}
        bundle = intake.build_evidence(manifest, self.root, retrieved_at=NOW)
        self.assertEqual(len(bundle["evidence_items"]), 1)
        self.assertEqual(bundle["rejected"][0]["reason"], "duplicate evidence_id")


RISK_POLICY = {
    "confirmed_at": "2026-09-28", "source_locator": "dataset://test",
    "rules": {"max_single_position_weight": {"value": 0.3},
              "max_single_position_loss": {"value": 0.15},
              "upside_cost_multiple": {"value": 1.5}},
    "proximity": {"value": 0.02},
}
POSITIONS = {"positions": [{"symbol": "AAA", "asset_type": "stock", "quantity": 1,
                            "currency": "CNY", "allocation_bucket": "core",
                            "days_to_liquidate": 3}]}


class RebalanceCostTests(unittest.TestCase):
    def goals(self):
        return policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})

    def test_missing_cost_leaves_the_benefit_threshold_underived(self):
        derived = policy.derive_alpha_policy(self.goals(), {"hit_rate": 0.39}, 0.3)
        rebalance = derived["rebalance_policy"]
        self.assertIsNone(rebalance["minimum_net_expected_benefit"])
        self.assertTrue(any("cost" in gap for gap in derived["gaps"]))

    def test_cost_is_added_to_the_band_instead_of_being_assumed_zero(self):
        derived = policy.derive_alpha_policy(self.goals(), {"hit_rate": 0.39}, 0.3,
                                             round_trip_cost_bps=30)
        rebalance = derived["rebalance_policy"]
        self.assertAlmostEqual(rebalance["minimum_net_expected_benefit"], 0.04 + 0.003, places=9)
        self.assertEqual(rebalance["basis"]["round_trip_cost_bps"], 30)


class CorrelatedStressTests(unittest.TestCase):
    def goals(self):
        return policy.load_goals(POSITIONS, RISK_POLICY, {"core_target_cap": 0.7})

    def portfolio(self):
        return {"weights": {"AAA": 0.6, "BBB": 0.4},
                "positions": [{"symbol": "AAA", "asset_type": "stock", "currency": "CNY"},
                              {"symbol": "BBB", "asset_type": "stock", "currency": "CNY"}],
                "base_currency": "CNY"}

    def test_correlated_loss_exceeds_the_diversified_estimate(self):
        data = {"AAA": {"closes": closes(10.0)}, "BBB": {"closes": closes(20.0, 90, 0.02)}}
        stress = policy.derive_stress_scenarios(self.goals(), self.portfolio(), data)
        aggregate = stress["portfolio"]
        self.assertLess(aggregate["severe_correlated_loss"], aggregate["severe_diversified_loss"])
        self.assertLess(aggregate["severe_correlated_loss"], 0)

    def test_aggregate_is_reported_even_when_one_symbol_is_missing(self):
        data = {"AAA": {"closes": closes(10.0)}}
        stress = policy.derive_stress_scenarios(self.goals(), self.portfolio(), data)
        self.assertTrue(any("BBB" in gap for gap in stress["gaps"]))
        self.assertIn("severe_correlated_loss", stress["portfolio"])


if __name__ == "__main__":
    unittest.main()
