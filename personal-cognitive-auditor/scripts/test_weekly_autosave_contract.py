import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class PeriodicAutoSaveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        cls.prompts = {
            period: (SKILL_ROOT / "prompts" / filename).read_text(encoding="utf-8")
            for period, filename in {
                "weekly": "WEEKLY.md",
                "monthly": "MONTHLY.md",
                "quarterly": "QUARTERLY.md",
            }.items()
        }

    def test_periodic_requests_authorize_only_canonical_autosave(self):
        for marker in (
            "受保护用户事件",
            "periodic-audit-request-v1",
            "canonical_autosave",
            "草稿、预览、只读或不保存",
            "第二处持久化",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)

    def test_periodic_payloads_use_unique_h2_and_bounded_actions(self):
        expected = {
            "weekly": ("[YYYY-Www] Weekly Cognitive Audit", "replace-weekly-audit"),
            "monthly": ("[YYYY-MM] Monthly Cognitive Audit", "replace-monthly-audit"),
            "quarterly": (
                "[YYYY-QN] Quarterly Cognitive Audit",
                "replace-quarterly-audit",
            ),
        }
        for period, (heading, action) in expected.items():
            with self.subTest(period=period):
                prompt = self.prompts[period]
                self.assertIn("完整保留", prompt)
                self.assertIn(heading, prompt)
                self.assertIn("唯一 H2", prompt)
                self.assertIn("`periodic-audit-request-v1`", prompt)
                self.assertIn("`diary_ops.py scope/replace", prompt)
                self.assertIn(action, prompt)

    def test_generation_is_not_save_authorization_and_preserves_periodic_blocks(self):
        for marker in (
            "## 最短用法：生成不等于保存",
            "本周个人日志审计，草稿",
            "内容门通过不等于保存授权",
            "--enforce-template-fields --period-type weekly --period-id <YYYY-Www>",
            "模板模式仍须填写能量管理稳定字段",
            "人工检查只支持草稿交付",
            "replace-personal-diary",
            "重复或非法周期区块失败关闭",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)

    def test_failure_stops_persistence(self):
        for marker in ("审计门", "权威门", "请求门", "范围门", "写后校验失败"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)

    def test_audit_uses_only_the_bounded_direct_two_stage_sync(self):
        for marker in (
            "sync_health_data.py sync --dry-run",
            "--allow-network --allow-sync --allow-health-data",
            "不得在同一次复盘中重试",
            "不得自动注册、更新或修复任何计划任务",
            "用户要求草稿、预览、只读、不同步或不联网时，不触发同步",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.skill)
        self.assertNotIn("启动该任务一次", self.skill)


if __name__ == "__main__":
    unittest.main()
