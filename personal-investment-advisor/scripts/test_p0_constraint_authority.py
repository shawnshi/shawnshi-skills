"""Synthetic policy/position authority tests; no financial files or providers."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import position_limits as limits
from test_investment_controls import valid_dashboard, valid_runtime_quote
from watchlist_gate import evaluate_watchlist, load_derived_limits

NOW = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)


def confirmed(**overrides):
    record = {"constraint_id": "synthetic-individual", "version": "1",
              "source_locator": "synthetic://user-confirmation/v1", "symbol": "AAPL",
              "asset_type": "stock", "market": "US", "role": "hard_max_weight",
              "denominator": "portfolio_total_market_value_base", "value": .1,
              "authority_status": "user_confirmed", "status": "effective",
              "confirmed_at": "2026-07-01", "effective_from": "2026-07-01"}
    record.update(overrides)
    return record


class ConstraintAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic-policy.json"
        self.policy = {"schema_version": "pia_risk_bounds_policy_v1",
                       "decision_scope": "observation_only", "authority_status": "user_confirmed",
                       "source_locator": "synthetic://confirmed-policy/v1",
                       "rules": {"max_single_position_weight": {"value": .3},
                                 "max_single_position_loss": {"value": .2},
                                 "upside_cost_multiple": {"value": 2}}}
        self.position = {"symbol": "AAPL", "quantity": 1, "avg_cost": 200,
                         "currency": "USD", "market": "US", "asset_type": "stock"}
        self.weights = {"evaluation_epoch": NOW.timestamp(), "base_currency": "USD",
                        "current_weights": [{"symbol": "AAPL", "quantity": 1, "currency": "USD",
                            "current_price": 200, "market_value_base": 200, "current_weight": .2},
                            {"symbol": "CASH", "market_value_base": 800}]}

    def build(self, records=None):
        if records is not None:
            self.policy["individual_weight_constraints"] = records
        self.path.write_text(json.dumps(self.policy), encoding="utf-8")
        loaded = limits.load_policy(self.path)
        return limits.build(self.weights, {"positions": [self.position]}, policy=loaded, policy_path=self.path)

    def row(self, records=None):
        return self.build(records)["positions"][0]

    def observe(self, payload):
        return evaluate_watchlist(valid_dashboard(), valid_runtime_quote(current_price=200),
                                  now=NOW, derived_limits=payload)

    def test_confirmed_stricter_individual_cap_is_computed_and_observed(self):
        payload = self.build([confirmed()])
        row = payload["positions"][0]
        self.assertEqual(row["constraint_resolution"]["status"], "complete")
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .1)
        self.assertEqual(row["boundaries"][2]["value"], 100)
        report = self.observe(payload)
        self.assertEqual(report["evaluation_status"], "complete")
        self.assertEqual(report["categories"]["weight_cap_breached"], ["AAPL"])
        self.assertIn("aapl-derived-weight-cap", report["categories"]["upside_boundary_crossed"])
        self.assertEqual(report["weight_compliance"]["effective_max_weight"], .1)

    def test_existing_confirmed_policy_needs_no_new_confirmation(self):
        self.policy["rules"]["max_single_position_weight"]["value"] = .15
        row = self.row()
        self.assertEqual(row["constraint_resolution"]["status"], "complete")
        self.assertEqual(row["boundaries"][2]["value"], 150)
        self.assertEqual(row["weight_compliance"]["status"], "breached")

    def test_bare_position_field_stays_pending_even_if_policy_matches(self):
        self.position["max_weight"] = .1
        payload = self.build([confirmed()])
        row = payload["positions"][0]
        self.assertEqual(row["constraint_resolution"]["status"], "unresolved")
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .1)
        self.assertEqual(row["constraint_resolution"]["recorded_unconfirmed"][0]["value"], .1)
        report = self.observe(payload)
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertEqual(report["categories"]["weight_cap_breached"], ["AAPL"])
        self.assertTrue(report["evaluations"])

    def test_pending_does_not_hide_known_generic_breach_even_without_quote(self):
        self.weights["current_weights"][0]["current_weight"] = .31
        payload = self.build([confirmed(status="pending")])
        row = payload["positions"][0]
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
        report = self.observe(payload)
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertEqual(report["categories"]["weight_cap_breached"], ["AAPL"])
        missing = evaluate_watchlist(valid_dashboard(), now=NOW, derived_limits=payload)
        self.assertEqual(missing["categories"]["weight_cap_breached"], ["AAPL"])
        self.assertIn("runtime_quote_missing", missing["quote_validation_errors"])

    def test_pending_is_never_an_all_clear_when_generic_within_limit(self):
        payload = self.build([confirmed(authority_status="pending")])
        report = self.observe(payload)
        self.assertEqual(report["evaluation_status"], "insufficient_data")
        self.assertEqual(report["weight_compliance"]["status"], "within_limit")
        self.assertEqual(report["weight_compliance"]["scope"], "active_constraints_only")
        self.assertIn("constraint_authority_unresolved", report["categories"]["insufficient_data"])

    def test_role_denominator_and_scope_mismatches_never_min(self):
        for fields in [{"denominator": "invested_equity"}, {"role": "target_weight"},
                       {"asset_type": "etf"}, {"market": "HK"}]:
            with self.subTest(fields=fields):
                row = self.row([confirmed(**fields)])
                self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
                self.assertEqual(row["constraint_resolution"]["status"], "unresolved")
                self.assertTrue(row["constraint_resolution"]["excluded_items"])

    def test_other_symbol_is_not_merged(self):
        row = self.row([confirmed(symbol="OTHER")])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
        self.assertEqual(row["constraint_resolution"]["status"], "complete")

    def test_revoked_and_superseded_records_do_not_apply(self):
        for status in ["revoked", "superseded"]:
            with self.subTest(status=status):
                row = self.row([confirmed(status=status, value=.01)])
                self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
                self.assertEqual(row["constraint_resolution"]["status"], "complete")
                self.assertTrue(row["constraint_resolution"]["inactive_items"])

    def test_conflicting_versions_do_not_silently_take_minimum(self):
        row = self.row([confirmed(), confirmed(version="2", value=.05)])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
        self.assertEqual(row["constraint_resolution"]["status"], "unresolved")
        self.assertEqual(len(row["constraint_resolution"]["conflicts"]), 2)

    def test_pending_or_explicit_conflict_blocks_same_identity(self):
        for status in ["pending", "conflict"]:
            with self.subTest(status=status):
                row = self.row([confirmed(), confirmed(version="2", status=status)])
                self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
                self.assertTrue(row["constraint_resolution"]["conflicts"])

    def test_independent_confirmed_caps_can_intersect(self):
        row = self.row([confirmed(), confirmed(constraint_id="independent", value=.15)])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .1)
        self.assertEqual(row["constraint_resolution"]["status"], "complete")

    def test_untraceable_or_malformed_records_are_unresolved_not_authorized(self):
        cases = [{"source_locator": ""}, {"version": ""}, {"confirmed_at": None},
                 {"effective_from": None}, {"confirmed_at": "2027-01-01"},
                 {"value": True}, {"value": "0.01"}, {"value": float("nan")},
                 {"value": float("inf")}, {"value": -.1}, {"value": 1.1}, {"value": 10 ** 1000},
                 {"pending_confirmation": True}, {"status": []}, {"status": {"effective": True}}]
        for fields in cases:
            with self.subTest(fields=fields):
                row = self.row([confirmed(**fields)])
                self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
                self.assertEqual(row["constraint_resolution"]["status"], "unresolved")

    def test_effective_dates_and_expiration(self):
        for fields in [{"effective_from": "2027-01-01"}, {"effective_until": "2026-07-29"}]:
            row = self.row([confirmed(**fields)])
            self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
            self.assertTrue(row["constraint_resolution"]["inactive_items"])
        row = self.row([confirmed(effective_until="2026-01-01")])
        self.assertTrue(row["constraint_resolution"]["conflicts"])
        row = self.row([confirmed(effective_until="2026-07-30")])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .1)

    def test_bad_clock_keeps_generic_check_but_not_individual_authority(self):
        for epoch in [None, True, float("inf"), 1e300, 10 ** 1000]:
            self.weights["evaluation_epoch"] = epoch
            row = self.row([confirmed()])
            self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
            self.assertEqual(row["constraint_resolution"]["status"], "unresolved")

    def test_malformed_container_and_scope_are_explicit_gaps(self):
        for records in [{}, [None], [{"value": .01}], [confirmed(symbol=" ")]]:
            row = self.row(records)
            self.assertEqual(row["constraint_resolution"]["status"], "unresolved")
            self.assertTrue(row["constraint_resolution"]["gaps"])

    def test_looser_policy_or_individual_never_breaks_p0_stock_cap(self):
        self.policy["rules"]["max_single_position_weight"]["value"] = .8
        row = self.row([confirmed(value=.7)])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)
        self.policy["rules"]["max_single_position_weight"]["applies_to_asset_types"] = ["etf"]
        row = self.row([confirmed(value=.7)])
        self.assertEqual(row["constraint_resolution"]["effective_max_weight"], .3)

    def test_equal_cap_is_allowed_and_frozen_mapping_is_not_dynamic_trigger(self):
        row = self.row([confirmed()])
        self.assertEqual(row["weight_compliance"]["status"], "breached")
        mapping = row["boundaries"][2]["price_mapping"]
        self.assertEqual(mapping["mode"], "snapshot_frozen_nav")
        self.assertEqual(mapping["frozen_nav"], 1000)
        self.assertEqual(mapping["base_currency"], "USD")
        self.assertEqual(mapping["evaluation_epoch"], NOW.timestamp())
        self.assertTrue(mapping["not_dynamic_weight_trigger"])
        self.assertEqual(row["boundaries"][2]["value"], 100)
        self.assertNotEqual(100, .1 * 800 / (1 - .1))
        self.weights["current_weights"][0].update(current_price=100, market_value_base=100, current_weight=.1)
        self.weights["current_weights"][1]["market_value_base"] = 900
        payload = self.build([confirmed()])
        report = evaluate_watchlist(valid_dashboard(), valid_runtime_quote(current_price=100),
                                    now=NOW, derived_limits=payload)
        self.assertEqual(report["weight_compliance"]["status"], "within_limit")
        self.assertEqual(report["categories"]["weight_cap_breached"], [])

    def test_native_file_roundtrip_preserves_pending_and_local_breach(self):
        self.position["max_weight"] = .05
        self.weights["current_weights"][0].update(current_price=310, market_value_base=310, current_weight=.31)
        self.weights["current_weights"][1]["market_value_base"] = 690
        self.build()
        folder = Path(self.tmp.name)
        inputs = {"weights.json": self.weights, "positions.json": {"positions": [self.position]},
                  "dashboard.json": valid_dashboard(), "quote.json": valid_runtime_quote(current_price=310)}
        for name, data in inputs.items():
            (folder / name).write_text(json.dumps(data), encoding="utf-8")
        scripts = Path(__file__).resolve().parent
        derived = folder / "derived.json"
        result = subprocess.run([sys.executable, "-B", str(scripts / "position_limits.py"),
            "--weights-file", str(folder / "weights.json"), "--positions-file", str(folder / "positions.json"),
            "--policy-file", str(self.path), "--out", str(derived)], capture_output=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(derived.read_text(encoding="utf-8"))["constraint_resolution_status"], "unresolved")
        gate = subprocess.run([sys.executable, "-B", str(scripts / "watchlist_gate.py"),
            str(folder / "dashboard.json"), "--quote-snapshot", str(folder / "quote.json"),
            "--derived-limits", str(derived), "--now", NOW.isoformat()],
            capture_output=True, encoding="utf-8", check=False)
        self.assertEqual(gate.returncode, 1, gate.stderr)
        report = json.loads(gate.stdout)
        self.assertEqual(report["detail_status"], "constraint_authority_unresolved")
        self.assertEqual(report["categories"]["weight_cap_breached"], ["AAPL"])
        self.assertTrue(report["derived_limits"]["evaluations"])

    def test_provenance_roundtrip_and_no_input_mutation(self):
        before_position, before_weights = copy.deepcopy(self.position), copy.deepcopy(self.weights)
        payload = self.build([confirmed()])
        path = Path(self.tmp.name) / "derived.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        loaded, errors = load_derived_limits(str(path))
        self.assertEqual(errors, [])
        self.assertEqual(loaded, payload)
        self.assertEqual(self.position, before_position)
        self.assertEqual(self.weights, before_weights)
        active = payload["positions"][0]["constraint_resolution"]["active_items"][-1]
        self.assertEqual(active["content_sha256"], limits.sha256_file(self.path))
        self.assertEqual(active["version"], "1")
        report = self.observe(payload)
        mapped = next(row for row in report["evaluations"] if row["basis"] == "position_weight_cap")
        self.assertEqual(mapped["price_mapping"]["mode"], "snapshot_frozen_nav")

    def test_numeric_policy_validation_rejects_bools_nonfinite_and_invalid_loss(self):
        for key, values in [("max_single_position_weight", [True, float("nan"), float("inf"), 1.1, 10 ** 1000]),
                            ("max_single_position_loss", [1, 1.1]),
                            ("upside_cost_multiple", [False, 0])]:
            for value in values:
                policy = copy.deepcopy(self.policy)
                policy["rules"][key]["value"] = value
                self.path.write_text(json.dumps(policy), encoding="utf-8")
                with self.assertRaises(limits.PolicyError):
                    limits.load_policy(self.path)


if __name__ == "__main__":
    unittest.main()
