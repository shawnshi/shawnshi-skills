import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from personal_risk_budget import VERSION, evaluate
from portfolio_scenario_analyzer import analyze_scenarios


class PersonalRiskBudgetTests(unittest.TestCase):
    def setUp(self):
        self.report = {"valid": True, "status": "ok", "scenario_contract_version": "2.0", "weight_snapshot": {"as_of": datetime.now(timezone.utc).isoformat(), "reconciled_weights": {"600000.SS": 0.7, "CASH_CNY": 0.3}}, "scenario_results": [{"name": "bear", "portfolio_return_after_cost": -0.12}, {"name": "base", "portfolio_return_after_cost": 0.03}]}
        self.budget = {"schema_version": VERSION, "source_type": "user_confirmed", "scenario_report_sha256": "a" * 64, "confirmed_at": datetime.now(timezone.utc).isoformat(), "horizon_days": 365, "max_loss_fraction": 0.15, "max_single_non_cash_weight": 0.75, "minimum_cash_weight": 0.2, "required_scenarios": ["base", "bear"]}

    def test_within_and_breached_are_not_trade_instructions(self):
        result = evaluate(self.report, self.budget, report_sha256="a" * 64)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["budget_status"], "within_supplied_scenarios")
        self.budget["max_loss_fraction"] = 0.1
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["budget_status"], "budget_boundary_breached")

    def test_user_declared_unbounded_horizon_requires_explicit_policy(self):
        self.budget["horizon_policy"] = "unbounded"
        self.budget["horizon_days"] = None
        result = evaluate(self.report, self.budget, report_sha256="a" * 64)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["horizon_policy"], "unbounded")
        self.assertIsNone(result["horizon_days"])
        self.budget.pop("horizon_policy")
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["status"], "invalid_input")
        self.budget["horizon_policy"] = "unbounded"
        self.budget["horizon_days"] = 365
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["status"], "invalid_input")

    def test_missing_cost_wrong_report_and_gaps_fail_closed(self):
        self.report["scenario_results"][0]["portfolio_return_after_cost"] = None
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["status"], "invalid_input")
        self.report["scenario_results"][0]["portfolio_return_after_cost"] = -0.12
        self.budget["required_scenarios"] = ["base"]
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["status"], "invalid_input")
        self.budget["required_scenarios"] = ["base", "bear"]
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="b" * 64)["status"], "invalid_input")
        self.report["weight_snapshot"] = None
        self.assertEqual(evaluate(self.report, self.budget, report_sha256="a" * 64)["status"], "invalid_input")

    def test_real_scenario_analyzer_output_is_consumed_without_private_inputs(self):
        symbol = "600000.SS"
        portfolio = {"base_currency": "CNY", "positions": [{"symbol": symbol, "quantity": 1, "avg_cost": 100, "currency": "CNY", "market": "CN", "asset_type": "stock", "current_weight": 1.0}]}
        assumptions = {"scenario_contract_version": "2.0", "base_currency": "CNY", "weight_snapshot": {"as_of": "2026-08-02T09:30:00+08:00", "source": "synthetic fixture", "source_locator": "dataset://pia/scenario-weights/synthetic", "retrieved_at": "2026-08-02T09:31:00+08:00", "content_sha256": "5" * 64, "valuation_basis": "base_currency_market_value", "market_values_base_currency": {symbol: 100}}, "scenarios": [{"name": "bear", "asset_returns": {symbol: -0.1}, "assumption_source": "synthetic fixture", "cost_model": {"source": "synthetic costs", "source_locator": "prompt:synthetic-costs", "as_of": "2026-08-02", "by_symbol": {symbol: {"transaction_cost_bps": 10, "assumed_turnover": 1.0}}}}]}
        report = analyze_scenarios(portfolio, assumptions)
        self.assertTrue(report["valid"], report["errors"])
        self.budget.update(required_scenarios=["bear"], minimum_cash_weight=0, max_single_non_cash_weight=1)
        result = evaluate(report, self.budget, report_sha256="a" * 64)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["measurements"]["worst_after_cost_return"], -0.101)

    def test_cli_binds_exact_report_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path, budget_path = (Path(tmp) / name for name in ("report.json", "budget.json"))
            raw = json.dumps(self.report).encode("utf-8")
            report_path.write_bytes(raw)
            self.budget["scenario_report_sha256"] = hashlib.sha256(raw).hexdigest()
            budget_path.write_text(json.dumps(self.budget), encoding="utf-8")
            command = [sys.executable, "-B", str(HERE / "personal_risk_budget.py"), str(report_path), str(budget_path)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            report_path.write_bytes(raw + b" ")
            self.assertEqual(subprocess.run(command, capture_output=True, text=True, timeout=10).returncode, 3)


if __name__ == "__main__":
    unittest.main()
