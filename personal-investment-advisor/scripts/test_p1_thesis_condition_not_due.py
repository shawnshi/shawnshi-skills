"""Gate-level tests for the ``condition_not_due`` conclusion (P1-2).

Before this state existed, "the condition exists but has not come due yet" could
only be expressed as ``insufficient_evidence``, which conflated "not evaluated"
with "not yet due". The new state must stay machine-checkable: it has to name the
conditions and a *future* due date, and it must never be read as "nothing breached".
"""
from __future__ import annotations

import copy
import datetime
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from thesis_evidence_gate import evaluate_thesis_evidence  # noqa: E402

NOW = datetime.datetime(2026, 9, 27, 12, 0, tzinfo=datetime.timezone.utc)
BINDING = {"schema_version": "pia_portfolio_snapshot_v1", "sha256": "a" * 64,
           "active_positions": [{"symbol": "AAPL", "quantity": "1", "currency": "USD",
                                 "market": "US", "asset_type": "stock"},
                                {"symbol": "159516.SZ", "quantity": "1", "currency": "CNY",
                                 "market": "CN", "asset_type": "etf"}]}
SYMBOLS = ["AAPL", "159516.SZ"]


def stamp(offset_seconds: int) -> str:
    return (NOW + datetime.timedelta(seconds=offset_seconds)).isoformat()


def build_pack(assessments: list[dict]) -> dict:
    evidence = []
    for index, evidence_id in enumerate(("macro", "sector", "regulatory", "aapl", "fund")):
        evidence.append({
            "evidence_id": evidence_id,
            "source_tier": "regulator" if index < 3 else "exchange",
            "source_locator": f"https://data.example.org/{evidence_id}",
            "published_at": stamp(-7200),
            "retrieved_at": stamp(-30),
            "content_sha256": format(index + 1, "064x"),
            "claim": f"coverage for {evidence_id}",
        })
    return {
        "schema_version": "pia_thesis_red_team_v1",
        "generated_at": stamp(-10),
        "window_start": stamp(-86400),
        "window_end": stamp(-60),
        "portfolio_snapshot_binding": copy.deepcopy(BINDING),
        "scope_coverage": {scope: {"status": "complete", "evidence_ids": [scope]}
                           for scope in ("macro", "sector", "regulatory")},
        "assessments": assessments,
        "evidence_items": evidence,
    }


def assessment(symbol: str, conclusion: str, evidence_id: str, **extra) -> dict:
    payload = {"symbol": symbol, "conclusion": conclusion,
               "rationale": f"{symbol} assessment", "evidence_ids": [evidence_id]}
    payload.update(extra)
    return payload


def evaluate(pack: dict) -> dict:
    return evaluate_thesis_evidence(pack, expected_symbols=SYMBOLS,
                                    portfolio_snapshot_binding=copy.deepcopy(BINDING),
                                    evaluation_epoch=NOW.timestamp())


class ConditionNotDueTests(unittest.TestCase):
    def test_all_conditions_not_due_is_complete_with_a_new_aggregate(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", condition_ids=["aapl-aa"],
                       due_date="2027-09-09"),
            assessment("159516.SZ", "condition_not_due", "fund",
                       condition_ids=["fund-aa"], due_date="2027-03-01"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["fatal_event_status"], "no_condition_due_yet")
        self.assertEqual(report["not_due_symbols"], ["AAPL", "159516.SZ"])
        self.assertEqual(report["earliest_due_date"], "2027-03-01")
        self.assertEqual(report["fatal_symbols"], [])

    def test_missing_condition_ids_is_rejected(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", due_date="2027-09-09"),
            assessment("159516.SZ", "no_fatal_breach_verified", "fund"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(any("condition_ids_required" in error for error in report["errors"]))

    def test_due_date_in_the_past_cannot_be_not_due(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", condition_ids=["aapl-aa"],
                       due_date="2026-01-01"),
            assessment("159516.SZ", "no_fatal_breach_verified", "fund"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(any("due_date_not_in_the_future" in error for error in report["errors"]))

    def test_missing_due_date_is_rejected(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", condition_ids=["aapl-aa"]),
            assessment("159516.SZ", "no_fatal_breach_verified", "fund"),
        ])
        report = evaluate(pack)
        self.assertTrue(any("due_date_required" in error for error in report["errors"]))

    def test_verified_symbol_outranks_not_due_in_the_aggregate(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", condition_ids=["aapl-aa"],
                       due_date="2027-09-09"),
            assessment("159516.SZ", "no_fatal_breach_verified", "fund"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["fatal_event_status"], "no_fatal_breach_verified")
        self.assertEqual(report["not_due_symbols"], ["AAPL"])

    def test_fatal_breach_still_outranks_everything(self):
        pack = build_pack([
            assessment("AAPL", "fatal_breach", "aapl"),
            assessment("159516.SZ", "condition_not_due", "fund",
                       condition_ids=["fund-aa"], due_date="2027-03-01"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["fatal_event_status"], "fatal_breach_detected")
        self.assertEqual(report["fatal_symbols"], ["AAPL"])

    def test_insufficient_evidence_still_leaves_the_gate_incomplete(self):
        pack = build_pack([
            assessment("AAPL", "insufficient_evidence", "aapl"),
            assessment("159516.SZ", "condition_not_due", "fund",
                       condition_ids=["fund-aa"], due_date="2027-03-01"),
        ])
        report = evaluate(pack)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["fatal_event_status"], "not_assessed")

    def test_not_due_does_not_claim_verification_in_its_own_words(self):
        pack = build_pack([
            assessment("AAPL", "condition_not_due", "aapl", condition_ids=["aapl-aa"],
                       due_date="2027-09-09"),
            assessment("159516.SZ", "condition_not_due", "fund",
                       condition_ids=["fund-aa"], due_date="2027-03-01"),
        ])
        report = evaluate(pack)
        self.assertNotEqual(report["fatal_event_status"], "no_fatal_breach_verified")
        self.assertIn("not_due_symbols", report)


if __name__ == "__main__":
    unittest.main()
