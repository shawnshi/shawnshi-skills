"""Read-only CLI contract and task-specific regressions; synthetic fixtures only."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_industry_radar.py"


class RuntimeContractTests(unittest.TestCase):
    def test_describe_contract_is_read_only_json(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPT), "--describe-contract"],
                                    cwd=td, capture_output=True, encoding="utf-8", timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("hit-industry-radar", value["skill"])
            self.assertEqual(1, value["schema_version"])
            self.assertTrue(value["read_only"])
            self.assertTrue(value["tables"])
            self.assertEqual([], list(Path(td).iterdir()))

    def test_describe_cannot_mix_with_validation_arguments(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--describe-contract", "--file", "missing.md"],
                                capture_output=True, timeout=10)
        self.assertEqual(2, result.returncode)


    def test_headers_match_schema_document(self):
        import validate_industry_radar as gate
        doc = (ROOT / "references/report_schema.md").read_text(encoding="utf-8")
        for header in gate.HEADERS.values():
            self.assertIn("| " + " | ".join(header) + " |", doc)
        self.assertEqual(",", gate.describe_contract()["source_reference_separator"])


if __name__ == "__main__":
    unittest.main()
