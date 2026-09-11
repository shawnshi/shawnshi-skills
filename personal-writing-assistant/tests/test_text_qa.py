"""Synthetic CLI regressions for text_qa; no real drafts or network access."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "text_qa.py"


class TextQaCliTests(unittest.TestCase):
    def run_cli(self, text, suffix=".md", extra=(), raw=None):
        with tempfile.TemporaryDirectory(prefix="text-qa-test-") as directory:
            path = Path(directory) / ("draft" + suffix)
            path.write_bytes(raw if raw is not None else text.encode("utf-8"))
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    str(path),
                    "--mode",
                    "publish",
                    "--json",
                    *extra,
                ],
                capture_output=True,
                encoding="utf-8",
                check=False,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        return result

    def check_report(self, text, expected_exit, code=None, line=None, **kwargs):
        result = self.run_cli(text, **kwargs)
        self.assertEqual(
            result.returncode, expected_exit, result.stdout + result.stderr
        )
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["exit_code"], expected_exit)
        self.assertEqual(report["status"], "blocked" if expected_exit else "pass")
        if code:
            finding = next(item for item in report["findings"] if item["code"] == code)
            if line is not None:
                self.assertIn(line, [item["line"] for item in finding["examples"]])
        return report

    def test_original_six_audit_cases(self):
        cases = [
            ("txt-inline", "`TODO`", ".txt", 2, "UNRESOLVED_PLACEHOLDER", 1),
            (
                "long-fence",
                "````\n```\n````\nTODO",
                ".md",
                2,
                "UNRESOLVED_PLACEHOLDER",
                4,
            ),
            (
                "inline-not-fence",
                "```x```\nTODO",
                ".md",
                2,
                "UNRESOLVED_PLACEHOLDER",
                2,
            ),
            (
                "prohibition",
                "不得采用未经核实的数据。",
                ".md",
                0,
                "PENDING_VERIFICATION",
                1,
            ),
            ("body", "TODO", ".md", 2, "UNRESOLVED_PLACEHOLDER", 1),
            (
                "longer-tilde-close",
                "~~~\nTODO\n~~~~\nTODO",
                ".md",
                2,
                "UNRESOLVED_PLACEHOLDER",
                4,
            ),
        ]
        for name, text, suffix, exit_code, code, line in cases:
            with self.subTest(name=name):
                self.check_report(text, exit_code, code, line, suffix=suffix)

    def test_fence_and_list_boundaries(self):
        cases = [
            ("````\nTODO\n```\nTODO\n````\nTODO", 6),
            ("```\nTODO\n``` trailing\nTODO\n```\nTODO", 6),
            ("~~~\n```\nTODO\n~~~\nTODO", 5),
            ("- ```\n  TODO\n  ```\nTODO", 4),
            ("- ```\n  TODO\nTODO", 3),
            ("1. item\n   ```\n   TODO\nTODO", 4),
            ("- outer\n  - ```\n    TODO\n  TODO", 4),
            ("- item\n\n    TODO", 3),
            ("- ```\n  TODO\n- TODO", 3),
            ("-     ```\nTODO", 2),
            ("```x`invalid\nTODO", 2),
            ("    ```\nTODO", 2),
        ]
        for text, line in cases:
            with self.subTest(text=text):
                self.check_report(text, 2, "UNRESOLVED_PLACEHOLDER", line)

    def test_valid_code_stays_masked(self):
        for text in (
            "```python\nTODO\n```",
            "~~~\nTODO\n~~~~",
            "`TODO`",
            "``TODO ` x``",
            "```TODO```",
            "- ```\n  TODO\n  ```",
            "`code\nTODO`",
            "``code ` TODO``",
        ):
            with self.subTest(text=text):
                self.check_report(text, 0)

    def test_inline_delimiter_length_escape_and_paragraph_boundary(self):
        for text, line in (
            ("`TODO``", 1),
            ("\\`TODO`", 1),
            ("`code\n\nTODO`", 3),
            ("`code\n# TODO`", 2),
            ("`code\n- TODO`", 2),
        ):
            with self.subTest(text=text):
                self.check_report(text, 2, "UNRESOLVED_PLACEHOLDER", line)

    def test_inline_code_stops_at_setext_boundary(self):
        for underline in (
            "=",
            "==",
            "===",
            "-",
            "--",
            "---",
            " ===",
            "   --",
            "=== \t",
            "-- \t",
        ):
            with self.subTest(underline=underline):
                self.check_report(
                    f"`code\n{underline}\nTODO`", 2, "UNRESOLVED_PLACEHOLDER", 3
                )
        for text in ("`code\r\n===\r\nTODO`", "- `code\n  ===\n  TODO`"):
            with self.subTest(text=text):
                self.check_report(text, 2, "UNRESOLVED_PLACEHOLDER", 3)

    def test_setext_inline_code_positive_controls(self):
        for text in (
            "`code\nTODO`",
            "`TODO`\n===",
            "`TODO`\n--",
            "title\n===\n`code\nTODO`",
            "title\n--\n`code\nTODO`",
            "`code\n= =\nTODO`",
            "`code\n=== text\nTODO`",
            "`code\n--x\nTODO`",
            "`code\n=-\nTODO`",
        ):
            with self.subTest(text=text):
                self.check_report(text, 0)

    def test_txt_does_not_mask_fences(self):
        self.check_report(
            "```\nTODO\n```", 2, "UNRESOLVED_PLACEHOLDER", 2, suffix=".txt"
        )

    def test_explicit_pending_blocks_but_prose_is_review_clue(self):
        for text in (
            "本项目节省金额【待核实】。",
            "数据[待确认]",
            "<来源待补>",
            "待核实：节省金额",
            "- [ ] 待核验节省金额",
            "- 待核实：节省金额",
        ):
            with self.subTest(text=text):
                report = self.check_report(text, 2, "EXPLICIT_PENDING_VERIFICATION", 1)
                self.assertEqual(report["summary"]["blocker_categories"], 1)
        report = self.check_report(
            "不得采用未经核实的数据。\n本项目节省金额【待核实】。",
            2,
            "EXPLICIT_PENDING_VERIFICATION",
            2,
        )
        clue = next(
            item
            for item in report["findings"]
            if item["code"] == "PENDING_VERIFICATION"
        )
        self.assertEqual(clue["severity"], "warning")
        self.check_report(
            "不得采用未经核实的数据。\nTODO", 2, "UNRESOLVED_PLACEHOLDER", 2
        )

    def test_page_source_and_conditional_links(self):
        text = "依据《合成示例文件》第 12 页。"
        self.check_report(text, 0)
        self.check_report(text, 2, "REQUIRED_LINKS_MISSING", extra=("--require-links",))
        self.check_report(
            text + " https://example.invalid/source", 0, extra=("--require-links",)
        )
        self.check_report(
            "`https://example.invalid/source`",
            2,
            "REQUIRED_LINKS_MISSING",
            extra=("--require-links",),
        )

    def test_empty_bom_and_invalid_encoding(self):
        self.check_report("", 2, "EMPTY_DOCUMENT")
        self.check_report("", 2, "EMPTY_DOCUMENT", raw=b"\xef\xbb\xbf")
        self.check_report("", 2, "UNRESOLVED_PLACEHOLDER", 1, raw=b"\xef\xbb\xbfTODO")
        report = self.check_report("", 2, "INVALID_ENCODING", raw=b"\xff\xfe\x00")
        self.assertIsNone(report["stats"])

    def test_parameter_conflicts(self):
        for extra in (
            ("--min-chars", "10", "--max-chars", "1"),
            ("--min-chars", "-1"),
            ("--mode", "invalid"),
        ):
            with self.subTest(extra=extra):
                result = self.run_cli("正文", extra=extra)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)

    def test_existing_rules_and_modes(self):
        self.check_report("正文", 2, "BELOW_MIN_CHARS", extra=("--min-chars", "3"))
        self.check_report("正文", 2, "ABOVE_MAX_CHARS", extra=("--max-chars", "1"))
        self.check_report("正文", 2, "UNSUPPORTED_FILE_TYPE", suffix=".csv")
        self.check_report(
            "【待核实】",
            0,
            "EXPLICIT_PENDING_VERIFICATION",
            extra=("--mode", "research"),
        )
        self.check_report(
            "【待核实】", 0, "EXPLICIT_PENDING_VERIFICATION", extra=("--mode", "light")
        )
        text = "众所周知，零风险。" + "合成内容" * 30
        report = self.check_report(text + "\n\n" + text, 0)
        self.assertTrue(
            {"AI_CLICHE", "OVER_CERTAINTY", "DUPLICATE_LONG_PARAGRAPH"}.issubset(
                {item["code"] for item in report["findings"]}
            )
        )


if __name__ == "__main__":
    unittest.main()
