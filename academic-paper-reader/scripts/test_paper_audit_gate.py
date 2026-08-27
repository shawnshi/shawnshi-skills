import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = SCRIPT_DIR / "paper_audit_gate.py"
EXAMPLE_PATH = SCRIPT_DIR.parent / "examples" / "APR-Reference.md"
MANIFEST_PATH = SCRIPT_DIR.parent / "resource-manifest.json"
sys.path.insert(0, str(SCRIPT_DIR))

from paper_audit_gate import audit_file, validate_paper_draft


VALID_QUICK = "# 论文拆解\n\n这是已完成的正文。\n"
VALID_STANDARD = VALID_QUICK + "\n## 证据索引\n\n- 论文正文，第 3 页。\n"
VALID_DEEP = VALID_STANDARD + "\n## 来源范围\n\n仅使用用户提供的论文全文。\n"


class ValidationTests(unittest.TestCase):
    def test_literal_non_template_braces_are_allowed(self):
        errors, _ = validate_paper_draft(
            "论文附录记录接口示例 {{patient_id}} 与字段 {custom_field}。"
        )
        self.assertEqual(errors, [])

    def test_known_template_token_and_whitespace_variant_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            template = Path(temp_dir) / "template.md"
            template.write_text(
                "# {Target Paper}\n{Title}\n{Authors}\n", encoding="utf-8"
            )
            for token in ("{Target Paper}", "{  Target   Paper  }"):
                with self.subTest(token=token):
                    errors, _ = validate_paper_draft(
                        f"目标仍是 {token}。", template_path=template
                    )
                    self.assertTrue(
                        any(
                            "unresolved template placeholders" in item
                            for item in errors
                        )
                    )

    def test_generic_instructional_placeholder_is_rejected(self):
        errors, _ = validate_paper_draft("结论：{请在这里填写结果}")
        self.assertTrue(
            any("unresolved template placeholders" in item for item in errors)
        )

    def test_placeholders_and_todo_inside_code_are_ignored(self):
        content = """正文已完成。

`{论文标题}` 和 `TODO` 是接口示例，``含 ` 的 {论文标题}`` 也是示例。

```markdown
{论文标题}
待补充
```

~~~text
TBD: example
~~~
"""
        errors, _ = validate_paper_draft(content)
        self.assertEqual(errors, [])

    def test_unfinished_markers_are_rejected_outside_code(self):
        for marker in ("TODO", "tbd", "FIXME", "待填写", "待补充", "待完善", "待完成"):
            with self.subTest(marker=marker):
                errors, _ = validate_paper_draft(f"正文。\n{marker}：这一节。")
                self.assertTrue(any("unfinished markers" in item for item in errors))

    def test_bom_zero_width_and_html_comments_only_are_empty(self):
        errors, _ = validate_paper_draft("\ufeff\u200b <!-- 暂无正文 --> \u2060")
        self.assertIn("draft is empty", errors)

    def test_html_comment_does_not_hide_visible_content(self):
        errors, _ = validate_paper_draft("<!-- 说明 -->\n正文已经完成。")
        self.assertEqual(errors, [])

    def test_missing_and_corrupt_template_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing.md"
            errors, _ = validate_paper_draft("正文", template_path=missing)
            self.assertTrue(any("template is missing" in item for item in errors))

            corrupt = root / "corrupt.md"
            corrupt.write_bytes(b"\xff\xfe\x00")
            errors, _ = validate_paper_draft("正文", template_path=corrupt)
            self.assertTrue(any("not valid UTF-8" in item for item in errors))

            no_tokens = root / "no_tokens.md"
            no_tokens.write_text("# 没有任何占位符", encoding="utf-8")
            errors, _ = validate_paper_draft("正文", template_path=no_tokens)
            self.assertTrue(any("too few recognizable placeholders" in item for item in errors))

            partial = root / "partial.md"
            partial.write_text("# 截断的模板\n{唯一残留项}", encoding="utf-8")
            errors, _ = validate_paper_draft("正文", template_path=partial)
            self.assertTrue(any("template is damaged" in item for item in errors))

    def test_standard_and_deep_mode_requirements(self):
        quick_errors, _ = validate_paper_draft(VALID_QUICK, mode="quick")
        standard_errors, _ = validate_paper_draft(VALID_QUICK, mode="standard")
        deep_errors, _ = validate_paper_draft(VALID_STANDARD, mode="deep")

        self.assertEqual(quick_errors, [])
        self.assertTrue(any("evidence index" in item for item in standard_errors))
        self.assertTrue(any("source-scope" in item for item in deep_errors))
        self.assertEqual(validate_paper_draft(VALID_DEEP, mode="deep")[0], [])

    def test_current_reference_example_is_a_standard_mode_golden(self):
        content = EXAMPLE_PATH.read_text(encoding="utf-8")
        errors, _ = validate_paper_draft(content, mode="standard")
        self.assertEqual(errors, [])

    def test_deep_mode_accepts_explicit_no_network_statement(self):
        content = VALID_STANDARD + "\n本次分析未联网，仅依据用户提供的 PDF。\n"
        self.assertEqual(validate_paper_draft(content, mode="deep")[0], [])

    def test_deep_mode_accepts_bold_network_scope_label(self):
        content = VALID_STANDARD + "\n> **联网范围**：前后向引用溯源至 2026-08。\n"
        self.assertEqual(validate_paper_draft(content, mode="deep")[0], [])

    def test_denote_metadata_is_not_audit_surface(self):
        content = VALID_QUICK + "\n#+identifier: malformed\n#+title:\n"
        errors, warnings = validate_paper_draft(content)
        self.assertEqual(errors, [])
        self.assertFalse(any("Denote" in item or "identifier" in item for item in warnings))

    def test_style_phrases_do_not_produce_noise(self):
        content = VALID_QUICK + "\n值得注意的是，本文提出了一种方法。\n"
        _, warnings = validate_paper_draft(content)
        self.assertFalse(any("editorial phrase" in item for item in warnings))


class AuditFileTests(unittest.TestCase):
    def test_paths_hashes_and_expected_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "论文.pdf"
            output = root / "论文_论文拆解.md"
            source.write_bytes(b"source bytes")
            output.write_text(VALID_QUICK, encoding="utf-8")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()

            result = audit_file(
                output,
                source_path=source,
                source_sha256=expected,
                expected_output_dir=root,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["hashes"]["source"]["before"], expected)
            self.assertEqual(result["hashes"]["source"]["after"], expected)
            self.assertTrue(result["hashes"]["source"]["unchanged"])
            self.assertTrue(result["hashes"]["source"]["matches_expected"])
            self.assertEqual(
                result["hashes"]["output"]["sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )

    def test_source_must_exist_and_differ_from_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "report.md"
            output.write_text(VALID_QUICK, encoding="utf-8")

            missing = audit_file(output, source_path=root / "missing.pdf")
            same = audit_file(output, source_path=output)

            self.assertTrue(any("source file not found" in item for item in missing["errors"]))
            self.assertTrue(any("must not be the source" in item for item in same["errors"]))

    def test_source_path_requires_pre_analysis_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.pdf"
            output = root / "report.md"
            source.write_bytes(b"source")
            output.write_text(VALID_QUICK, encoding="utf-8")

            result = audit_file(output, source_path=source)

            self.assertFalse(result["ok"])
            self.assertTrue(
                any("recorded before analysis" in item for item in result["errors"])
            )

    def test_separate_output_with_source_content_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.md"
            output = root / "report.md"
            source.write_text(VALID_QUICK, encoding="utf-8")
            output.write_text(VALID_QUICK, encoding="utf-8")

            result = audit_file(output, source_path=source)

            self.assertFalse(result["ok"])
            self.assertTrue(any("identical" in item for item in result["errors"]))

    def test_source_sha_mismatch_and_output_dir_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            actual_dir = root / "actual"
            expected_dir = root / "expected"
            actual_dir.mkdir()
            expected_dir.mkdir()
            source = root / "source.pdf"
            output = actual_dir / "report.md"
            source.write_bytes(b"source")
            output.write_text(VALID_QUICK, encoding="utf-8")

            result = audit_file(
                output,
                source_path=source,
                source_sha256="0" * 64,
                expected_output_dir=expected_dir,
            )

            self.assertFalse(result["ok"])
            self.assertTrue(any("SHA-256 mismatch" in item for item in result["errors"]))
            self.assertTrue(any("directory mismatch" in item for item in result["errors"]))

    def test_invalid_utf8_output_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.md"
            output.write_bytes(b"\xff\xfe")
            result = audit_file(output)
            self.assertFalse(result["ok"])
            self.assertTrue(any("not valid UTF-8" in item for item in result["errors"]))


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def test_cli_return_codes_for_pass_fail_and_bad_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            good = root / "良好.md"
            bad = root / "bad.md"
            good.write_text(VALID_QUICK, encoding="utf-8")
            bad.write_text("TODO: finish", encoding="utf-8")

            self.assertEqual(self.run_cli(str(good)).returncode, 0)
            self.assertEqual(self.run_cli(str(bad)).returncode, 1)
            self.assertEqual(
                self.run_cli(str(good), "--mode", "impossible").returncode, 2
            )

    def test_cli_json_is_structured_utf8_and_contains_hash_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "来源.pdf"
            output = root / "报告.md"
            source.write_bytes("论文来源".encode("utf-8"))
            output.write_text(VALID_QUICK, encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()

            completed = self.run_cli(
                str(output),
                "--source-path",
                str(source),
                "--source-sha256",
                digest,
                "--expected-output-dir",
                str(root),
                "--json",
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(payload["ok"])
            self.assertIn("报告.md", payload["output_path"])
            self.assertEqual(payload["hashes"]["source"]["before"], digest)
            self.assertEqual(payload["hashes"]["source"]["after"], digest)
            self.assertRegex(payload["hashes"]["output"]["sha256"], r"^[0-9a-f]{64}$")

    def test_cli_json_failure_uses_exit_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.md"
            output.write_text("待补充", encoding="utf-8")
            completed = self.run_cli(str(output), "--json")
            payload = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["errors"])

    def test_cli_rejects_malformed_sha_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.md"
            output.write_text(VALID_QUICK, encoding="utf-8")
            completed = self.run_cli(str(output), "--source-sha256", "not-a-digest")
            self.assertEqual(completed.returncode, 2)


class ManifestTests(unittest.TestCase):
    @staticmethod
    def normalized_sha256(path: Path) -> str:
        data = path.read_bytes().replace(b"\r\n", b"\n")
        return hashlib.sha256(data).hexdigest()

    def test_manifest_hashes_counts_and_declared_dependencies(self):
        skill_dir = SCRIPT_DIR.parent
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest["skill"], "academic-paper-reader")
        declared_hashes = {
            entry["path"]: entry["sha256"]
            for entry in manifest["top_level_file_hashes"]
            + manifest["resource_file_hashes"]
        }
        self.assertIn("assets/icon.svg", declared_hashes)
        for relative_path, expected in declared_hashes.items():
            with self.subTest(path=relative_path):
                path = skill_dir / relative_path
                self.assertTrue(path.is_file())
                self.assertEqual(self.normalized_sha256(path), expected)

        for entry in manifest["resource_directories"]:
            directory = skill_dir / entry["name"]
            files = [
                path
                for path in directory.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            ]
            with self.subTest(directory=entry["name"]):
                self.assertEqual(len(files), entry["file_count"])

        for dependency in manifest["declared_local_dependencies"]:
            with self.subTest(dependency=dependency["path"]):
                path = skill_dir / dependency["path"]
                self.assertTrue(dependency["exists"])
                self.assertTrue(path.is_file())
                self.assertEqual(
                    self.normalized_sha256(path), dependency["sha256"]
                )
        self.assertEqual(manifest["missing_declared_dependencies"], [])


if __name__ == "__main__":
    unittest.main()
