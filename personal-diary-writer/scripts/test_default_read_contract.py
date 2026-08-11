import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROXY_SKILL = SKILL_ROOT / "SKILL.md"
AUTHORITY_CONFIG = SKILL_ROOT / "authority.json"


class DefaultReadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proxy_text = PROXY_SKILL.read_text(encoding="utf-8")
        cls.config = json.loads(AUTHORITY_CONFIG.read_text(encoding="utf-8"))
        locator = cls.config["authority_locator"]
        if locator.get("base") != "user_home":
            raise ValueError("production authority must use a user_home locator")
        cls.authority_path = Path.home().joinpath(*locator["segments"])
        cls.authority_text = cls.authority_path.read_text(encoding="utf-8")

    def test_personal_diary_grants_bounded_default_reads(self):
        self.assertIn("最近 3 天 Garmin 健康摘要", self.proxy_text)
        self.assertIn("日记日期及次日日历", self.proxy_text)
        self.assertIn("不再为这两类限定读取重复询问授权", self.proxy_text)

    def test_local_first_and_live_fallback_are_fail_closed(self):
        required = (
            "--source local --allow-health-data",
            "`no_data`",
            "`partial`",
            "--source live --allow-network --allow-health-data",
            "RUNTIME_CONTRACT_MISMATCH",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)

    def test_default_read_does_not_grant_mutating_capabilities(self):
        required = (
            "Garmin 登录",
            "令牌创建或刷新写入",
            "本地数据库同步",
            "原始活动文件下载",
            "日历写操作",
            "第二处持久化",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.proxy_text)

    def test_authority_routes_to_active_health_skill(self):
        self.assertIn("active `personal-health-analysis` skill", self.authority_text)
        legacy_runtime = (
            Path.home()
            / ".gemini"
            / "config"
            / "skills"
            / "personal-health-analysis"
        )
        self.assertNotIn(
            str(legacy_runtime),
            self.authority_text,
        )


if __name__ == "__main__":
    unittest.main()
