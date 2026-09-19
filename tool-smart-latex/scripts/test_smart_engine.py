"""Behaviour tests for smart_engine.py.

These tests check what the engine does, not only what its documentation says:
command construction, language routing, style detection, multi-pass compilation
and failure handling.
"""

import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("smart_engine.py")
SPEC = importlib.util.spec_from_file_location("smart_engine", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
smart_engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smart_engine)

TEMPLATES = SCRIPT_PATH.parent.parent / "templates"
STYLES = ["academic", "book", "tech_book", "tech_report", "cv"]


def write_png(path, width=16, height=16, rgba=(200, 30, 30, 255)):
    """Write a real PNG: ad-hoc base64 fixtures often carry broken CRCs."""
    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def command_for(style, **options):
    return smart_engine.build_pandoc_command(
        "input.md", TEMPLATES / f"{style}.tex", "out/doc.tex", style, None, None, **options
    )


class CommandConstructionTests(unittest.TestCase):
    def test_tech_report_conversion_uses_listings(self):
        command = command_for("tech_report")
        self.assertIn("--listings", command)
        self.assertNotIn("abstract=", command)
        self.assertIn("-M", command)
        self.assertIn("cjk=false", command)

    def test_language_switch_is_always_explicit(self):
        self.assertIn("cjk=true", command_for("tech_report", cjk=True))
        self.assertIn("cjk=false", command_for("academic", cjk=False))

    def test_chapter_division_only_for_book_styles(self):
        for style in ("book", "tech_book"):
            with self.subTest(style=style):
                self.assertIn("--top-level-division=chapter", command_for(style))
        for style in ("academic", "tech_report", "cv"):
            with self.subTest(style=style):
                self.assertFalse(
                    [a for a in command_for(style) if a.startswith("--top-level-division")]
                )
        self.assertIn(
            "--top-level-division=section",
            command_for("book", top_level_division="section"),
        )

    def test_media_is_extracted_to_a_relative_directory(self):
        command = command_for("tech_report")
        index = command.index("--extract-media")
        self.assertEqual(command[index + 1], "media")
        self.assertFalse(Path(command[index + 1]).is_absolute())
        self.assertEqual(command[command.index("-o") + 1], "doc.tex")

    def test_numbering_and_leading_flags(self):
        self.assertIn("--number-sections", command_for("tech_report", number_sections=True))
        self.assertNotIn("--number-sections", command_for("tech_report", number_sections=False))
        self.assertIn("linespread=1.4", command_for("tech_report", linespread=1.4))
        self.assertIn("secnumdepth=2", command_for("tech_report", secnumdepth=2))

    def test_citations_require_a_bibliography(self):
        self.assertFalse([a for a in command_for("academic") if a.startswith("--citeproc")])
        command = command_for("academic", bibliography="refs.bib", csl="gb.csl")
        self.assertIn("--citeproc", command)
        self.assertIn("--bibliography=refs.bib", command)
        self.assertIn("--csl=gb.csl", command)

    def test_two_column_table_filter_only_for_academic(self):
        self.assertTrue(any("twocol_table.lua" in a for a in command_for("academic")))
        for style in ("book", "tech_book", "tech_report", "cv"):
            with self.subTest(style=style):
                self.assertFalse(any("twocol_table.lua" in a for a in command_for(style)))

    def test_box_filter_matches_the_style_mapping(self):
        for style, expected in (
            ("book", "definition:definitionBox"),
            ("tech_book", "note:techNote"),
            ("tech_report", "tip:tipBox"),
        ):
            with self.subTest(style=style):
                command = command_for(style)
                self.assertTrue(any("div_boxes.lua" in a for a in command))
                self.assertIn(f"boxes={smart_engine.BOX_MAPS[style]}", command)
                self.assertIn(expected, smart_engine.BOX_MAPS[style])
        for style in ("academic", "cv"):
            with self.subTest(style=style):
                self.assertFalse(any("div_boxes.lua" in a for a in command_for(style)))


class LanguageDetectionTests(unittest.TestCase):
    def test_chinese_and_english_documents(self):
        self.assertEqual(smart_engine.detect_language("这是一段中文正文，用于判定语言。" * 20), "zh")
        self.assertEqual(smart_engine.detect_language("This is an English body. " * 20), "en")

    def test_code_does_not_decide_the_language(self):
        body = "This is an English body.\n\n```python\n中文注释 = 'x'\n```\n" * 5
        self.assertEqual(smart_engine.detect_language(body), "en")

    def test_english_document_quoting_chinese_stays_english(self):
        body = "The report says 高质量发展 once, in a long English paragraph. " * 20
        self.assertEqual(smart_engine.detect_language(body), "en")

    def test_explicit_request_and_front_matter_win(self):
        chinese = "这是一段中文正文。" * 20
        self.assertEqual(smart_engine.detect_language(chinese, "en"), "en")
        declared = "---\nlang: en-US\n---\n\n" + chinese
        self.assertEqual(smart_engine.detect_language(declared), "en")
        self.assertEqual(smart_engine.frontmatter_lang(declared), "en-US")
        self.assertIsNone(smart_engine.frontmatter_lang("no front matter"))

    def test_empty_input_defaults_to_english(self):
        self.assertEqual(smart_engine.detect_language(""), "en")


class StyleDetectionTests(unittest.TestCase):
    def detect(self, text, name="doc.md"):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / name
            source.write_text(text, encoding="utf-8")
            return smart_engine.detect_style(str(source))

    def test_keywords_match_whole_words_only(self):
        # "comfortable"/"capital"/"format" are not academic or tech_report signals.
        self.assertEqual(self.detect("A comfortable and suitable capital format. " * 5), "tech_report")

    def test_no_signal_falls_back_to_tech_report(self):
        self.assertEqual(self.detect("Lorem ipsum dolor sit amet. " * 5), "tech_report")

    def test_ties_resolve_deterministically(self):
        # One academic and one tech_report keyword: the priority list decides.
        self.assertEqual(self.detect("Abstract. api. " * 3), "academic")

    def test_fence_bonus_applies_to_markdown_sources(self):
        # No style keyword at all: the fence bonus alone decides, and it only
        # applies to text-like sources.
        body = "A neutral note about nothing in particular.\n\n```text\nx = 1\n```\n" * 3
        self.assertEqual(self.detect(body, "doc.markdown"), "tech_book")
        self.assertEqual(self.detect(body, "doc.docx"), "tech_report")


class CompileTests(unittest.TestCase):
    def test_compile_disables_shell_escape_and_uses_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text("test", encoding="utf-8")

            with patch.object(smart_engine.subprocess, "run") as run_mock:
                self.assertTrue(smart_engine.compile_tex(tex_path))

            options = run_mock.call_args.kwargs
            command = run_mock.call_args.args[0]
            self.assertIn("-no-shell-escape", command)
            self.assertNotIn("-shell-escape", command)
            self.assertEqual(command[-1], "sample.tex")
            self.assertEqual(options["cwd"], str(tex_path.parent.resolve()))
            self.assertEqual(options["timeout"], 40)

    def test_compiles_again_only_when_the_log_asks_for_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text("test", encoding="utf-8")
            log = tex_path.with_suffix(".log")

            def clean_pass(*_args, **_kwargs):
                log.write_text("Output written on sample.pdf", encoding="utf-8")

            with patch.object(smart_engine.subprocess, "run", side_effect=clean_pass) as run_mock:
                self.assertTrue(smart_engine.compile_tex(tex_path))
                self.assertEqual(run_mock.call_count, 1)

            def rerun_pass(*_args, **_kwargs):
                log.write_text("Rerun to get cross-references right.", encoding="utf-8")

            with patch.object(smart_engine.subprocess, "run", side_effect=rerun_pass) as run_mock:
                self.assertTrue(smart_engine.compile_tex(tex_path))
                self.assertEqual(run_mock.call_count, smart_engine.MAX_LATEX_PASSES)

    def test_failed_compile_quarantines_the_partial_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "sample.tex"
            tex_path.write_text("test", encoding="utf-8")
            pdf = tex_path.with_suffix(".pdf")

            def failing_run(*_args, **_kwargs):
                # xelatex writes a truncated PDF before it stops.
                pdf.write_bytes(b"%PDF-1.4 truncated")
                raise subprocess.CalledProcessError(1, ["xelatex"], stderr="compile failed")

            with patch.object(smart_engine.subprocess, "run", side_effect=failing_run):
                self.assertFalse(smart_engine.compile_tex(tex_path))

            self.assertFalse(pdf.exists())
            self.assertTrue((Path(temp_dir) / "sample.INCOMPLETE.pdf").exists())

    def test_stale_artifacts_are_removed_but_not_the_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tex_path = Path(temp_dir) / "doc.tex"
            tex_path.write_text("test", encoding="utf-8")
            stale = [tex_path.parent / ("doc" + suffix) for suffix in (".aux", ".pdf", ".toc")]
            for path in stale:
                path.write_bytes(b"stale")
            smart_engine.clean_previous_outputs(tex_path)
            self.assertEqual([p for p in stale if p.exists()], [])
            self.assertTrue(tex_path.exists())

    def test_error_report_includes_the_offending_line(self):
        log = (
            "This is xelatex output\n"
            "! Undefined control sequence.\n"
            "l.104 \\undefinedcommand\n"
            "                 here\n"
            "more output\n"
        )
        report = smart_engine.format_latex_error(log)
        self.assertIn("Undefined control sequence", report)
        self.assertIn("l.104", report)

    def test_error_report_falls_back_to_diagnostics_without_a_bang_line(self):
        log = "libpng error: IDAT: CRC error\nHere is how much of TeX's memory you used:\n"
        report = smart_engine.format_latex_error(log)
        self.assertIn("libpng error", report)
        self.assertNotIn("memory", report)

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


class MainTests(unittest.TestCase):
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

    def test_main_routes_a_chinese_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.md"
            source.write_text("这是一段中文正文。" * 30, encoding="utf-8")
            with (
                patch.object(
                    smart_engine.sys,
                    "argv",
                    ["engine", "--input", str(source), "--style", "tech_report"],
                ),
                patch.object(smart_engine, "convert_and_compile") as convert,
                patch.object(smart_engine, "compile_tex", return_value=True),
            ):
                smart_engine.main()
                self.assertTrue(convert.call_args.kwargs["cjk"])

    def test_main_reports_a_missing_input(self):
        with patch.object(smart_engine.sys, "argv", ["engine", "--input", "does-not-exist.md"]):
            with self.assertRaises(SystemExit) as result:
                smart_engine.main()
            self.assertEqual(result.exception.code, 1)


class TemplateContractTests(unittest.TestCase):
    def test_every_template_carries_the_pandoc_prelude(self):
        required = (
            r"\providecommand{\tightlist}",
            r"\providecommand{\passthrough}",
            r"\newcounter{none}",
            r"\providecommand*\pandocbounded",
            "CSLReferences",
            "secnumdepth",
        )
        for style in STYLES:
            template = (TEMPLATES / f"{style}.tex").read_text(encoding="utf-8")
            for literal in required:
                with self.subTest(style=style, literal=literal):
                    self.assertIn(literal, template)

    def test_every_template_routes_the_language(self):
        for style in STYLES:
            template = (TEMPLATES / f"{style}.tex").read_text(encoding="utf-8")
            with self.subTest(style=style):
                self.assertIn("scheme=chinese", template)
                self.assertIn("scheme=plain", template)
                self.assertIn("$if(cjk)$", template)
                self.assertIn("ragged2e", template)

    def test_academic_clears_the_newtx_font_feature_leak(self):
        template = (TEMPLATES / "academic.tex").read_text(encoding="utf-8")
        self.assertIn("newtxtext", template)
        self.assertIn(r"\defaultfontfeatures{}", template)


class RealPandocTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc not installed")
    def test_real_pandoc_academic_abstract_independent_of_title(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.md"
            output = Path(directory) / "output.tex"
            template = TEMPLATES / "academic.tex"
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
                    source.write_text(metadata + "---\n\nBodySentinel\n", encoding="utf-8")
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
            write_png(image)
            source = source_dir / "input.md"
            source.write_text(
                "---\ntitle: OriginalTitle\nauthor: OriginalAuthor\ndate: OriginalDate\n"
                "abstract: AbstractSentinel 中文摘要\n---\n\nBodySentinel 中文正文\n\n"
                "![](pixel.png)\n",
                encoding="utf-8",
            )
            for style in ("academic", "tech_report"):
                with self.subTest(style=style):
                    output = output_dir / f"{style}.tex"
                    template = TEMPLATES / f"{style}.tex"
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
                    # Media references stay relative so the directory can move.
                    self.assertIn("media/pixel.png", text)
                    extracted = list((output_dir / "media").rglob("*.png"))
                    self.assertTrue(extracted)
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


class RealCompileTests(unittest.TestCase):
    """End-to-end checks that need a full LaTeX installation."""

    HARNESS = (
        "---\ntitle: Harness\nauthor: A\n---\n\n# Section\n\nBody 中文正文 text.\n\n"
        "| A | B |\n|:--|--:|\n| 1 | 2 |\n\n```python\nprint('x')\n```\n\n"
        "Inline `code` and ![](pixel.png)\n"
    )

    @unittest.skipUnless(shutil.which("pandoc") and shutil.which("xelatex"), "toolchain missing")
    def test_every_style_compiles_a_mixed_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_png(root / "pixel.png")
            source = root / "harness.md"
            source.write_text(self.HARNESS, encoding="utf-8")
            for style in STYLES:
                with self.subTest(style=style):
                    out = root / style
                    out.mkdir()
                    result = subprocess.run(
                        [
                            "python", str(SCRIPT_PATH),
                            "--input", str(source), "--style", style, "--output", str(out),
                        ],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=300,
                    )
                    pdf = list(out.glob("*.pdf"))
                    self.assertEqual(result.returncode, 0, result.stdout[-800:])
                    self.assertTrue(pdf, result.stdout[-800:])


class IdiomHelperTests(unittest.TestCase):
    def helper(self):
        spec = importlib.util.spec_from_file_location(
            "process_idioms", SCRIPT_PATH.with_name("process_idioms.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_numeric_data_survives_while_audio_markers_are_removed(self):
        idioms = self.helper()
        cleaned = idioms.clean_text("Kept 1234.5 and 2020.1 but not 048.1 ")
        self.assertIn("1234.5", cleaned)
        self.assertIn("2020.1", cleaned)
        self.assertNotIn("048.1", cleaned)

    def test_quotes_become_typographic(self):
        idioms = self.helper()
        self.assertEqual(idioms.clean_text('He said "hello" softly.'), "He said “hello” softly.")
        self.assertIn("’", idioms.clean_text(r"O\textquotesingle Reilly"))

    def test_entries_parse_without_double_items(self):
        idioms = self.helper()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "intermediate.tex"
            source.write_text(
                "\\section{48. A sweet tooth}\n\n\\textbf{释义}\n\nGloss text.\n\n"
                "\\textbf{例句}\n\n\\begin{itemize}\n\\item \\item An example.\n\\end{itemize}\n",
                encoding="utf-8",
            )
            parsed = idioms.parse_tex(str(source))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["id"], "48")
            self.assertEqual(parsed[0]["term"], "A sweet tooth")
            self.assertEqual(parsed[0]["definition"], ["Gloss text."])
            self.assertEqual(parsed[0]["examples"], ["An example."])
            self.assertEqual(idioms.as_list_item("An example."), "\\item An example.")
            self.assertEqual(idioms.as_list_item("\\item An example."), "\\item An example.")


if __name__ == "__main__":
    unittest.main()
