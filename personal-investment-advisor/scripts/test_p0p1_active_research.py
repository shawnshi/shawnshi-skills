import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pia  # noqa: E402
from active_alpha_scan import run_active_scan  # noqa: E402
from active_portfolio_constructor import run_construction  # noqa: E402
from alpha_validation import evaluate_alpha_package  # noqa: E402
from rebalance_proposal import run_proposal  # noqa: E402


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def evidence(day="2026-08-01T00:00:00+00:00"):
    return {
        "observed_at": day,
        "available_at": day,
        "retrieved_at": "2026-08-20T00:00:00+00:00",
        "source_locator": "dataset://licensed-point-in-time-snapshot",
        "content_sha256": SHA_A,
    }


def alpha_package():
    gross = [
        0.008, 0.012, 0.006, 0.015, 0.007, 0.013, 0.005, 0.011,
        0.009, 0.014, 0.006, 0.016, 0.008, 0.013, 0.007, 0.015,
    ]
    observations = []
    for index, value in enumerate(gross, start=1):
        observations.append(
            {
                "date": f"2026-07-{index:02d}T00:00:00+00:00",
                "segment": "in_sample" if index <= 8 else "out_of_sample",
                "gross_return": value,
                "benchmark_return": 0.001,
                "turnover": 0.02,
            }
        )
    components = lambda score: [
        {
            "name": "quality",
            "score": score,
            "confidence": 0.9,
            "decay_half_life_days": 120,
            "evidence": evidence(),
        },
        {
            "name": "momentum",
            "score": score * 0.8,
            "confidence": 0.8,
            "decay_half_life_days": 60,
            "evidence": evidence("2026-08-15T00:00:00+00:00"),
        },
    ]
    return {
        "schema_version": "pia_alpha_evidence_v1",
        "decision_scope": "research_only",
        "as_of": "2026-08-20T00:00:00+00:00",
        "annualization_factor": 252,
        "universe": {
            "symbols": ["AAA", "BBB"],
            "benchmark": "SPY",
            "base_currency": "USD",
            "survivorship_bias_control": True,
            "corporate_action_adjusted": True,
            "point_in_time_evidence": evidence(),
        },
        "model": {
            "model_id": "quality-momentum",
            "version": "1.0.0",
            "economic_rationale": "Profitable firms with persistent relative strength may earn a premium.",
            "selected_trial_id": "selected",
            "trial_ledger": [
                {"trial_id": "selected", "parameter_fingerprint": SHA_A},
                {"trial_id": "weak", "parameter_fingerprint": SHA_B},
                {"trial_id": "inverse", "parameter_fingerprint": SHA_C},
            ],
        },
        "cost_model": {
            "commission_bps": 1,
            "spread_bps": 2,
            "market_impact_bps": 2,
            "tax_bps": 0,
            "evidence": evidence(),
        },
        "observations": observations,
        "trial_net_excess_returns": {
            "selected": [value - 0.0011 for value in gross],
            "weak": [0.001, -0.001, 0.0005, -0.0005] * 4,
            "inverse": [-value + 0.001 for value in gross],
        },
        "signals": [
            {
                "symbol": "AAA",
                "expected_excess_return_annualized": 0.08,
                "expected_return_standard_error": 0.01,
                "economic_rationale": "High quality and persistence.",
                "invalidation_condition": "Margin and relative strength both reverse.",
                "components": components(1.5),
            },
            {
                "symbol": "BBB",
                "expected_excess_return_annualized": 0.04,
                "expected_return_standard_error": 0.015,
                "economic_rationale": "Moderate quality and persistence.",
                "invalidation_condition": "Balance sheet weakens.",
                "components": components(0.8),
            },
        ],
    }


def promotion_policy():
    return {
        "schema_version": "pia_alpha_promotion_policy_v1",
        "min_oos_observations": 8,
        "min_net_information_ratio": 0.0,
        "min_deflated_sharpe_probability": 0.0,
        "max_probability_backtest_overfitting": 1.0,
        "max_drawdown_fraction": 0.5,
        "max_annual_turnover": 10.0,
        "cost_stress_multiplier": 2.0,
        "min_cost_stress_information_ratio": 0.0,
        "pbo_block_count": 4,
    }


def scan_policy():
    return {
        "schema_version": "pia_active_scan_policy_v1",
        "required_components": ["quality", "momentum"],
        "component_weights": {"quality": 0.6, "momentum": 0.4},
        "max_component_age_days": 60,
        "minimum_confidence": 0.5,
        "uncertainty_penalty_multiplier": 1.0,
        "retain_count": 1,
    }


def construction_policy():
    return {
        "schema_version": "pia_active_construction_policy_v1",
        "decision_scope": "research_only",
        "as_of": "2026-08-20T00:00:00+00:00",
        "symbols": ["AAA", "BBB"],
        "current_weights": {"AAA": 0.5, "BBB": 0.5},
        "risk_budgets": {"AAA": 0.5, "BBB": 0.5},
        "minimum_weights": {"AAA": 0.1, "BBB": 0.1},
        "maximum_weights": {"AAA": 0.9, "BBB": 0.9},
        "covariance": {
            "symbols": ["AAA", "BBB"],
            "matrix": [[0.04, 0.006], [0.006, 0.09]],
            "observation_count": 252,
            "window_start": "2025-08-20T00:00:00+00:00",
            "window_end": "2026-08-19T00:00:00+00:00",
            "as_of": "2026-08-20T00:00:00+00:00",
            "source_locator": "dataset://licensed-return-history",
            "content_sha256": SHA_B,
        },
        "risk_aversion": 5.0,
        "transaction_cost_bps": 0.0,
        "cost_evidence": {
            "observed_at": "2026-08-20T00:00:00+00:00",
            "source_locator": "dataset://broker-cost-schedule",
            "content_sha256": SHA_C,
        },
        "step_size": 0.2,
        "tolerance": 1e-9,
        "max_iterations": 10000,
        "max_one_way_turnover": 0.2,
        "max_trade_weight": 0.3,
    }


class AlphaValidationTests(unittest.TestCase):
    def test_valid_package_is_eligible_and_cost_adjusted(self):
        report = evaluate_alpha_package(
            alpha_package(), promotion_policy(), package_sha256=SHA_A, policy_sha256=SHA_B
        )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["promotion_status"], "eligible_for_active_research")
        self.assertTrue(report["formal_use_allowed"])
        self.assertIsNotNone(report["metrics"]["deflated_sharpe_probability"])
        self.assertIsNotNone(report["metrics"]["probability_backtest_overfitting"])
        self.assertEqual(report["metrics"]["cost_bps_per_unit_turnover"], 5.0)

    def test_threshold_failure_is_incomplete_and_fail_closed(self):
        policy = promotion_policy()
        policy["min_net_information_ratio"] = 1000.0
        report = evaluate_alpha_package(alpha_package(), policy)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["promotion_status"], "experimental_only")
        self.assertFalse(report["formal_use_allowed"])
        self.assertTrue(report["fail_closed"]["triggered"])

    def test_future_or_unaligned_evidence_fails_contract(self):
        package = alpha_package()
        package["universe"]["point_in_time_evidence"]["available_at"] = "2026-09-01T00:00:00+00:00"
        package["trial_net_excess_returns"]["selected"] = [0.01]
        report = evaluate_alpha_package(package, promotion_policy())
        self.assertEqual(report["status"], "invalid_input")
        self.assertTrue(any("cannot be after package as_of" in error for error in report["errors"]))
        self.assertTrue(any("one-for-one" in error for error in report["errors"]))


class ActivePipelineTests(unittest.TestCase):
    def setUp(self):
        self.package = alpha_package()
        self.validation = evaluate_alpha_package(
            self.package, promotion_policy(), package_sha256=SHA_A, policy_sha256=SHA_B
        )
        self.scan = run_active_scan(
            self.package,
            self.validation,
            scan_policy(),
            package_sha256=SHA_A,
            validation_sha256=SHA_B,
            policy_sha256=SHA_C,
        )

    def test_rank_yank_requires_hash_bound_promoted_alpha(self):
        self.assertEqual(self.scan["status"], "complete")
        self.assertEqual([row["symbol"] for row in self.scan["rankings"]], ["AAA", "BBB"])
        self.assertEqual(self.scan["rankings"][0]["research_pool"], "rank_pool")
        self.assertEqual(self.scan["rankings"][1]["research_pool"], "yank_review_pool")
        broken = copy.deepcopy(self.validation)
        broken["alpha_package_sha256"] = SHA_C
        rejected = run_active_scan(
            self.package,
            broken,
            scan_policy(),
            package_sha256=SHA_A,
            validation_sha256=SHA_B,
            policy_sha256=SHA_C,
        )
        self.assertNotEqual(rejected["status"], "complete")

    def test_erc_and_active_constructor_use_covariance_and_constraints(self):
        report = run_construction(
            self.scan, construction_policy(), scan_sha256=SHA_A, policy_sha256=SHA_B
        )
        self.assertEqual(report["status"], "complete", report)
        self.assertTrue(report["erc_candidate"]["converged"])
        risk_shares = [
            row["variance_contribution_share"]
            for row in report["erc_candidate"]["bounded_risk_contributions"]
        ]
        self.assertAlmostEqual(sum(risk_shares), 1.0, places=8)
        weights = report["active_candidate"]["weights"]
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=8)
        self.assertLessEqual(report["active_candidate"]["one_way_turnover"], 0.2 + 1e-9)
        rendered = json.dumps(report).lower()
        self.assertNotIn("target_weight", rendered)
        self.assertNotIn('"order"', rendered)

    def test_non_psd_covariance_fails_closed(self):
        policy = construction_policy()
        policy["covariance"]["matrix"] = [[0.04, 0.2], [0.2, 0.09]]
        report = run_construction(self.scan, policy, scan_sha256=SHA_A, policy_sha256=SHA_B)
        self.assertEqual(report["detail_status"], "covariance_not_positive_semidefinite")
        self.assertFalse(report["formal_use_allowed"])

    def test_proposal_has_no_trade_band_and_no_actionability(self):
        construction = run_construction(
            self.scan, construction_policy(), scan_sha256=SHA_A, policy_sha256=SHA_B
        )
        proposal = run_proposal(
            construction,
            {
                "schema_version": "pia_rebalance_proposal_policy_v1",
                "decision_scope": "research_only",
                "no_trade_band": 0.01,
                "minimum_net_expected_benefit": 0.0,
                "review_horizon_days": 90,
            },
            construction_sha256=SHA_A,
            policy_sha256=SHA_B,
        )
        self.assertEqual(proposal["status"], "complete")
        self.assertEqual(proposal["actionability"], "prohibited")
        self.assertTrue(all(row["actionability"] == "prohibited" for row in proposal["rows"]))
        rendered = json.dumps(proposal).lower()
        self.assertNotIn("target_weight", rendered)
        self.assertNotIn('"order"', rendered)

    def test_stable_router_exposes_all_four_active_stages(self):
        cases = {
            "alpha-validate": ("alpha_validation.py", ["package.json", "--policy-file", "policy.json"]),
            "alpha-scan": (
                "active_alpha_scan.py",
                ["package.json", "--validation-report", "validation.json", "--policy-file", "policy.json"],
            ),
            "portfolio-construct": (
                "active_portfolio_constructor.py",
                ["scan.json", "--policy-file", "policy.json"],
            ),
            "rebalance-proposal": (
                "rebalance_proposal.py",
                ["construction.json", "--policy-file", "policy.json"],
            ),
        }
        argv = {
            "alpha-validate": ["alpha-validate", "package.json", "--policy-file", "policy.json"],
            "alpha-scan": ["alpha-scan", "package.json", "--validation-report", "validation.json", "--policy-file", "policy.json"],
            "portfolio-construct": ["portfolio-construct", "scan.json", "--policy-file", "policy.json"],
            "rebalance-proposal": ["rebalance-proposal", "construction.json", "--policy-file", "policy.json"],
        }
        parser = pia._build_parser()
        for command, (script, child_arguments) in cases.items():
            with self.subTest(command=command), mock.patch.object(pia, "_run_child", return_value=({}, 0)) as run:
                args = parser.parse_args(argv[command])
                pia._dispatch(args)
                self.assertEqual(run.call_args.kwargs["script_name"], script)
                self.assertEqual(run.call_args.kwargs["child_arguments"], child_arguments)

    def test_actual_stable_cli_completes_four_stage_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            inputs = {
                "package.json": self.package,
                "promotion.json": promotion_policy(),
                "scan-policy.json": scan_policy(),
                "construction-policy.json": construction_policy(),
                "proposal-policy.json": {
                    "schema_version": "pia_rebalance_proposal_policy_v1",
                    "decision_scope": "research_only",
                    "no_trade_band": 0.01,
                    "minimum_net_expected_benefit": 0.0,
                    "review_horizon_days": 90,
                },
            }
            for name, payload in inputs.items():
                (root / name).write_text(json.dumps(payload), encoding="utf-8")

            commands = [
                ["alpha-validate", str(root / "package.json"), "--policy-file", str(root / "promotion.json")],
                ["alpha-scan", str(root / "package.json"), "--validation-report", str(root / "validation.json"), "--policy-file", str(root / "scan-policy.json")],
                ["portfolio-construct", str(root / "scan.json"), "--policy-file", str(root / "construction-policy.json")],
                ["rebalance-proposal", str(root / "construction.json"), "--policy-file", str(root / "proposal-policy.json")],
            ]
            outputs = ["validation.json", "scan.json", "construction.json", "proposal.json"]
            for command, output_name in zip(commands, outputs, strict=True):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT_DIR / "pia.py"), *command],
                    cwd=SCRIPT_DIR,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
                envelope = json.loads(completed.stdout)
                self.assertEqual(envelope["status"], "complete")
                (root / output_name).write_text(
                    json.dumps(envelope["result"]), encoding="utf-8"
                )
            proposal = json.loads((root / "proposal.json").read_text(encoding="utf-8"))
            self.assertEqual(proposal["actionability"], "prohibited")


if __name__ == "__main__":
    unittest.main()
