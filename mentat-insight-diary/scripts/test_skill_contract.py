import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
TEMPLATE_TEXT = (SKILL_ROOT / "assets" / "ooda_template.md").read_text(
    encoding="utf-8"
)


class MentatInsightDiaryContractTests(unittest.TestCase):
    def test_generation_defaults_to_canonical_atomic_save(self):
        for required in (
            "生成完成后自动保存",
            "personal-diary-writer",
            "canonical Mentat 目标",
            "同日原子替换",
            "标题数量等于 1",
            "授权范围摘要与实际写入范围摘要相等",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_preview_and_noncanonical_writes_do_not_inherit_authorization(self):
        for required in (
            "草稿、预览、分析、审计技能或不保存",
            "自定义路径、外部系统、知识库、STQM 和 Vector Lake",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_template_matches_writer_ooda_gate_and_does_not_preclaim_save(self):
        headings = (
            "**1. 观测 (Observe)：**",
            "**2. 导向 (Orient)：**",
            "**3. 决策 (Decide)：**",
            "**4. 执行 (Act)：**",
            "**5. 系统自我反思 (Self-Reflection)**",
            "**6. 对指挥官的观察与建议 (Commander Observation & Suggestion)**",
            "**7. 认知结晶 (Cognitive Distillations)：**",
            "**8. [Message to Future Mentat]**",
        )
        positions = []
        for required in headings:
            with self.subTest(required=required):
                self.assertIn(required, TEMPLATE_TEXT)
                self.assertIn(required, SKILL_TEXT)
                positions.append(TEMPLATE_TEXT.index(required))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("**未决问题**", TEMPLATE_TEXT)
        self.assertNotIn("日志已归档", TEMPLATE_TEXT)
        self.assertIn("不得预先声称本条已经保存", TEMPLATE_TEXT)

    def test_new_sections_keep_evidence_and_authorization_boundaries(self):
        for required in (
            "不得伪装主观意识或隐藏推理",
            "不做人格、动机或能力定性",
            "生成结晶不等于授权写入知识库",
            "不包含隐藏推理、凭据或越权指令",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)


if __name__ == "__main__":
    unittest.main()
