"""Run-level visibility contract: what ran, what did not, and how long it is valid."""

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia_daily
from pia_daily import build_residual_unknowns
from quote_evidence_contract import (
    MAX_QUOTE_AGE_SECONDS,
    QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE,
)

EPOCH = 1_800_000_000.0


def stages(*names):
    return [{"stage": name, "status": "complete", "exit_code": 0} for name in names]


class RunInventoryTests(unittest.TestCase):
    def test_run_stages_are_listed_with_their_scope(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh", "quotes"],
            stages=stages("refresh", "quotes"),
            decision_scope="advisory",
            evaluation_epoch=EPOCH,
        )
        self.assertEqual(inventory["stages_run"], ["refresh", "quotes"])
        self.assertEqual(inventory["stage_scopes"], {"refresh": "advisory", "quotes": "advisory"})
        self.assertEqual(inventory["stages_not_run"], [])

    def test_planned_but_absent_stage_carries_a_reason(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh", "quotes", "weights"],
            stages=stages("refresh", "quotes"),
            decision_scope="research_only",
            evaluation_epoch=EPOCH,
        )
        self.assertEqual(
            inventory["stages_not_run"],
            [{"stage": "weights", "reason": "not_reached_due_to_upstream_incomplete"}],
        )

    def test_flag_skipped_stage_is_distinguished_from_unreached(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh", "watchlist"],
            stages=stages("refresh"),
            decision_scope="advisory",
            evaluation_epoch=EPOCH,
            flag_skipped={"watchlist": "--skip-watchlist"},
        )
        self.assertEqual(
            inventory["stages_not_run"],
            [{"stage": "watchlist", "reason": "skipped_by_flag:--skip-watchlist"}],
        )

    def test_validity_uses_the_conservative_shortest_window(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh"],
            stages=stages("refresh"),
            decision_scope="advisory",
            evaluation_epoch=EPOCH,
        )
        shortest = min(QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE.values())
        self.assertEqual(inventory["max_quote_age_seconds"], MAX_QUOTE_AGE_SECONDS)
        self.assertEqual(
            inventory["freshness"]["earliest_valid_until"],
            pia_daily._epoch_to_iso(EPOCH + shortest),
        )
        self.assertEqual(
            inventory["valid_until"], inventory["freshness"]["earliest_valid_until"]
        )
        self.assertEqual(
            inventory["valid_until_basis"], "conservative_shortest_quote_window"
        )
        # The loose bound is published too, but is never the default read.
        self.assertNotEqual(
            inventory["freshness"]["latest_valid_until"], inventory["valid_until"]
        )

    def test_window_table_comes_from_the_contract_not_from_literals(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh"],
            stages=stages("refresh"),
            decision_scope="advisory",
            evaluation_epoch=EPOCH,
        )
        self.assertEqual(
            inventory["freshness"]["window_seconds_by_market_state"],
            dict(QUOTE_MAX_AGE_SECONDS_BY_MARKET_STATE),
        )

    def test_inventory_reports_the_scope_it_was_given(self):
        inventory = pia_daily.build_run_inventory(
            plan=["refresh"],
            stages=stages("refresh"),
            decision_scope="research_only",
            evaluation_epoch=EPOCH,
        )
        self.assertEqual(inventory["decision_scope"], "research_only")
        self.assertEqual(inventory["stage_scopes"]["refresh"], "research_only")


class ResidualUnknownTests(unittest.TestCase):
    """A run must name what it did not establish, not just what it completed."""

    def test_clean_run_still_declares_standing_unknowns(self):
        unknowns = build_residual_unknowns([
            {"stage": "refresh", "status": "complete", "detail_status": "ok"},
        ])
        kinds = [item["kind"] for item in unknowns]
        self.assertEqual(kinds, ["account_rules_not_verified", "cost_model_not_sourced"])
        self.assertTrue(all(item["statement"] for item in unknowns))

    def test_each_unproven_probe_becomes_an_unknown(self):
        unknowns = build_residual_unknowns([{
            "stage": "coverage-probe", "status": "complete",
            "detail_status": "coverage_partially_unproven",
            "unproven_probes": ["sse_query 601899.SS: channel_broken"],
        }])
        probe = [item for item in unknowns if item["kind"] == "coverage_probe_unproven"]
        self.assertEqual(len(probe), 1)
        self.assertEqual(probe[0]["detail"], "sse_query 601899.SS: channel_broken")

    def test_incomplete_stage_and_its_error_are_both_named(self):
        unknowns = build_residual_unknowns([{
            "stage": "risk-diagnostic", "status": "insufficient_evidence",
            "detail_status": "no_usable_history", "errors": ["history_unusable"],
        }])
        kinds = sorted(item["kind"] for item in unknowns)
        self.assertEqual(kinds, ["account_rules_not_verified", "cost_model_not_sourced",
                                 "stage_error", "stage_not_complete"])
        self.assertEqual([item["detail"] for item in unknowns if item["stage"] == "risk-diagnostic"],
                         ["no_usable_history", "history_unusable"])

    def test_undefined_watchlist_thresholds_are_not_silence(self):
        unknowns = build_residual_unknowns([{
            "stage": "watchlist", "status": "complete",
            "detail_status": "thresholds_undefined", "boundaries_undefined": ["Y"],
        }])
        self.assertIn("watchlist_thresholds_undefined",
                      [item["kind"] for item in unknowns])

    def test_incomplete_run_verdict_is_itself_an_unknown(self):
        unknowns = build_residual_unknowns(
            [{"stage": "refresh", "status": "complete"}],
            run_status="incomplete", run_detail="thesis_not_assessed")
        first = unknowns[0]
        self.assertEqual(first["kind"], "run_not_complete")
        self.assertEqual(first["detail"], "thesis_not_assessed")
        # A complete run does not invent a run-level unknown.
        self.assertEqual(
            [item["kind"] for item in build_residual_unknowns([], run_status="complete")],
            ["account_rules_not_verified", "cost_model_not_sourced"])

    def test_non_dict_stages_are_skipped_without_crashing(self):
        unknowns = build_residual_unknowns(["nonsense", None])  # type: ignore[list-item]
        self.assertEqual([item["kind"] for item in unknowns],
                         ["account_rules_not_verified", "cost_model_not_sourced"])


if __name__ == "__main__":
    unittest.main()
