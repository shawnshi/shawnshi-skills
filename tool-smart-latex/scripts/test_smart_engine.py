import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).with_name("smart_engine.py")
SPEC = importlib.util.spec_from_file_location("smart_engine", SCRIPT_PATH)
smart_engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smart_engine)


class SmartEngineTests(unittest.TestCase):
    @patch.object(smart_engine.subprocess, "run")
    def test_tech_report_conversion_uses_listings(self, run_mock):
        self.assertTrue(
            smart_engine.convert_and_compile(
                "input.md", "template.tex", "output.tex", "tech_report", None, None
            )
        )
        command = run_mock.call_args.args[0]
        self.assertIn("--listings", command)

    @patch.object(smart_engine.subprocess, "run")
    def test_compile_disables_shell_escape_and_uses_output_directory(self, run_mock):
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text("test", encoding="utf-8")

            self.assertTrue(smart_engine.compile_tex(tex_path))

            self.assertEqual(run_mock.call_count, 2)
            command = run_mock.call_args.args[0]
            options = run_mock.call_args.kwargs
            self.assertIn("-no-shell-escape", command)
            self.assertNotIn("-shell-escape", command)
            self.assertEqual(command[-1], "sample.tex")
            self.assertEqual(options["cwd"], str(tex_path.parent.resolve()))

    @patch.object(smart_engine.subprocess, "run")
    def test_compile_failure_is_reported(self, run_mock):
        run_mock.side_effect = subprocess.CalledProcessError(
            1, ["xelatex"], stderr="compile failed"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text("test", encoding="utf-8")
            self.assertFalse(smart_engine.compile_tex(tex_path))

    def test_tech_report_template_has_no_minted_dependency(self):
        template = (SCRIPT_PATH.parent.parent / "templates" / "tech_report.tex").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("minted", template)
        self.assertIn("\\usepackage{listings}", template)
        self.assertIn("\\newcounter{none}", template)


if __name__ == "__main__":
    unittest.main()
