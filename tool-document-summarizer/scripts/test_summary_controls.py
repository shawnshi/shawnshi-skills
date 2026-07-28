import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("generate_summaries_enhanced.py")
ORCHESTRATOR = Path(__file__).with_name("orchestrate_enhanced.py")
sys.path.insert(0, str(Path(__file__).parent))
from apply_metadata_enhanced import load_inputs


class SummaryControlTests(unittest.TestCase):
    def test_literal_template_syntax_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "documents.json"
            output = root / "summaries.json"
            literal = "接口文档示例保留 {{patient_id}} 与 <TBD> 的字面说明。"
            source.write_text(
                json.dumps(
                    [{"id": "doc-1", "filename": "example.txt", "content": literal}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            outcome = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--max-chars",
                    "200",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["summary"], literal)

    def test_summary_length_has_no_silent_default(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "documents.json"
            source.write_text("[]", encoding="utf-8")

            outcome = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(root / "summaries.json"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(outcome.returncode, 2)
            self.assertIn("--max-chars", outcome.stderr)

    def test_external_use_requires_explicit_data_boundary(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source = root / "documents.json"
            source.write_text("[]", encoding="utf-8")

            outcome = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(root / "summaries.json"),
                    "--max-chars",
                    "200",
                    "--allow-external-model",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(outcome.returncode, 2)
            self.assertIn("--external-max-chars", outcome.stderr)

    def test_metadata_preview_accepts_literal_template_syntax(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_file = root / "source.pdf"
            source_file.write_bytes(b"fixture")
            summaries = root / "summaries.json"
            mapping = root / "mapping.json"
            literal = "Literal source syntax: {{patient_id}} and <TBD>."
            summaries.write_text(
                json.dumps(
                    [{"id": "doc-1", "summary": literal, "tags": ["template"]}]
                ),
                encoding="utf-8",
            )
            mapping.write_text(
                json.dumps({"doc-1": str(source_file)}),
                encoding="utf-8",
            )

            proposed = load_inputs(summaries, mapping)

            self.assertEqual(proposed[0]["summary"], literal)

    def test_all_pipeline_is_read_only_and_uses_explicit_length(self):
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            source_dir = root / "source"
            output_dir = root / "output"
            source_dir.mkdir()
            source = source_dir / "brief.txt"
            source.write_text(
                "第一段记录可核验事实与日期。\n\n第二段记录限制和待核验问题。",
                encoding="utf-8",
            )
            before = hashlib.sha256(source.read_bytes()).hexdigest()

            outcome = subprocess.run(
                [
                    sys.executable,
                    str(ORCHESTRATOR),
                    "all",
                    "--dir",
                    str(source_dir),
                    "--output-dir",
                    str(output_dir),
                    "--workers",
                    "1",
                    "--max-chars",
                    "200",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            for name in (
                "extracted_content.json",
                "file_id_mapping.json",
                "document_summaries.json",
                "term_locations.json",
                "portfolio_inventory.json",
            ):
                self.assertTrue((output_dir / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
