import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class WeeklyAutoSaveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.weekly = (SKILL_ROOT / "prompts" / "WEEKLY.md").read_text(encoding="utf-8")

    def test_weekly_request_authorizes_only_canonical_autosave(self):
        self.assertIn("原始周审计请求即为这一个 canonical 目标的保存授权", self.skill)
        self.assertIn("草稿、预览或不保存", self.skill)
        self.assertIn("第二处持久化", self.skill)

    def test_weekly_payload_preserves_day_and_replaces_unique_week(self):
        self.assertIn("完整保留该日既有七段日志", self.weekly)
        self.assertIn("新增或替换一个 `## [YYYY-Www] Weekly Cognitive Audit", self.weekly)
        self.assertIn("`diary_ops.py scope`", self.weekly)
        self.assertIn("`replace-date`", self.weekly)

    def test_failure_stops_persistence(self):
        for marker in ("审计门", "权威门", "范围门", "写后校验失败"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)

    def test_audit_can_trigger_only_pre_authorized_garmin_sync(self):
        for marker in (
            "Codex-Garmin-Health-Sync",
            "启动该任务一次",
            "不得在同一次复盘中重试",
            "任务不存在或未启用时不得自动注册、更新或修复",
            "用户要求草稿、预览、只读、不同步或不联网时，不触发任务",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)


if __name__ == "__main__":
    unittest.main()
