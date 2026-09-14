import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SkillReviewIdentityTests(unittest.TestCase):
    def test_ordinary_self_check_is_not_independent_approval(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("普通反方自检可由当前代理直接执行，但不得称为独立红队或独立批准", skill)
        self.assertIn("仅在普通自检中", skill)
        self.assertIn("可继续不依赖该批准的普通分析", skill)

    def test_required_review_and_missing_capability_in_both_surfaces(self):
        for name in ["SKILL.md", "references/output_format.md"]:
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                for rule in ["真实、未参与生成的独立审查者", "真实用户显式批准路径", "停止依赖该批准的放行", "不等于批准", "回执"]:
                    self.assertIn(rule, text)
                self.assertIn("上位合同准许", text)

if __name__ == "__main__":
    unittest.main()
