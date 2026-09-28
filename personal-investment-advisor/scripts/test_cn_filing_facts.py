import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from cn_filing_facts import VERSION, evaluate
from source_timing_contract import verify_source_capture


class FilingFactsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name) / "announcement.txt"
        self.raw.write_text("Synthetic filing, not real investment evidence", encoding="utf-8")
        now = datetime.now(timezone.utc)
        observed = (now - timedelta(days=2)).isoformat()
        retrieved = (now - timedelta(days=1)).isoformat()
        receipt = verify_source_capture(self.raw, source_locator="https://www.sse.com.cn/synthetic", availability_observed_at=observed, retrieved_at=retrieved)
        self.fact = {
            "fact_id": "first", "symbol": "600000.SS", "metric": "revenue", "period_end": "2025-12-31", "valuation_date": "2025-12-31", "unit": "CNY", "scale": 1000000, "value": 100,
            "revision": "original", "supersedes_fact_id": None, "source_type": "filing", "source_tier": "exchange",
            "source_locator": receipt["source_locator"], "content_sha256": receipt["content_sha256"], "timing_contract_version": "1.0",
            "publication_precision": "unknown", "published_at": None, "publication_date": None, "publication_utc_offset": None,
            "availability_observed_at": observed, "retrieved_at": retrieved, "source_capture_receipt": receipt,
        }
        self.package = {"schema_version": VERSION, "instrument": {"symbol": "600000.SS", "market": "CN", "asset_type": "stock"}, "cutoff_at": now.isoformat(), "facts": [self.fact]}

    def test_reverified_original_and_correction(self):
        correction = copy.deepcopy(self.fact)
        correction.update(fact_id="second", value=120, revision="correction", supersedes_fact_id="first")
        correction["availability_observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        correction["retrieved_at"] = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        correction["source_capture_receipt"] = verify_source_capture(self.raw, source_locator=correction["source_locator"], availability_observed_at=correction["availability_observed_at"], retrieved_at=correction["retrieved_at"])
        self.package["facts"].append(correction)
        result = evaluate(self.package, verify_raw=True)
        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(result["selected_facts"][0]["value"], 120)

    def test_no_implicit_raw_read_and_missing_capture_fails_closed(self):
        self.raw.unlink()
        self.assertEqual(evaluate(self.package)["status"], "insufficient_evidence")
        self.assertEqual(evaluate(self.package, verify_raw=True)["status"], "invalid_input")

    def test_conflict_and_future_capture_fail_closed(self):
        duplicate = copy.deepcopy(self.fact)
        duplicate["fact_id"] = "parallel"
        self.package["facts"].append(duplicate)
        self.assertEqual(evaluate(self.package, verify_raw=True)["status"], "invalid_input")
        self.package["facts"].pop()
        self.package["facts"][0]["availability_observed_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        self.assertEqual(evaluate(self.package, verify_raw=True)["status"], "invalid_input")

    def test_cli_requires_explicit_raw_authorization(self):
        package_path = Path(self.temp.name) / "package.json"
        package_path.write_text(json.dumps(self.package), encoding="utf-8")
        base = [sys.executable, "-B", str(HERE / "cn_filing_facts.py"), str(package_path)]
        unverified = subprocess.run(base, capture_output=True, text=True, timeout=10)
        self.assertEqual(unverified.returncode, 2)
        self.assertEqual(json.loads(unverified.stdout)["selected_facts"], [])
        verified = subprocess.run([*base, "--verify-raw"], capture_output=True, text=True, timeout=10)
        self.assertEqual(verified.returncode, 0, verified.stdout)
        self.assertEqual(json.loads(verified.stdout)["selected_facts"][0]["scale"], 1000000)

    def test_noncanonical_exchange_suffix_fails_closed(self):
        self.package["instrument"]["symbol"] = "600000.SH"
        self.package["facts"][0]["symbol"] = "600000.SH"
        self.assertEqual(evaluate(self.package, verify_raw=True)["status"], "invalid_input")

    def test_wrong_issuer_fails_closed(self):
        self.package["facts"][0]["symbol"] = "000001.SZ"
        self.assertEqual(evaluate(self.package, verify_raw=True)["status"], "invalid_input")

    def test_invalid_numeric_and_orphan_revision_fail_closed(self):
        self.package["facts"][0]["value"] = float("nan")
        self.assertEqual(evaluate(self.package)["status"], "invalid_input")
        self.package["facts"][0]["value"] = 100
        self.package["facts"][0]["revision"] = "correction"
        self.package["facts"][0]["supersedes_fact_id"] = "missing"
        self.assertEqual(evaluate(self.package)["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
