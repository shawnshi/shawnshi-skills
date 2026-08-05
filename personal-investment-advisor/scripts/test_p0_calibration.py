import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from advice_journal import batch_update_outcomes, build_journal_entry, load_entries  # noqa: E402
from decision_outcome_report import build_report, calculate_calibration  # noqa: E402
from sync_outcomes import _canonical_digest, build_outcome_update  # noqa: E402


SYNC_SOURCE = {
    "source_provider": "test market data provider",
    "source_locator": "test://daily-history",
    "daily_interval": "1d",
    "intraday_interval": "5m",
}


def verified_outcome(*args, **kwargs):
    return build_outcome_update(*args, **SYNC_SOURCE, **kwargs)


def formal_entry(net_return: float, **overrides):
    entry = {
        "entry_id": "formal-entry",
        "calibration_sample_type": "research",
        "calibration_eligible": True,
        "dual_trigger_detected": False,
        "calibration_start_date": "2026-01-01",
        "calibration_start_price": 100.0,
        "outcome_date": "2026-01-31",
        "outcome_price": 105.0,
        "outcome_return_pct": 5.0,
        "benchmark_return_pct": 5.0 - net_return,
        "net_excess_return_pct": net_return,
        "investment_horizon_days": 30,
        "confidence_level": "中",
        "calibration_quality": "observed_daily",
        "outcome_resolution_method": "fixed_horizon_close",
        "outcome_resolution_timestamp": None,
    }
    entry.update(overrides)
    evidence = {
        "contract_version": "1.0",
        "generator": "sync_outcomes.py",
        "source": {
            "provider": "test market data provider",
            "locator": "test://daily-history",
            "daily_interval": "1d",
        },
        "daily_coverage": {
            "asset": {"row_count": 2, "first_timestamp": "2026-01-01", "last_timestamp": "2026-01-31", "content_sha256": "a" * 64},
            "benchmark": {"row_count": 2, "first_timestamp": "2026-01-01", "last_timestamp": "2026-01-31", "content_sha256": "b" * 64},
        },
        "result_summary": {
            field: entry[field]
            for field in (
                "calibration_start_date", "calibration_start_price", "outcome_date",
                "outcome_price", "outcome_return_pct", "benchmark_return_pct",
                "net_excess_return_pct", "outcome_resolution_method", "dual_trigger_detected",
            )
        },
        "intraday_sequence": None,
    }
    evidence["evidence_sha256"] = _canonical_digest(evidence)
    entry["outcome_evidence"] = evidence
    return entry


def research_entry(**overrides):
    entry = {
        "entry_id": "AAPL-20260101",
        "stock_code": "AAPL",
        "research_scope": "research_only",
        "calibration_sample_type": "research",
        "research_anchor_date": "2026-01-01",
        "investment_horizon_days": 2,
        "benchmark_symbol": "SPY",
        "dual_trigger_policy": "exclude",
        "observation_boundaries": {
            "downside_boundary": {
                "role": "downside_boundary",
                "operator": "lte",
                "value": 90,
                "currency": "USD",
                "authority_status": "user_confirmed",
            },
            "upside_boundary": {
                "role": "upside_boundary",
                "operator": "gte",
                "value": 110,
                "currency": "USD",
                "authority_status": "user_confirmed",
            },
        },
    }
    entry.update(overrides)
    return entry


def dual_trigger_histories():
    asset = [
        {"Date": "2026-01-01", "High": 101, "Low": 99, "Close": 100},
        {"Date": "2026-01-02", "High": 115, "Low": 85, "Close": 105},
    ]
    benchmark = [
        {"Date": "2026-01-01", "Close": 200},
        {"Date": "2026-01-02", "Close": 202},
    ]
    return asset, benchmark


class JournalResearchSampleTests(unittest.TestCase):
    def test_journal_declares_research_sample_without_inventing_execution(self):
        payload = {
            "stock_code": "AAPL",
            "stock_name": "Apple",
            "research_mode": "research_only",
            "confidence_level": "中",
            "dashboard": {
                "data_perspective": {"price_position": {"current_price": 100}},
                "core_conclusion": {"one_sentence": "Research watch only"},
            },
            "research_brief": {
                "as_of_date": "2026-01-01",
                "investment_horizon_days": 30,
                "benchmark": {"symbol": "SPY", "market": "US"},
                "output_contract": {
                    "decision_scope": "research_only",
                    "transaction_cost_bps": 10,
                    "dual_trigger_policy": "conservative",
                },
            },
            "monitoring_boundaries": {
                "decision_scope": "observation_only",
                "metric": "regular_market_price",
                "boundaries": [
                    {
                        "boundary_id": "lower",
                        "role": "downside_boundary",
                        "operator": "lte",
                        "value": 90,
                        "currency": "USD",
                        "authority_status": "user_confirmed",
                    },
                    {
                        "boundary_id": "upper",
                        "role": "upside_boundary",
                        "operator": "gte",
                        "value": 110,
                        "currency": "USD",
                        "authority_status": "user_confirmed",
                    },
                ],
            },
            "evidence_items": [],
        }

        entry = build_journal_entry(payload)

        self.assertEqual(entry["calibration_sample_type"], "research")
        self.assertEqual(entry["research_anchor_date"], "2026-01-01")
        self.assertEqual(entry["dual_trigger_policy"], "exclude")
        self.assertEqual(entry["dual_trigger_sensitivity_policy"], "conservative")
        self.assertEqual(
            entry["observation_boundaries"]["downside_boundary"]["value"], 90
        )
        self.assertNotIn("executed", entry)
        self.assertNotIn("position_direction", entry)


class ResearchOutcomeSyncTests(unittest.TestCase):
    def test_unexecuted_research_sample_reaches_fixed_horizon(self):
        entry = research_entry(executed=False, observation_boundaries={})
        asset = [
            {"Date": "2026-01-01", "Close": 100},
            {"Date": "2026-01-03", "Close": 110},
        ]
        benchmark = [
            {"Date": "2026-01-01", "Close": 200},
            {"Date": "2026-01-03", "Close": 204},
        ]

        result = verified_outcome(entry, asset, benchmark, today=date(2026, 1, 4))

        self.assertTrue(result["calibration_eligible"])
        self.assertEqual(result["calibration_sample_type"], "research")
        self.assertEqual(result["calibration_start_price"], 100.0)
        self.assertAlmostEqual(result["net_excess_return_pct"], 8.0)
        self.assertEqual(
            result["return_definition"],
            "asset_return_minus_benchmark_return_without_execution_assumptions",
        )

    def test_execution_metadata_does_not_replace_research_anchor(self):
        entry = research_entry(
            executed=True,
            execution_price=50,
            execution_date="2026-01-01",
            execution_timing="close",
            position_direction="long",
            transaction_cost_bps=100,
            observation_boundaries={},
        )
        asset = [
            {"Date": "2026-01-01", "Close": 100},
            {"Date": "2026-01-03", "Close": 110},
        ]
        benchmark = [
            {"Date": "2026-01-01", "Close": 200},
            {"Date": "2026-01-03", "Close": 204},
        ]

        result = verified_outcome(entry, asset, benchmark, today=date(2026, 1, 4))

        self.assertTrue(result["calibration_eligible"])
        self.assertEqual(result["calibration_start_price"], 100.0)
        self.assertAlmostEqual(result["outcome_return_pct"], 10.0)
        self.assertAlmostEqual(result["net_excess_return_pct"], 8.0)

    def test_unresolved_daily_dual_trigger_defaults_to_formal_exclusion(self):
        asset, benchmark = dual_trigger_histories()

        result = verified_outcome(
            research_entry(), asset, benchmark, today=date(2026, 1, 3)
        )

        self.assertFalse(result["calibration_eligible"])
        self.assertTrue(result["dual_trigger_detected"])
        self.assertEqual(result["dual_trigger_policy"], "exclude")
        self.assertIsNone(result["sensitivity_analysis"])

    def test_conservative_dual_trigger_is_sensitivity_only(self):
        asset, benchmark = dual_trigger_histories()

        result = verified_outcome(
            research_entry(),
            asset,
            benchmark,
            dual_trigger_policy="conservative",
            today=date(2026, 1, 3),
        )

        self.assertFalse(result["calibration_eligible"])
        self.assertEqual(result["calibration_quality"], "assumption_based_conservative")
        self.assertIsNone(result["net_excess_return_pct"])
        sensitivity = result["sensitivity_analysis"]
        self.assertEqual(sensitivity["policy"], "conservative")
        self.assertEqual(sensitivity["outcome_status"], "Downside Boundary Reached")
        self.assertAlmostEqual(sensitivity["net_excess_return_pct"], -11.0)

    def test_conservative_remains_sensitivity_only_when_intraday_order_is_available(self):
        asset, benchmark = dual_trigger_histories()
        intraday = [
            {"Date": "2026-01-02T10:00:00-05:00", "High": 111, "Low": 100, "Close": 110},
        ]
        benchmark_intraday = [
            {"Date": "2026-01-02T10:00:00-05:00", "Close": 202},
        ]

        result = verified_outcome(
            research_entry(),
            asset,
            benchmark,
            intraday_history=intraday,
            benchmark_intraday_history=benchmark_intraday,
            dual_trigger_policy="conservative",
            today=date(2026, 1, 3),
        )

        self.assertFalse(result["calibration_eligible"])
        self.assertEqual(
            result["sensitivity_analysis"]["outcome_status"],
            "Downside Boundary Reached",
        )
        self.assertEqual(
            result["sensitivity_analysis"]["outcome_resolution_method"],
            "daily_ohlc_conservative_stop_first",
        )

    def test_formal_exclude_can_attach_requested_conservative_sensitivity(self):
        asset, benchmark = dual_trigger_histories()

        result = verified_outcome(
            research_entry(dual_trigger_sensitivity_policy="conservative"),
            asset,
            benchmark,
            today=date(2026, 1, 3),
        )

        self.assertFalse(result["calibration_eligible"])
        self.assertEqual(result["dual_trigger_policy"], "exclude")
        self.assertEqual(result["sensitivity_analysis"]["policy"], "conservative")
        self.assertIsNone(result["net_excess_return_pct"])

    def test_intraday_sequence_is_formally_eligible_under_exclude_policy(self):
        asset, benchmark = dual_trigger_histories()
        intraday = [
            {"Date": "2026-01-02T09:30:00-05:00", "High": 105, "Low": 95, "Close": 102},
            {"Date": "2026-01-02T10:00:00-05:00", "High": 111, "Low": 100, "Close": 110},
        ]
        benchmark_intraday = [
            {"Date": "2026-01-02T10:00:00-05:00", "Close": 202},
        ]

        result = verified_outcome(
            research_entry(),
            asset,
            benchmark,
            intraday_history=intraday,
            benchmark_intraday_history=benchmark_intraday,
            today=date(2026, 1, 3),
        )

        self.assertTrue(result["calibration_eligible"])
        self.assertEqual(result["dual_trigger_policy"], "exclude")
        self.assertEqual(result["outcome_status"], "Upside Boundary Reached")
        self.assertEqual(result["calibration_quality"], "observed_intraday")
        persisted = research_entry()
        persisted.update(result)
        self.assertEqual(calculate_calibration([persisted])["eligible_count"], 1)

    def test_intraday_self_report_without_complete_sequence_proof_is_excluded(self):
        asset, benchmark = dual_trigger_histories()
        result = verified_outcome(
            research_entry(),
            asset,
            benchmark,
            intraday_history=[
                {"Date": "2026-01-02T10:00:00-05:00", "High": 111, "Low": 100, "Close": 110},
            ],
            benchmark_intraday_history=[
                {"Date": "2026-01-02T10:00:00-05:00", "Close": 202},
            ],
            today=date(2026, 1, 3),
        )
        entry = research_entry()
        entry.update(result)
        del entry["outcome_evidence"]["intraday_sequence"]["interval"]
        entry["outcome_evidence"]["evidence_sha256"] = _canonical_digest(
            {
                key: value
                for key, value in entry["outcome_evidence"].items()
                if key != "evidence_sha256"
            }
        )

        calibration = calculate_calibration([entry])

        self.assertEqual(calibration["eligible_count"], 0)
        self.assertIn(
            "dual-trigger intraday sequence metadata is incomplete or inconsistent",
            calibration["exclusion_reasons"],
        )


class CalibrationReportCohortTests(unittest.TestCase):
    def test_formal_research_headline_includes_nonexecuted_and_excludes_sensitivity(self):
        entries = [
            formal_entry(4.0, entry_id="research-not-executed", executed=False),
            formal_entry(-2.0, entry_id="research-executed", executed=True),
            {
                "entry_id": "legacy-conservative",
                "executed": True,
                "calibration_eligible": True,
                "net_excess_return_pct": -5.0,
                "investment_horizon_days": 30,
                "confidence_level": "中",
                "calibration_quality": "assumption_based_conservative",
                "dual_trigger_detected": True,
                "dual_trigger_policy": "conservative",
            },
        ]

        result = calculate_calibration(entries)

        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["research_sample_count"], 2)
        self.assertEqual(result["executed_research_subset_count"], 1)
        self.assertEqual(result["not_executed_research_subset_count"], 1)
        self.assertEqual(result["average_net_excess_return_pct"], 1.0)
        self.assertEqual(result["executed_research_subset_average_pct"], -2.0)
        self.assertEqual(result["not_executed_research_subset_average_pct"], 4.0)
        self.assertEqual(result["sensitivity_count"], 1)
        self.assertEqual(result["sensitivity_average_net_excess_return_pct"], -5.0)

    def test_sensitivity_only_update_is_persisted_without_formal_return(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            journal_path.write_text(
                json.dumps(
                    {
                        "entry_id": "research-dual-trigger",
                        "calibration_sample_type": "research",
                        "calibration_eligible": True,
                        "net_excess_return_pct": 99,
                        "outcome_evidence": {"stale": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            batch_update_outcomes(
                {
                    "research-dual-trigger": {
                        "calibration_eligible": False,
                        "calibration_exclusion_reason": "sensitivity only",
                        "net_excess_return_pct": None,
                        "calibration_quality": "assumption_based_conservative",
                        "sensitivity_analysis": {
                            "policy": "conservative",
                            "net_excess_return_pct": -3.0,
                        },
                    }
                },
                journal_path=str(journal_path),
            )

            persisted = load_entries(str(journal_path))[0]

        self.assertFalse(persisted["calibration_eligible"])
        self.assertIsNone(persisted["net_excess_return_pct"])
        self.assertIsNone(persisted["outcome_evidence"])
        self.assertEqual(
            persisted["sensitivity_analysis"]["net_excess_return_pct"], -3.0
        )

    def test_forged_unresolved_dual_trigger_cannot_enter_formal_calibration(self):
        result = calculate_calibration(
            [
                {
                    "entry_id": "forged-dual-trigger",
                    "calibration_sample_type": "research",
                    "calibration_eligible": True,
                    "net_excess_return_pct": 99.0,
                    "investment_horizon_days": 30,
                    "confidence_level": "高",
                    "calibration_quality": "unresolved_daily_dual_trigger",
                    "dual_trigger_detected": True,
                    "dual_trigger_policy": "exclude",
                    "outcome_resolution_method": None,
                }
            ]
        )

        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["excluded_count"], 1)
        self.assertIn(
            "verified sync_outcomes evidence contract is missing",
            result["exclusion_reasons"],
        )

    def test_missing_or_non_boolean_dual_trigger_flag_is_archive_only(self):
        entries = [
            formal_entry(1.0),
            formal_entry(2.0, dual_trigger_detected=None),
            formal_entry(3.0, dual_trigger_detected="false"),
        ]
        for entry in entries[1:]:
            entry["outcome_evidence"]["result_summary"]["dual_trigger_detected"] = entry[
                "dual_trigger_detected"
            ]
            entry["outcome_evidence"]["evidence_sha256"] = _canonical_digest(
                {
                    key: value
                    for key, value in entry["outcome_evidence"].items()
                    if key != "evidence_sha256"
                }
            )

        result = calculate_calibration(entries)

        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["excluded_count"], 2)
        self.assertEqual(
            result["exclusion_reasons"][
                "dual_trigger_detected must be an explicit boolean generated by sync_outcomes"
            ],
            2,
        )

    def test_false_dual_trigger_requires_generated_daily_evidence(self):
        entry = formal_entry(1.0)
        entry["outcome_evidence"] = None

        result = calculate_calibration([entry])

        self.assertEqual(result["eligible_count"], 0)
        self.assertIn(
            "verified sync_outcomes evidence contract is missing",
            result["exclusion_reasons"],
        )

    def test_old_untyped_entry_is_archive_only_even_with_self_reported_eligibility(self):
        entry = formal_entry(1.0)
        entry.pop("calibration_sample_type")

        result = calculate_calibration([entry])

        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["legacy_mixed_sample_count"], 1)
        self.assertIn("legacy or untyped entries are archive-only", result["exclusion_reasons"])

    def test_rendered_report_labels_research_and_execution_strata(self):
        temporary_root = os.environ.get("PIA_TEST_TMPDIR")
        with tempfile.TemporaryDirectory(dir=temporary_root) as tmpdir:
            journal_path = Path(tmpdir) / "journal.jsonl"
            entry = formal_entry(
                3.0,
                entry_id="research-not-executed",
                created_at="2026-02-01T10:00:00",
                stock_code="AAPL",
                executed=False,
            )
            journal_path.write_text(
                json.dumps(entry, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            report = build_report(str(journal_path))

        self.assertIn("决策范围: research_only", report)
        self.assertIn("正式研究样本数: 1", report)
        self.assertIn("未执行或未披露子集: 1", report)
        self.assertNotIn("| 方向 |", report)


if __name__ == "__main__":
    unittest.main()
