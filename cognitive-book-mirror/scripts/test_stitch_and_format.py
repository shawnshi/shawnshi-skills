import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stitch_and_format.py")


class StitchAndFormatTests(unittest.TestCase):
    def run_stitch(self, results_dir: Path, output: Path):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--results-dir",
                str(results_dir),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_sequence_must_start_at_one(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            results = root / "results"
            results.mkdir()
            (results / "result_2.md").write_text("second", encoding="utf-8")
            (results / "result_3.md").write_text("third", encoding="utf-8")

            outcome = self.run_stitch(results, root / "output.md")

            self.assertEqual(outcome.returncode, 1)
            self.assertIn("expected contiguous sequence [1, 2, 3]", outcome.stdout)
            self.assertFalse((root / "output.md").exists())

    def test_literal_template_syntax_is_valid_content(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            results = root / "results"
            results.mkdir()
            literal = "Documentation example: {{field}} and <TBD> are quoted source text."
            (results / "result_1.md").write_text(literal, encoding="utf-8")
            output = root / "output.md"

            outcome = self.run_stitch(results, output)

            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            self.assertIn(literal, output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
