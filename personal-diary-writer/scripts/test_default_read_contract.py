import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_SKILL = SKILL_ROOT / "SKILL.md"
AUTHORITY_CONFIG = SKILL_ROOT / "authority.json"


class DefaultReadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority_text = AUTHORITY_SKILL.read_text(encoding="utf-8")
        cls.proxy_text = cls.authority_text
        cls.config = json.loads(AUTHORITY_CONFIG.read_text(encoding="utf-8"))
        locator = cls.config["authority_locator"]
        if locator.get("base") != "user_home":
            raise ValueError("production authority must use a user_home locator")
        cls.authority_path = Path.home().joinpath(*locator["segments"])
        if cls.authority_path.resolve() != AUTHORITY_SKILL.resolve():
            raise ValueError("production authority must bind to the Pi standalone skill")

    def test_personal_diary_grants_bounded_default_reads(self):
        self.assertIn("最近 3 天 Garmin 健康摘要", self.proxy_text)
        self.assertIn("日记日期及次日日历", self.proxy_text)
        self.assertIn("不再为这两类限定读取重复询问授权", self.proxy_text)

    def test_calendar_read_is_bound_to_gws_and_fails_closed(self):
        required = (
            "`gws auth status`",
            "`auth_method=oauth2`",
            "`token_valid=true`",
            "`gws calendar +agenda --today --timezone Asia/Shanghai --format json`",
            "`gws calendar +agenda --tomorrow --timezone Asia/Shanghai --format json`",
            "禁止自动改用 Outlook COM、Microsoft Graph、Windows 日历",
            "用户在当前请求中明确指定并授权其他来源",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)

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
        self.assertIn("canonical `personal-health-analysis`", self.authority_text)
        self.assertIn("runtime-authority.json", self.authority_text)
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

    def test_current_date_staleness_uses_one_direct_two_stage_sync(self):
        for marker in (
            "Current-date freshness gate",
            "sync_health_data.py sync --dry-run",
            "--allow-network --allow-sync --allow-health-data",
            "without retry",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)
        self.assertIn("不调用 `Codex-Garmin-Health-Sync`", self.authority_text)

    def test_energy_template_discloses_acquisition_audit(self):
        for marker in (
            "采集审计",
            "sync_eligible=<true|false>",
            "sync_attempted=<started|waited_existing|direct|not_attempted>",
            "task_status=<success|failed|timeout|invalid|start_failed|interrupted_or_terminated|not_checked>",
            "local_reread=<accepted|rejected|not_run>",
            "local_status=<complete|partial|no_data|read_error|not_run>",
            "live_fallback=<used|not_used>",
            "reason=<稳定原因码>",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)

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

    def test_exact_personal_diary_update_is_auto_authorized_and_bounded(self):
        self.assertIn(
            "Canonical personal-diary auto-save exception",
            self.authority_text,
        )
        for marker in (
            "personal-diary-request-v1",
            "personal_diary_request_gate",
            "replace-personal-diary",
            "canonical_autosave",
            "无需人工确认",
            "元请求不会被识别为日记写入授权",
            "audit_gate.py --enforce-template-fields",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.authority_text)
        for heading in (
            "今日事项",
            "今日进展与证据",
            "判断与反思",
            "时间背景",
            "能量管理（描述性生理背景）",
            "明日事项",
            "风险与未知",
            "行动闭环",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f"`## {heading}`", self.authority_text)

    def test_canonical_mentat_generation_is_auto_authorized(self):
        self.assertIn("Canonical Mentat auto-save exception", self.authority_text)
        self.assertIn("originating request is the approval", self.authority_text)
        self.assertIn("不再重复询问确认", self.proxy_text)

    def test_canonical_periodic_audits_are_auto_authorized_and_bounded(self):
        self.assertIn(
            "Canonical periodic personal-audit auto-save exception",
            self.authority_text,
        )
        for marker in (
            "周、月、季度",
            "periodic-audit-request-v1",
            "canonical_autosave",
            "草稿、预览、只读或不保存",
            "目标周期标题数量等于 1",
            "replace-weekly-audit",
            "replace-monthly-audit",
            "replace-quarterly-audit",
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
