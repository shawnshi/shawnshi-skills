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
            "`authentication_required`",
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

    def test_energy_projection_is_contentful_when_metrics_are_unavailable(self):
        for marker in (
            "runtime_preflight.py --mode live",
            "`not_scored`",
            "`sleep_debt_h=null`",
            "`sleep_debt_status=not_provided_by_source`",
            "触发条件、最小动作和完成标准",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)
        self.assertNotIn("- **执行带宽**: [DATA_UNAVAILABLE]", self.authority_text)
        self.assertNotIn("- **睡眠负债**: [DATA_UNAVAILABLE]", self.authority_text)
        self.assertIn("不得只写空值或 `[DATA_UNAVAILABLE]`", self.proxy_text)

    def test_personal_diary_energy_template_matches_strict_audit_contract(self):
        self.assertIn("## 能量管理（描述性生理背景）", self.authority_text)
        self.assertIn("--enforce-template-fields", self.authority_text)
        for field in (
            "数据范围与来源",
            "组件覆盖与新鲜度",
            "睡眠观察",
            "HRV 与静息心率观察",
            "Body Battery 与压力观察",
            "执行带宽",
            "睡眠负债",
            "摩擦解构",
            "交叉归因",
            "干预指令",
            "数据缺口与不可判断事项",
        ):
            with self.subTest(field=field):
                self.assertIn(f"**{field}**", self.authority_text)
        self.assertNotIn(
            "## 能量管理 (Biological-Cognitive Correlation)",
            self.authority_text,
        )

    def test_canonical_mentat_generation_is_auto_authorized(self):
        self.assertIn("Canonical Mentat auto-save exception", self.authority_text)
        self.assertIn("originating request is the approval", self.authority_text)
        self.assertIn("不再重复询问确认", self.proxy_text)

    def test_canonical_weekly_audit_is_auto_authorized_and_bounded(self):
        self.assertIn("Canonical weekly personal-audit auto-save exception", self.authority_text)
        self.assertIn("current natural week's personal-log audit", self.authority_text)
        for marker in (
            "草稿、预览或不保存",
            "保留周期结束日既有日记内容",
            "同周标题数量等于 1",
            "第二处持久化",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.proxy_text)

    def test_other_personal_diary_and_noncanonical_targets_still_require_confirmation(self):
        self.assertIn("Personal diary checkpoint", self.authority_text)
        for marker in (
            "drafts/previews",
            "personal diaries",
            "custom paths",
            "knowledge bases",
            "Vector Lake",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)


if __name__ == "__main__":
    unittest.main()
