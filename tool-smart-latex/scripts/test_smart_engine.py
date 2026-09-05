import base64
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("smart_engine.py")
SPEC = importlib.util.spec_from_file_location("smart_engine", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
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
        self.assertNotIn("abstract=", command)
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 60)

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
            self.assertEqual(options["timeout"], 40)

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
        template = (
            SCRIPT_PATH.parent.parent / "templates" / "tech_report.tex"
        ).read_text(encoding="utf-8")
        self.assertNotIn("minted", template)
        self.assertIn("\\usepackage{listings}", template)
        self.assertIn("\\newcounter{none}", template)

    def test_missing_tools_and_timeouts_are_explicit(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("tool", 60)):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(smart_engine.subprocess, "run", side_effect=error),
            ):
                with self.assertRaises(SystemExit) as result:
                    smart_engine.convert_and_compile(
                        "in.md", "t.tex", "out.tex", "academic", None, None
                    )
                self.assertEqual(result.exception.code, 1)
                self.assertFalse(smart_engine.compile_tex("out.tex"))

    def test_main_preserves_metadata_without_cli_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.md"
            source.write_text("synthetic", encoding="utf-8")
            with (
                patch.object(
                    smart_engine.sys,
                    "argv",
                    ["engine", "--input", str(source), "--style", "academic"],
                ),
                patch.object(smart_engine, "convert_and_compile") as convert,
                patch.object(smart_engine, "compile_tex", return_value=True),
            ):
                smart_engine.main()
                self.assertEqual(convert.call_args.args[-2:], (None, None))

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc not installed")
    def test_real_pandoc_academic_abstract_independent_of_title(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.md"
            output = Path(directory) / "output.tex"
            template = SCRIPT_PATH.parent.parent / "templates" / "academic.tex"
            for has_title, has_abstract in (
                (False, True),
                (True, True),
                (True, False),
                (False, False),
            ):
                with self.subTest(title=has_title, abstract=has_abstract):
                    metadata = "---\nauthor: SyntheticAuthor\n"
                    if has_title:
                        metadata += "title: TitleSentinel\n"
                    if has_abstract:
                        metadata += "abstract: AbstractSentinel\n"
                    source.write_text(
                        metadata + "---\n\nBodySentinel\n", encoding="utf-8"
                    )
                    smart_engine.convert_and_compile(
                        str(source), str(template), str(output), "academic", None, None
                    )
                    text = output.read_text(encoding="utf-8")
                    self.assertIn("BodySentinel", text)
                    self.assertEqual("AbstractSentinel" in text, has_abstract)
                    self.assertEqual("\\begin{abstract}" in text, has_abstract)
                    self.assertEqual("\\maketitle" in text, has_title)
                    self.assertEqual("TitleSentinel" in text, has_title)
                    self.assertEqual("\\twocolumn[" in text, has_title or has_abstract)

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc not installed")
    def test_real_pandoc_preserves_metadata_body_and_output_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            source_dir.mkdir()
            output_dir = root / "output"
            output_dir.mkdir()
            image = source_dir / "pixel.png"
            image.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
                )
            )
            source = source_dir / "input.md"
            source.write_text(
                "---\ntitle: OriginalTitle\nauthor: OriginalAuthor\ndate: OriginalDate\nabstract: AbstractSentinel 中文摘要\n---\n\nBodySentinel 中文正文\n\n![](pixel.png)\n",
                encoding="utf-8",
            )
            for style in ("academic", "tech_report"):
                with self.subTest(style=style):
                    output = output_dir / f"{style}.tex"
                    template = SCRIPT_PATH.parent.parent / "templates" / f"{style}.tex"
                    smart_engine.convert_and_compile(
                        str(source), str(template), str(output), style, None, None
                    )
                    text = output.read_text(encoding="utf-8")
                    for sentinel in (
                        "OriginalTitle",
                        "OriginalAuthor",
                        "OriginalDate",
                        "AbstractSentinel",
                        "中文摘要",
                        "BodySentinel",
                        "中文正文",
                    ):
                        self.assertIn(sentinel, text)
                    extracted = list((output_dir / "media").rglob("*.png"))
                    self.assertTrue(extracted)
                    self.assertTrue(any(p.as_posix() in text for p in extracted))
                    self.assertEqual(extracted[0].read_bytes(), image.read_bytes())
                    smart_engine.convert_and_compile(
                        str(source),
                        str(template),
                        str(output),
                        style,
                        "OverrideTitle",
                        "OverrideAuthor",
                    )
                    text = output.read_text(encoding="utf-8")
                    for sentinel in (
                        "OverrideTitle",
                        "OverrideAuthor",
                        "AbstractSentinel",
                        "BodySentinel",
                    ):
                        self.assertIn(sentinel, text)
                    self.assertNotIn("OriginalTitle", text)


if __name__ == "__main__":
    unittest.main()
