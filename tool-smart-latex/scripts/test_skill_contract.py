"""Static skill-contract checks, not proof of rendered PDF compliance."""

import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class WritingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.styles = (SKILL_ROOT / "references" / "styles.md").read_text(
            encoding="utf-8"
        )

    def test_requires_current_authoritative_writing_contract(self):
        self.assertIn("`pai/WRITING.md`", self.skill)
        self.assertIn("完整读取当前运行时", self.skill)
        self.assertIn("无法读取", self.skill)
        self.assertIn("只覆盖冲突条款", self.skill)
        self.assertIn("预置模板本身不构成覆盖理由", self.skill)

    def test_scopes_typography_to_language_and_protects_literals(self):
        for literal in ("中文与混排", "英文正文", "10–12 pt", "120–145%", "45–90"):
            with self.subTest(literal=literal):
                self.assertIn(literal, self.skill)
        for literal in ("代码", "URL", "引用键", "数学", "全局替换", "中文字符数"):
            with self.subTest(literal=literal):
                self.assertIn(literal, self.skill)

    def test_measures_actual_leading_and_adapts_task_copy(self):
        for literal in (
            "\\baselineskip",
            "\\f@size",
            "\\onehalfspacing",
            "\\RaggedRight",
            "任务副本",
            "compile_tex()",
            "不自动实施",
        ):
            with self.subTest(literal=literal):
                self.assertIn(literal, self.skill)
        self.assertIn("WRITING.md", self.styles)
        self.assertIn("not a publisher-approved exception", self.styles)
        self.assertIn("actual baseline", self.styles)

    def test_requires_pdf_visual_gate_and_exception_disclosure(self):
        for literal in ("首末页", "分页", "密集表格", "例外来源", "不能仅凭"):
            with self.subTest(literal=literal):
                self.assertIn(literal, self.skill)


if __name__ == "__main__":
    unittest.main()
