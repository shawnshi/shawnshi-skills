import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SkillSourceAuthorizationTests(unittest.TestCase):
    def test_available_workspace_and_connected_lake_do_not_authorize_reads(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for rule in ["本次任务已获准的路径、知识源", "同时满足任务需要、本次授权和适用访问合同", "当前工作区可用或知识库已连接不构成读取授权", "Vector Lake 也须满足上述条件"]:
            self.assertIn(rule, text)

    def test_insufficient_recall_does_not_expand_scope_or_stop_authorized_work(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for rule in ["可继续同一授权范围内", "不得自动扩大目录、读取私人历史或向外部传播材料", "继续使用已获准来源", "先补足授权", "已有明确窄化授权覆盖的读取不重复确认"]:
            self.assertIn(rule, text)

if __name__ == "__main__":
    unittest.main()
