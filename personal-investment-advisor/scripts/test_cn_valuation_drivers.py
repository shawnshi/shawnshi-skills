import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from cn_valuation_drivers import VERSION, evaluate
from cn_filing_facts import VERSION as FILING_VERSION
from source_timing_contract import verify_source_capture


class OperatingDCFTests(unittest.TestCase):
    def setUp(self):
        self.model = {
            "schema_version": VERSION, "instrument": {"symbol": "600000.SS", "market": "CN", "asset_type": "stock", "industry_type": "operating_company", "currency": "CNY"},
            "as_of_date": date.today().isoformat(), "base_revenue_cny": 1000,
            "revenue_anchor": {"fact_id": "filing1", "value": 1, "scale": 1000, "source_locator": "https://www.sse.com.cn/synthetic", "content_sha256": "a" * 64, "reviewed_page": "page 5, consolidated revenue"},
            "cases": {name: {"discount_rate": 0.1, "terminal_growth": 0, "years": [{"year": 1, "revenue_growth": 0, "operating_margin": 0.1, "cash_tax_rate": 0.2, "depreciation_amortization_cny": 0, "capital_expenditure_cny": 0, "change_in_working_capital_cny": 0}]} for name in ("base", "bull", "bear")},
        }
        self.dashboard = {"stock_code": "600000.SS", "research_brief": {"instrument": {"symbol": "600000.SS", "market": "CN", "asset_type": "stock"}}, "scenario_analysis": {"valuation_contract_version": "3.0", "valuation_method": "enterprise_value_bridge", "currency": "CNY", "as_of_date": date.today().isoformat(), **{name: {"enterprise_value": 800} for name in ("base", "bull", "bear")}}}

    def test_recomputes_ev_and_terminal_share(self):
        result = evaluate(self.model, self.dashboard)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["cases"]["base"]["enterprise_value_cny"], 800)
        self.assertEqual(result["cases"]["base"]["terminal_share"], 0.909091)

    def test_tampered_dashboard_and_bad_growth_fail_closed(self):
        self.dashboard["scenario_analysis"]["base"]["enterprise_value"] = 900
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")
        self.dashboard["scenario_analysis"]["base"]["enterprise_value"] = 800
        self.model["cases"]["base"]["terminal_growth"] = 0.1
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")

    def test_missing_driver_nan_financial_sector_and_wrong_anchor_fail(self):
        self.model["cases"]["base"]["years"][0].pop("cash_tax_rate")
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")
        self.model["cases"]["base"]["years"][0]["cash_tax_rate"] = float("nan")
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")
        self.model["cases"]["base"]["years"][0]["cash_tax_rate"] = 0.2
        self.model["instrument"]["industry_type"] = "bank"
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")
        self.model["instrument"]["industry_type"] = "operating_company"
        self.model["revenue_anchor"]["scale"] = 5
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")

    def test_negative_capex_and_tax_fail_closed(self):
        self.model["cases"]["base"]["years"][0]["capital_expenditure_cny"] = -0.1
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")
        self.model["cases"]["base"]["years"][0]["capital_expenditure_cny"] = 0
        self.model["cases"]["base"]["years"][0]["cash_tax_rate"] = -0.1
        self.assertEqual(evaluate(self.model, self.dashboard)["status"], "invalid_input")

    def test_verified_filing_anchor_detects_changed_fact_and_missing_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "synthetic.txt"
            raw.write_text("Synthetic source; no real filing claim", encoding="utf-8")
            now = datetime.now(timezone.utc)
            observed = (now - timedelta(days=2)).isoformat()
            retrieved = (now - timedelta(days=1)).isoformat()
            locator = "https://www.sse.com.cn/synthetic"
            receipt = verify_source_capture(raw, source_locator=locator, availability_observed_at=observed, retrieved_at=retrieved)
            fact = {"fact_id": "filing1", "symbol": "600000.SS", "metric": "operating_revenue_consolidated", "period_end": "2025-12-31", "valuation_date": "2025-12-31", "unit": "CNY", "scale": 1000, "value": 1, "revision": "original", "supersedes_fact_id": None, "source_type": "filing", "source_tier": "annual_audited_filing", "source_locator": locator, "content_sha256": receipt["content_sha256"], "timing_contract_version": "1.0", "publication_precision": "unknown", "published_at": None, "publication_date": None, "publication_utc_offset": None, "availability_observed_at": observed, "retrieved_at": retrieved, "source_capture_receipt": receipt}
            package = {"schema_version": FILING_VERSION, "instrument": {"symbol": "600000.SS", "market": "CN", "asset_type": "stock"}, "cutoff_at": now.isoformat(), "facts": [fact]}
            self.model["revenue_anchor"].update(source_locator=locator, content_sha256=receipt["content_sha256"])
            bound = evaluate(self.model, self.dashboard, filing_package=package, verify_filing_raw=True)
            self.assertEqual(bound["status"], "complete", bound)
            self.assertEqual(bound["source_anchor_status"], "raw_capture_bound_semantics_unverified")
            paths = [Path(temp) / name for name in ("model.json", "dashboard.json", "filing.json")]
            for path, value in zip(paths, (self.model, self.dashboard, package)):
                path.write_text(json.dumps(value), encoding="utf-8")
            command = [sys.executable, "-B", str(HERE / "cn_valuation_drivers.py"), str(paths[0]), str(paths[1]), "--filing-package", str(paths[2])]
            self.assertEqual(subprocess.run([*command, "--verify-filing-raw"], capture_output=True, text=True, timeout=10).returncode, 0)
            self.assertEqual(subprocess.run(command, capture_output=True, text=True, timeout=10).returncode, 3)
            package["facts"][0]["value"] = 2
            self.assertEqual(evaluate(self.model, self.dashboard, filing_package=package, verify_filing_raw=True)["status"], "invalid_input")
            package["facts"][0]["value"] = 1
            correction = copy.deepcopy(fact)
            correction.update(fact_id="filing2", value=2, revision="correction", supersedes_fact_id="filing1")
            correction["availability_observed_at"] = (now - timedelta(hours=12)).isoformat()
            correction["retrieved_at"] = (now - timedelta(hours=6)).isoformat()
            correction["source_capture_receipt"] = verify_source_capture(raw, source_locator=locator, availability_observed_at=correction["availability_observed_at"], retrieved_at=correction["retrieved_at"])
            package["facts"].append(correction)
            self.assertEqual(evaluate(self.model, self.dashboard, filing_package=package, verify_filing_raw=True)["status"], "invalid_input")
            package["facts"].pop()
            raw.unlink()
            self.assertEqual(evaluate(self.model, self.dashboard, filing_package=package, verify_filing_raw=True)["status"], "invalid_input")
            self.assertEqual(evaluate(self.model, self.dashboard, filing_package=package)["status"], "invalid_input")

    def test_cli_is_offline_and_fails_on_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.json"
            dashboard = Path(temp) / "dashboard.json"
            model.write_text(json.dumps(self.model), encoding="utf-8")
            dashboard.write_text(json.dumps(self.dashboard), encoding="utf-8")
            command = [sys.executable, "-B", str(HERE / "cn_valuation_drivers.py"), str(model), str(dashboard)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.dashboard["scenario_analysis"]["bear"]["enterprise_value"] = 123
            dashboard.write_text(json.dumps(self.dashboard), encoding="utf-8")
            rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(rejected.returncode, 3)


if __name__ == "__main__":
    unittest.main()
