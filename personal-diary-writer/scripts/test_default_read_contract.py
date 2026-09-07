import hashlib
import json
import re
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_SKILL = SKILL_ROOT / "SKILL.md"
AUTHORITY_CONFIG = SKILL_ROOT / "authority.json"


class DefaultReadContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entry_text = AUTHORITY_SKILL.read_text(encoding="utf-8")
        cls.read_contract = (SKILL_ROOT / "references/private-data-read.md").read_text(
            encoding="utf-8"
        )
        cls.write_contract = (SKILL_ROOT / "references/write-protocol.md").read_text(
            encoding="utf-8"
        )
        # Existing safety assertions cover the entry plus its required branch contracts.
        cls.authority_text = "\n".join(
            (cls.entry_text, cls.read_contract, cls.write_contract)
        )
        cls.proxy_text = cls.authority_text
        cls.config = json.loads(AUTHORITY_CONFIG.read_text(encoding="utf-8"))
        locator = cls.config["authority_locator"]
        if locator.get("base") != "user_home":
            raise ValueError("production authority must use a user_home locator")
        cls.authority_path = Path.home().joinpath(*locator["segments"])
        if cls.authority_path.resolve() != AUTHORITY_SKILL.resolve():
            raise ValueError(
                "production authority must bind to the Pi standalone skill"
            )

    def test_entry_routes_before_authority_gate_and_discloses_only_two_contracts(self):
        self.assertLess(
            self.entry_text.index("## 先选分支"),
            self.entry_text.index("## 启动门"),
        )
        self.assertEqual(
            set(re.findall(r"references/[a-z-]+\.md", self.entry_text)),
            {"references/private-data-read.md", "references/write-protocol.md"},
        )
        self.assertLess(len(self.entry_text), 6000)
        self.assertNotIn("sync_eligible=<true|false>", self.entry_text)
        self.assertNotIn("授权矩阵固定为", self.entry_text)
        self.assertIn("sync_eligible=<true|false>", self.read_contract)
        self.assertIn("授权矩阵固定为", self.write_contract)

    def test_current_text_draft_has_no_private_reads_telemetry_or_write_artifacts(self):
        draft = self.entry_text.split("- **纯文本草稿**：", 1)[1].split("\n- **", 1)[0]
        for marker in (
            "仅使用当次用户提供文本",
            "直接在回复中起草",
            "不读取个人历史、日历、健康库、私人会话或凭证",
            "不运行 authority 启动遥测",
            "不调用 `diary_ops.py scope`/`replace`",
            "不生成 scope/approval",
            "不要求 scope/hash 确认",
            "不为起草要求写入范围",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, draft)
        self.assertIn("到此结束，不执行后续写入步骤", self.entry_text)

    def test_private_read_draft_keeps_authority_and_read_only_exit(self):
        branch = self.entry_text.split("- **私人数据读取**：", 1)[1].split("\n- **", 1)[
            0
        ]
        for marker in (
            "先通过下方启动门",
            "再完整读取 `references/private-data-read.md`",
            "草稿身份不豁免读取门",
            "用户明确排除的来源不得读取",
            "只读/不保存仍不进入 scope、approval 或保存确认",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, branch)
        self.assertIn("不再为这两类限定读取重复询问授权", self.read_contract)

    def test_save_requires_fresh_authorization_and_full_protocol(self):
        branch = self.entry_text.split("- **保存**：", 1)[1].split("\n\n", 1)[0]
        for marker in (
            "先通过启动门",
            "再完整读取 `references/write-protocol.md`",
            "从草稿转为保存必须重新判定请求与目标",
            "不能复用草稿阶段同意",
            "读模板本身不授权数据采集",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, branch)
        for marker in (
            "随机 128-bit `scope_nonce`",
            "`user_confirmation` 必须回查受保护的当前 `PI_SESSION_FILE`",
            "旧确认、通用“确认”或 receipt 时间字段均不能授权新 scope",
            "同目录排他锁",
            "`fsync` 与 `os.replace`",
            "`finally` 中清理尚未提交的临时文件",
            "阻断 TOCTOU",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.write_contract)

    def test_no_draft_confirmation_conflict_remains_in_entry_or_references(self):
        for obsolete in (
            "草稿或非标准路径仍执行确认门",
            "立即停止草稿生成和写入",
            "仅明确声明草稿、预览、只读或非 canonical 目标的个人日记才需要先展示",
            "只有明确声明草稿、预览、只读或非 canonical 路径的日记才展示 hash",
            "需确认的草稿日记使用",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, self.authority_text)
        self.assertIn("不展示待确认 hash，也不要求保存确认", self.write_contract)
        self.assertIn(
            "非 canonical 目标不在本写入器能力范围，不创建 scope", self.write_contract
        )

    def test_eight_sections_stay_in_entry_without_forced_health_collection(self):
        headings = re.findall(r"^\d+\. `## (.+)`$", self.entry_text, re.MULTILINE)
        self.assertEqual(
            headings,
            [
                "今日事项",
                "今日进展与证据",
                "判断与反思",
                "时间背景",
                "能量管理（描述性生理背景）",
                "明日事项",
                "风险与未知",
                "行动闭环",
            ],
        )
        self.assertIn("没有健康读取需求时不得为填模板强行采集", self.read_contract)
        self.assertIn(
            "完整八章日记仍保留能量章节并注明未读取及判断边界", self.read_contract
        )

    def test_standalone_authority_hash_still_binds_exact_entry_bytes(self):
        self.assertEqual(
            self.config["authority_sha256"],
            hashlib.sha256(AUTHORITY_SKILL.read_bytes()).hexdigest(),
        )
        self.assertEqual(self.config["allowed_proxy_locators"], [])
        self.assertEqual(
            self.config["candidate_locators"], [self.config["authority_locator"]]
        )

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
            Path.home() / ".gemini" / "config" / "skills" / "personal-health-analysis"
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

    def test_read_only_and_offline_requests_exclude_freshness_sync(self):
        exclusion = self.read_contract.split("## 限定读取授权与禁止事项", 1)[1].split("\n- 进入", 1)[0]
        for marker in ("草稿", "预览", "只读", "不保存", "不同步", "不联网", "仅用本地数据"):
            with self.subTest(marker=marker):
                self.assertIn(marker, exclusion)
        self.assertIn("不触发本合同的新鲜度同步", exclusion)
        self.assertIn("不得走云端实时回退", exclusion)
        self.assertIn("不为恢复同步要求用户再次授权", exclusion)
        freshness = self.read_contract.split("3. Current-date freshness gate：", 1)[1].split("\n4.", 1)[0]
        self.assertIn("未命中上述同步退出条件", freshness)

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

    def test_checkpoint_keeps_read_only_exit_and_separate_noncanonical_authorization(
        self,
    ):
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
