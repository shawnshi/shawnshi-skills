from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check_text_invariants.py"
SPEC = importlib.util.spec_from_file_location("check_text_invariants", SCRIPT_PATH)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class InvariantCheckerTests(unittest.TestCase):
    def compare(self, original: str, revised: str, mode: str = "strict", fmt: str = "auto"):
        return CHECKER.compare(original, revised, mode, fmt, [], [])

    def test_unchanged_protected_content_passes(self):
        text = "截至2026-06-30，共31个系统，完成率80.65%，结论仍可能调整。[12]"
        report = self.compare(text, text)
        self.assertTrue(report["ok"])

    def test_number_change_fails(self):
        report = self.compare("共31个系统。", "共37个系统。")
        self.assertFalse(report["ok"])
        self.assertIn("numbers", report["failures"])

    def test_version_number_change_fails(self):
        report = self.compare("版本V1.2。", "版本V1.3。")
        self.assertFalse(report["ok"])
        self.assertIn("numbers", report["failures"])

    def test_number_position_swap_fails(self):
        report = self.compare("甲负责31项，乙负责37项。", "甲负责37项，乙负责31项。")
        self.assertFalse(report["ok"])
        self.assertIn("numbers", report["failures"])

    def test_comparison_direction_change_fails(self):
        report = self.compare("数量不得少于5项。", "数量不得超过5项。")
        self.assertFalse(report["ok"])
        self.assertIn("semantic_markers", report["failures"])

    def test_uncertainty_change_fails_in_strict_mode(self):
        report = self.compare("结果可能相关。", "结果确定相关。")
        self.assertFalse(report["ok"])
        self.assertIn("semantic_markers", report["failures"])

    def test_uncertainty_change_warns_in_standard_mode(self):
        report = self.compare("结果可能相关。", "结果确定相关。", mode="standard")
        self.assertTrue(report["ok"])
        self.assertIn("semantic_markers", report["warnings"])

    def test_direct_quote_change_fails(self):
        report = self.compare("原文称：“尚不能证明因果。”", "原文称：“已经证明因果。”")
        self.assertFalse(report["ok"])
        self.assertIn("quotes", report["failures"])

    def test_multiline_quote_change_fails(self):
        original = "原文称：“第一行\n第二行尚不能证明因果。”"
        revised = "原文称：“第一行\n第二行已经证明因果。”"
        report = self.compare(original, revised)
        self.assertFalse(report["ok"])
        self.assertIn("quotes", report["failures"])

    def test_placeholder_removal_fails(self):
        report = self.compare("上线日期【待确认】。", "上线日期为8月。")
        self.assertFalse(report["ok"])
        self.assertIn("placeholders", report["failures"])

    def test_bare_placeholder_removal_fails(self):
        report = self.compare("上线日期待确认，负责人TBD。", "上线日期确定，负责人已定。")
        self.assertFalse(report["ok"])
        self.assertIn("placeholders", report["failures"])

    def test_named_footnote_change_fails(self):
        report = self.compare("结论A[^risk]。", "结论A[^other]。")
        self.assertFalse(report["ok"])
        self.assertIn("citations", report["failures"])

    def test_citation_position_swap_fails(self):
        report = self.compare("结论A[1]，结论B[2]。", "结论A[2]，结论B[1]。")
        self.assertFalse(report["ok"])
        self.assertIn("citations", report["failures"])

    def test_unit_change_fails(self):
        report = self.compare("距离为30 km。", "距离为30 m。")
        self.assertFalse(report["ok"])
        self.assertIn("units", report["failures"])

    def test_medical_unit_change_fails(self):
        report = self.compare("血压为120 mmHg。", "血压为120 kPa。")
        self.assertFalse(report["ok"])
        self.assertIn("units", report["failures"])

    def test_url_parenthesized_path_change_fails(self):
        report = self.compare("见https://x/spec(alpha)", "见https://x/spec(beta)")
        self.assertFalse(report["ok"])
        self.assertIn("urls", report["failures"])

    def test_mailto_and_relative_link_changes_fail(self):
        report = self.compare(
            "联系mailto:a@example.com，见[规范](../spec.md)。",
            "联系mailto:b@example.com，见[规范](../other.md)。",
        )
        self.assertFalse(report["ok"])
        self.assertIn("urls", report["failures"])

    def test_markdown_table_shape_change_fails(self):
        original = "| 年份 | 系统 |\n|---|---|\n| 2027 | HIS |"
        revised = "| 年份 |\n|---|\n| 2027 |"
        report = self.compare(original, revised)
        self.assertFalse(report["ok"])
        self.assertIn("tables", report["failures"])

    def test_markdown_table_content_swap_fails(self):
        original = "| 部门 | 责任 |\n|---|---|\n| IT | 验收 |\n| 业务 | 旁听 |"
        revised = "| 部门 | 责任 |\n|---|---|\n| IT | 旁听 |\n| 业务 | 验收 |"
        report = self.compare(original, revised)
        self.assertFalse(report["ok"])
        self.assertIn("tables", report["failures"])

    def test_single_column_markdown_table_content_change_fails(self):
        original = "| 状态 |\n|---|\n| 待确认 |"
        revised = "| 状态 |\n|---|\n| 已完成 |"
        report = self.compare(original, revised)
        self.assertFalse(report["ok"])
        self.assertIn("tables", report["failures"])

    def test_heading_text_change_fails_in_strict_mode(self):
        report = self.compare("# 风险控制\n正文", "# 价值提升\n正文")
        self.assertFalse(report["ok"])
        self.assertIn("headings", report["failures"])

    def test_json_scalar_edit_preserves_shape(self):
        original = '{"name":"草稿","note":"表达含糊"}'
        revised = '{"name":"草稿","note":"表达需要进一步明确"}'
        report = CHECKER.compare(
            original,
            revised,
            "strict",
            "auto",
            [],
            [("表达含糊", "表达需要进一步明确")],
        )
        self.assertTrue(report["ok"])

    def test_json_array_order_change_fails(self):
        report = self.compare('[{"owner":"IT"},{"owner":"业务"}]', '[{"owner":"业务"},{"owner":"IT"}]')
        self.assertFalse(report["ok"])
        self.assertIn("json_values", report["failures"])

    def test_invalid_revised_json_fails(self):
        original = '{"note":"表达不清"}'
        revised = '{"note":"表达需要进一步明确"'
        report = self.compare(original, revised)
        self.assertFalse(report["ok"])
        self.assertIn("json_validity", report["failures"])

    def test_duplicate_json_key_fails(self):
        report = self.compare('{"owner":"IT"}', '{"owner":"IT","owner":"业务"}')
        self.assertFalse(report["ok"])
        self.assertIn("json_validity", report["failures"])

    def test_invalid_original_json_fails_in_auto_mode(self):
        report = self.compare('{"note":"表达含糊"', '{"note":"表达清晰"}')
        self.assertFalse(report["ok"])
        self.assertEqual(report["format"], "json")
        self.assertIn("json_validity", report["failures"])

    def test_trailing_comma_array_is_detected_as_invalid_json(self):
        report = self.compare("[1,2,]", "[1,2]")
        self.assertFalse(report["ok"])
        self.assertEqual(report["format"], "json")
        self.assertIn("json_validity", report["failures"])

    def test_protected_term_change_fails(self):
        report = CHECKER.compare(
            "WiNEX平台",
            "WinEX平台",
            "strict",
            "text",
            ["WiNEX", "WinEX"],
            [],
        )
        self.assertFalse(report["ok"])
        self.assertIn("protected_terms", report["failures"])

    def test_protected_term_position_swap_fails(self):
        report = CHECKER.compare(
            "信息技术部门必须验收，业务部门可以旁听。",
            "业务部门必须验收，信息技术部门可以旁听。",
            "strict",
            "text",
            ["信息技术部门", "业务部门"],
            [],
        )
        self.assertFalse(report["ok"])
        self.assertIn("protected_terms", report["failures"])

    def test_protected_responsibility_span_change_fails(self):
        report = CHECKER.compare(
            "信息技术部门必须验收，业务部门可以旁听。",
            "信息技术部门可以旁听，业务部门必须验收。",
            "strict",
            "text",
            ["信息技术部门必须验收", "业务部门可以旁听"],
            [],
        )
        self.assertFalse(report["ok"])
        self.assertIn("protected_terms", report["failures"])

    def test_exact_replacement_authorizes_only_declared_number_change(self):
        report = CHECKER.compare(
            "共31个系统。",
            "共37个系统。",
            "strict",
            "text",
            [],
            [("31", "37")],
        )
        self.assertTrue(report["ok"])
        number_check = next(check for check in report["checks"] if check["category"] == "numbers")
        self.assertEqual(number_check["status"], "allowed")

    def test_multiple_exact_replacements_allow_declared_number_swap(self):
        report = CHECKER.compare(
            "甲1，乙2。",
            "甲2，乙1。",
            "strict",
            "text",
            [],
            [("甲1", "甲2"), ("乙2", "乙1")],
        )
        self.assertTrue(report["ok"])

    def test_exact_replacement_rejects_any_extra_edit(self):
        original = "第三段：系统运型稳定。其他内容保持。"
        revised = "第三段：系统运行稳定。其他内容删除。"
        report = CHECKER.compare(
            original,
            revised,
            "strict",
            "text",
            [],
            [("第三段：系统运型稳定。", "第三段：系统运行稳定。")],
        )
        self.assertFalse(report["ok"])
        self.assertIn("authorized_scope", report["failures"])

    def test_exact_mode_requires_an_exact_replacement_scope(self):
        report = CHECKER.compare(
            "系统运型稳定。",
            "系统运行稳定。",
            "exact",
            "text",
            [],
            [],
        )
        self.assertFalse(report["ok"])
        self.assertIn("authorized_scope", report["failures"])

    def test_exact_replacement_requires_unique_source(self):
        report = CHECKER.compare(
            "运型。运型。",
            "运行。运型。",
            "strict",
            "text",
            [],
            [("运型", "运行")],
        )
        self.assertFalse(report["ok"])
        self.assertIn("authorized_scope", report["failures"])

    def test_cli_reports_success_and_exit_zero_for_exact_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.txt"
            revised = root / "revised.txt"
            original.write_text("系统运型稳定。", encoding="utf-8")
            revised.write_text("系统运行稳定。", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    str(original),
                    str(revised),
                    "--mode",
                    "exact",
                    "--exact-replacement",
                    "系统运型稳定。=>系统运行稳定。",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_cli_rejects_undeclared_extra_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.txt"
            revised = root / "revised.txt"
            original.write_text("系统运型稳定。其他内容保持。", encoding="utf-8")
            revised.write_text("系统运行稳定。其他内容删除。", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    str(original),
                    str(revised),
                    "--mode",
                    "exact",
                    "--exact-replacement",
                    "系统运型稳定。=>系统运行稳定。",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("authorized_scope", json.loads(result.stdout)["failures"])


if __name__ == "__main__":
    unittest.main()
