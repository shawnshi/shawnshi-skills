from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.common import SCRIPTS, SKILL_ROOT, load_module, run_python

validator = load_module("validate_outputs", SCRIPTS / "validate_outputs.py")
checker = load_module("draft_preflight", SCRIPTS / "check_briefing_draft.py")


def marked(body: str) -> str:
    return "<!-- briefing:start -->\n" + body + "\n<!-- briefing:end -->"


class DraftPreflightTests(unittest.TestCase):
    def test_valid_four_digit_reference_is_shape_only(self):
        result = checker.check(marked("合成事实 CLM-I-1000；判断待核实。"))
        self.assertEqual(result["claim_ids"], ["CLM-I-1000"])
        self.assertEqual(result["scope"], "draft_shape_only")
        self.assertFalse(result["ready_for_use"])
        self.assertFalse(result["sources_verified"])

    def test_48_49_line_boundary_preserves_input(self):
        body = "CLM-I-001\n" + "\n".join(["行"] * 47)
        self.assertEqual(checker.check(marked(body))["wrapped_lines"], 48)
        with self.assertRaisesRegex(ValueError, "48行"):
            checker.check(marked(body + "\n多一行"))

    def test_blank_lines_count_but_are_not_silently_removed(self):
        body = "\n".join(["CLM-I-001"] * 28)
        spaced = body.replace("\n", "\n\n", 21)
        with self.assertRaisesRegex(ValueError, "48行"):
            checker.check(marked(spaced))
        compact = "\n".join(line for line in spaced.splitlines() if line.strip())
        self.assertEqual(compact, body)
        self.assertEqual(checker.check(marked(compact))["wrapped_lines"], 28)

    def test_character_limit_and_control_rejection(self):
        body = "CLM-I-001 " + "x" * 1590
        self.assertEqual(checker.check(marked(body))["characters"], 1600)
        for invalid in (body + "x", "CLM-I-001\u202e"):
            with self.assertRaises(ValueError):
                checker.check(marked(invalid))

    def test_missing_duplicate_reversed_markers_and_short_ids(self):
        valid = marked("CLM-I-001")
        for text in (
            "CLM-I-001",
            valid + valid,
            "<!-- briefing:end -->CLM-I-001<!-- briefing:start -->",
            marked("C01 [S01]"),
            marked("CLM-I-01"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                checker.check(text)

    def test_cli_file_is_unchanged_and_missing_input_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "draft.md"
            data = marked("CLM-I-001 合成草稿").encode("utf-8")
            path.write_bytes(data)
            result = run_python("check_briefing_draft.py", [str(path)])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["ready_for_use"])
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(list(Path(temp).iterdir()), [path])
            missing = run_python(
                "check_briefing_draft.py", [str(path.with_name("missing.md"))]
            )
            self.assertEqual(missing.returncode, 2)
            self.assertFalse(missing.stdout)

    def test_cli_stdin_utf8_and_invalid_or_oversized_bytes(self):
        for data, code in (
            (marked("CLM-L-1000 合成角色").encode("utf-8"), 0),
            (b"\xff", 2),
            (b"x" * (checker.MAX_INPUT_BYTES + 1), 2),
        ):
            with self.subTest(code=code):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SCRIPTS / "check_briefing_draft.py"),
                        "-",
                    ],
                    input=data,
                    capture_output=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, code, result.stderr.decode("utf-8"))
                if code == 0:
                    self.assertFalse(json.loads(result.stdout)["sources_verified"])
                else:
                    self.assertFalse(result.stdout)

    def test_default_cli_does_not_create_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            for source in SCRIPTS.glob("*.py"):
                (scripts / source.name).write_bytes(source.read_bytes())
            draft = root / "draft.md"
            draft.write_text(marked("CLM-I-001 合成草稿"), encoding="utf-8")
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            env = os.environ.copy()
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            env.pop("PYTHONPYCACHEPREFIX", None)
            result = subprocess.run(
                [sys.executable, str(scripts / "check_briefing_draft.py"), str(draft)],
                capture_output=True, timeout=20, env=env, cwd=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse(list(root.rglob("__pycache__")))

    def test_due_date_explanation_must_stay_outside_cell(self):
        self.assertTrue(checker.validator.date_valid("2026-09-10"))
        for value in ("2026-09-10前", "2026-09-10（按原约定执行）", "2026-02-30"):
            self.assertFalse(checker.validator.date_valid(value))

    def test_documented_public_and_unauthorized_commands(self):
        document = (SKILL_ROOT / "references/validation-cases.md").read_text(
            encoding="utf-8"
        )
        section = document.split("## 7.", 1)[1].split("## 8.", 1)[0]
        for name, expected in (("示例医院", 0), ("无授权负例医院", 2)):
            command = re.search(
                r'python3 scripts/init_workspace.py "' + name + r'".*?--json',
                section,
                re.S,
            )
            if command is None:
                self.fail(f"文档缺少{name}初始化命令")
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                args = shlex.split(command.group().replace("\\\n", " "))[2:]
                args = [temp if arg == "$case_root" else arg for arg in args]
                result = run_python("init_workspace.py", args)
                self.assertEqual(
                    result.returncode, expected, result.stderr or result.stdout
                )
                if expected == 0:
                    workspace = Path(json.loads(result.stdout)["workspace"])
                    self.assertEqual(len(list(workspace.glob("*.md"))), 5)
                    check = run_python(
                        "validate_outputs.py", [str(workspace), "--json"]
                    )
                    self.assertEqual(check.returncode, 0, check.stdout)
                else:
                    self.assertIn("authorization_required", result.stderr)
                    self.assertFalse(list(Path(temp).glob("客户研究-*")))


if __name__ == "__main__":
    unittest.main()
