from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests.common import SCRIPTS, load_module, run_python
from tests.fixture_builder import (
    _rebuild_manifest,
    build_pending_letter_workspace,
    build_pending_strategy_workspace,
    record_action_assertion,
)


VALIDATOR = load_module("delivery_structure_regression_validator", SCRIPTS / "validate_outputs.py")
PREFLIGHT = load_module("delivery_structure_regression_preflight", SCRIPTS / "preflight_intake.py")
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def issue_codes(issues: list[object]) -> set[str]:
    return {issue.code for issue in issues}


def total_document(
    *,
    business_mode: str,
    route: str,
    depth: str,
    body: str = "",
    strategy_variant: str | None = None,
):
    frontmatter = {
        "business_mode": business_mode,
        "route": route,
        "depth": depth,
        "ready_for_use": "false",
        "module_status": "completed",
        "freshness_status": "current",
        "evidence_cutoff_date": "2026-08-27",
        "runtime_owner": "测试负责人",
    }
    if strategy_variant is not None:
        frontmatter["strategy_variant"] = strategy_variant
    return VALIDATOR.Document(
        Path("/tmp/示例医院客户研究与拜访准备报告.md"),
        "",
        frontmatter,
        body,
    )


def complete_briefing_body(*, include_agenda: bool, complete_opportunity: bool) -> str:
    opportunity_rows = ["| Need | 需求已初步明确 | CLM-I-001 |"]
    if complete_opportunity:
        opportunity_rows.extend(
            [
                "| Authority | 决策角色待现场确认 | CLM-I-001 |",
                "| Budget/Procurement | 预算与采购口径待确认 | CLM-I-001 |",
                "| Competition | 竞争位置待确认 | CLM-I-001 |",
                "| 建议 | 先验证最小推进动作 | CLM-I-001 |",
            ]
        )
    agenda = ""
    if include_agenda:
        agenda = """
## 建议交流节奏

| 时段 | 交流主题 | 目标 |
|---|---|---|
| 0—5分钟 | 开场与目标对齐 | 确认本次交流边界 |
| 5—20分钟 | 核心问题验证 | 核实需求和决策结构 |
| 20—25分钟 | 方案边界讨论 | 明确可继续验证的范围 |
| 25—30分钟 | 收口 | 确认最小推进动作 |
"""
    return f"""## 一句话判断

建议以验证客户需求和决策结构为主，依据 CLM-I-001。

## 会前必须知道

| 事实 | 类型与依据 | 拜访意义 |
|---|---|---|
| 客户主体已确认 | F CLM-I-001 | 可开展结构化交流 |

## 机会与边界

| 维度 | 判断 | 依据claim_id |
|---|---|---|
{chr(10).join(opportunity_rows)}

## 三个现场问题

1. 当前最需要解决的业务问题是什么？
2. 谁负责需求、预算和采购决策？
3. 下一步可验证的最小动作是什么？
{agenda}
## 最小推进动作

- 动作：会后确认一次需求验证会。
- 依据claim_id：CLM-I-001

## 未决风险

- 预算、采购时序和竞争位置仍待确认。
"""


def keyword_only_standard_strategy():
    return VALIDATOR.Document(
        Path("/tmp/示例医院交流策略与议题设计.md"),
        "",
        {
            "strategy_variant": "scheduled_visit",
            "target_contact_level": "信息中心负责人",
            "visit_objective": "确认下一步需求验证安排",
            "minimum_next_step": "会后确认需求验证会",
            "module_status": "completed",
            "freshness_status": "current",
            "evidence_cutoff_date": "2026-08-27",
        },
        """## 概述

目标与最小推进动作、机会资格、议程、参会分工、材料、会后行动、CRM/PIMS
均待补充；当前仅记录关键词。依据 CLM-I-001。
""",
    )


def account_strategy(*, empty_actions: bool, omit_no_go_fields: bool = False):
    if empty_actions:
        action_rows = """| 30天 |  |  |  |  |  |  |  |  |  |  |
| 60天 |  |  |  |  |  |  |  |  |  |  |
| 90天 |  |  |  |  |  |  |  |  |  |  |"""
    else:
        action_rows = """| 30天 | 验证项目窗口 | observe | customer_contact | none | 账户负责人 | 2026-09-26 | 客户确认 | 形成窗口结论 | 无法确认窗口时转观察 | 是 |
| 60天 | 核实预算窗口 | recheck | customer_contact | none | 账户负责人 | 2026-10-26 | 角色清单 | 形成预算判断 | 无预算依据时停止加码 | 是 |
| 90天 | 做出投入判断 | recheck | none | none | 账户负责人 | 2026-11-25 | 前两项完成 | 形成继续或停止结论 | 证据仍缺失时退出 | 是 |"""
    no_go_fields = "" if omit_no_go_fields else """
- 投入强度：低
- 建议理由：核心角色与预算窗口仍需进一步验证
"""
    return VALIDATOR.Document(
        Path("/tmp/示例医院交流策略与议题设计.md"),
        "",
        {
            "strategy_variant": "account_planning",
            "strategic_question": "未来90天是否值得持续投入",
            "planning_horizon": "90天",
            "minimum_next_step": "验证项目窗口",
            "module_status": "completed",
            "freshness_status": "current",
            "evidence_cutoff_date": "2026-08-27",
        },
        f"""## 战略问题与最小推进动作
验证未来90天是否值得继续投入。

## 判断链与证据边界
当前判断均待验证。

## 利益相关者与决策结构
角色尚待核实。

## 机会资格与投入建议
- 建议：monitor
{no_go_fields}

## 情景与触发条件
以预算窗口为触发条件。

## 30/60/90天账户动作

| 周期 | action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 调整/停止触发 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|---|
{action_rows}

## 验证计划
依次验证角色、预算和时序。

## 风险、承诺边界与停止条件
- 停止继续投入的最低条件：无法验证预算窗口及正式责任角色时停止主动投入。

## CRM/PIMS候选
记录上述动作。
""",
    )


def completed_letter(external_body: str) -> VALIDATOR.Document:
    return VALIDATOR.Document(
        Path("/tmp/示例医院客户信-内部待审核.md"),
        "",
        {
            "module_status": "completed",
            "review_status": "pending",
            "external_output_required": "true",
            "recipient_role": "张主任，信息中心主任，身份已确认",
            "letter_purpose": "确认下一次技术交流安排",
            "expected_action": "确认九月技术交流时间",
            "signer": "王经理，客户负责人",
        },
        f"""`EXTERNAL_BODY_START`
{external_body}
`EXTERNAL_BODY_END`
""",
    )


def loaded_by_type(workspace: Path) -> dict[str, VALIDATOR.Document]:
    issues: list[object] = []
    documents = VALIDATOR.load_documents(workspace, issues)
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise AssertionError([issue.code for issue in errors])
    return {
        document.frontmatter.get("artifact_type"): document
        for document in documents
    }


def write_mutated_body(document: VALIDATOR.Document, body: str) -> None:
    document.path.write_text(
        document.text.replace(document.body, body, 1),
        encoding="utf-8",
    )


def controlled_no_go_strategy(
    document: VALIDATOR.Document,
) -> tuple[dict[str, str], str]:
    body = """# 示例医院账户经营策略与验证计划

## 战略问题与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 待决策问题 | 未来90天是否值得持续投入 | CLM-I-001 |
| 经营周期 | 90天 | CLM-I-001 |
| 最小推进动作 | 内部复核机会资格 | CLM-I-001 |
| 完成标准 | no_go_decision_recorded | CLM-I-001 |

## 判断链与证据边界

| 环节 | 当前判断 | claim_id | 反证/替代解释 | 置信度 | 验证方式 |
|---|---|---|---|---|---|
| 客户发展或履职阶段 | insufficient_evidence | CLM-I-001 | insufficient_evidence | 低 | 被动观察证据变化 |
| 核心任务或矛盾 | insufficient_evidence | CLM-I-001 | conflicted_evidence | 低 | 内部复核机会资格 |
| 数字化支撑点 | not_applicable | CLM-I-001 | insufficient_evidence | 低 | 归档当前机会 |

## 利益相关者与决策结构

| 角色层级 | 当前可核实职责 | 事项/阶段 | 影响方式 | 证据 claim_id | 缺口与验证动作 |
|---|---|---|---|---|---|
| known_role | verified | qualification | verified | CLM-L-001 | 内部复核机会资格 |

## 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/反证 | 下一验证动作 |
|---|---|---|---|---|
| Budget | insufficient | CLM-I-001 | insufficient | 内部复核机会资格 |
| Authority | unverified | CLM-L-001 | insufficient | 内部复核机会资格 |
| Need | insufficient | CLM-I-001 | insufficient | 被动观察证据变化 |
| Timing/采购时序 | insufficient | CLM-I-001 | insufficient | 被动观察证据变化 |
| 竞争位置 | not_applicable | CLM-I-001 | insufficient | 归档当前机会 |

- 建议：no_go
- 投入强度：低
- 建议理由：evidence_insufficient

## 情景与触发条件

| 情景 | 触发信号 | 可能影响 | 应对动作 | owner | 复核日期 |
|---|---|---|---|---|---|
| 基准情景 | evidence_unchanged | maintain_no_go | 被动观察证据变化 | 账户负责人 | 2026-09-25 |
| 上行情景 | new_verified_evidence | reopen_internal_review | 内部复核机会资格 | 账户负责人 | 2026-10-25 |
| 下行情景 | disqualifying_evidence | close_opportunity | 归档当前机会 | 账户负责人 | 2026-11-24 |

## 30/60/90天账户动作

| 周期 | action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 调整/停止触发 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|---|
| 30天 | 内部复核机会资格 | recheck | none | none | 账户负责人 | 2026-09-25 | 内部复核 | qualification_review_recorded | keep_no_go_if_unresolved | 是 |
| 60天 | 被动观察证据变化 | observe | none | none | 账户负责人 | 2026-10-25 | 公开证据变化 | evidence_watch_recorded | archive_if_unchanged | 是 |
| 90天 | 归档当前机会 | archive | none | none | 账户负责人 | 2026-11-24 | 无依赖 | opportunity_archived | reopen_internal_review | 是 |

## 验证计划

| 待验证主张/假设 | 当前状态 | 验证问题或动作 | 目标对象/来源 | owner | due_date | 通过/停止信号 |
|---|---|---|---|---|---|---|
| CLM-I-001 | unknown | 内部复核机会资格 | internal_evidence | 账户负责人 | 2026-09-25 | keep_no_go |
| CLM-L-001 | H | 被动观察证据变化 | public_evidence | 账户负责人 | 2026-10-25 | reopen_internal_review |

## 风险、承诺边界与停止条件

| 风险/停止条件 | 依据 claim_id | 业务后果 | 预防或降级动作 | 升级角色 |
|---|---|---|---|---|
| evidence_insufficient | CLM-I-001 | maintain_no_go | 被动观察证据变化 | 战略账户责任岗 |
| authorization_missing | CLM-L-001 | internal_review_required | 内部复核机会资格 | 方案责任岗 |

- 停止继续投入的最低条件：evidence_still_insufficient
- 禁止承诺：all_unapproved_commitments

## CRM/PIMS候选

| 候选类型 | 内容 | 数据属性 | owner | due_date | 写回状态 |
|---|---|---|---|---|---|
| action | 内部复核机会资格 | 建议 | 账户负责人 | 2026-09-25 | candidate_only |
| verification | 被动观察证据变化 | 事实缺口 | 账户负责人 | 2026-10-25 | candidate_only |
"""
    frontmatter = dict(document.frontmatter)
    frontmatter["minimum_next_step"] = "内部复核机会资格"
    return frontmatter, body


def controlled_no_go_total(document: VALIDATOR.Document) -> str:
    sections = VALIDATOR.h2_sections(
        VALIDATOR.markdown_without_fenced_code(document.body)
    )
    task_context = sections["任务上下文与成果状态"][0].strip()
    refresh_log = sections["刷新结果记录"][0].strip()
    version_log = sections["版本与同步记录"][0].strip()
    return f"""# 示例医院客户研究与行动准备报告

## 1. 决策摘要

| 核心问题 | 当前结论 | claim_id | 对业务决策的意义 |
|---|---|---|---|
| 客户主体 | verified | CLM-I-001 | maintain_no_go |
| 责任角色 | verified | CLM-L-001 | internal_review_required |
| 当前任务 | insufficient_evidence | CLM-I-001 | maintain_no_go |
| 最小推进动作 | 内部复核机会资格 | CLM-I-001 | no_external_action |

## 2. 任务上下文与成果状态

{task_context}

### 2.1 本次RACI与审核SLA

| 角色 | 姓名（稳定角色/账号） | 本次责任 | 截止时间/状态 |
|---|---|---|---|
| account_owner | 账户负责人 | account_decision | pending |
| runtime_owner | 运行负责人 | research_execution | 2026-09-25 |
| evidence_reviewer | 证据负责人 | evidence_review | pending |
| commercial_reviewer | 商务审核岗 | commercial_review | pending |
| external_approver | not_applicable | external_approval | not_applicable |
| authorization_owner | 账户负责人 | data_authorization | pending |

## 3. 综合判断链

| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 验证问题或动作 |
|---|---|---|---|---|---|
| 发展阶段 | insufficient_evidence | CLM-I-001 | insufficient_evidence | 低 | 被动观察证据变化 |
| 核心矛盾 | insufficient_evidence | CLM-I-001 | conflicted_evidence | 低 | 内部复核机会资格 |
| 决策者关注 | conflicted_evidence | CLM-L-001 | insufficient_evidence | 低 | 内部复核机会资格 |
| 信息化支撑 | not_applicable | CLM-I-001 | insufficient_evidence | 低 | 归档当前机会 |
| 最小推进动作 | insufficient_evidence | CLM-I-001 | insufficient_evidence | 低 | 内部复核机会资格 |

## 4. G-C-P 推演

| 模块 | 结论 | claim_id | 边界 | 置信度 |
|---|---|---|---|---|
| G：目标任务 | insufficient_evidence | CLM-I-001 | insufficient_evidence | 低 |
| C：承接能力 | not_applicable | CLM-I-001 | insufficient_evidence | 低 |
| P：政策与项目风险 | conflicted_evidence | CLM-I-001 | insufficient_evidence | 低 |

## 4.1 机会资格与投入建议

| 维度 | 当前判断 | claim_id | 缺口/验证问题 |
|---|---|---|---|
| Budget | insufficient | CLM-I-001 | insufficient |
| Authority | unverified | CLM-L-001 | insufficient |
| Need | insufficient | CLM-I-001 | insufficient |
| Timing/采购时序 | insufficient | CLM-I-001 | insufficient |
| 竞争位置 | not_applicable | CLM-I-001 | insufficient |

- 建议：no_go
- 投入强度：低；依据：evidence_insufficient
- 继续投入的前提/停止条件：evidence_still_insufficient

## 4.2 执行与下一步

| action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 继续/调整/no-go条件 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|
| 内部复核机会资格 | recheck | none | none | 账户负责人 | 2026-09-25 | 内部复核 | qualification_review_recorded | keep_no_go_if_unresolved | 是 |

## 5. 高价值发现

| 序号 | claim_id | claim_type | provenance | 发现 | impact_type | 业务影响 | 置信度 |
|---|---|---|---|---|---|---|---|
| 1 | CLM-I-001 | F | public | 示例医院为本次研究主体 | risk | 存在误判风险 | 高 |

## 7. 关键缺口与验证计划

| claim_ref | claim_type_ref | provenance_ref | evidence_state | impact_type | verification_mode | owner | due_date |
|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | insufficient | risk | internal_review | 账户负责人 | 2026-09-25 |

## 8.1 刷新结果记录

{refresh_log}

## 9. 版本与同步记录

{version_log}
"""


def install_controlled_no_go_workspace(workspace: Path) -> None:
    by_type = loaded_by_type(workspace)
    strategy = by_type["visit_strategy"]
    total = by_type["comprehensive_report"]
    _frontmatter, strategy_body = controlled_no_go_strategy(strategy)
    strategy_text = strategy.text.replace(strategy.body, strategy_body, 1)
    strategy_text = VALIDATOR.replace_flat_frontmatter(
        strategy_text,
        {"minimum_next_step": "内部复核机会资格"},
    )
    strategy.path.write_text(strategy_text, encoding="utf-8")
    write_mutated_body(total, controlled_no_go_total(total))
    _rebuild_manifest(workspace, ["institution", "leader", "strategy"])


class DeliveryStructureRegressionTests(unittest.TestCase):
    def assert_cli_profiles_reject(
        self,
        workspace: Path,
        expected_code: str,
    ) -> None:
        for profile in ("candidate", "release"):
            with self.subTest(profile=profile):
                result = run_python(
                    "validate_outputs.py",
                    [str(workspace), "--profile", profile, "--json"],
                )
                self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
                self.assertIn(expected_code, codes)

    def govern_success(
        self,
        workspace: Path,
        *arguments: str,
    ) -> dict[str, object]:
        result = run_python(
            "validate_outputs.py",
            [str(workspace), *arguments, "--json"],
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], 0, payload)
        return payload

    def complete_strategic_release(self, workspace: Path) -> dict[str, object]:
        self.govern_success(workspace, "--profile", "candidate")
        record_action_assertion(
            workspace,
            event_id="approve-institution",
            actor_id="reviewer-institution",
            operation="approve_artifact:institution",
            artifact_type="institution_research",
        )
        self.govern_success(
            workspace,
            "--approve-artifact",
            "institution",
            "--reviewer",
            "周洁（机构事实审核岗）",
            "--actor-id",
            "reviewer-institution",
            "--action-event-id",
            "approve-institution",
        )
        record_action_assertion(
            workspace,
            event_id="approve-leader",
            actor_id="reviewer-leader",
            operation="approve_artifact:leader",
            artifact_type="leader_research",
        )
        self.govern_success(
            workspace,
            "--approve-artifact",
            "leader",
            "--reviewer",
            "孙宁（人物事实审核岗）",
            "--actor-id",
            "reviewer-leader",
            "--action-event-id",
            "approve-leader",
        )
        record_action_assertion(
            workspace,
            event_id="approve-strategy",
            actor_id="reviewer-strategy",
            operation="approve_artifact:strategy",
            artifact_type="visit_strategy",
        )
        self.govern_success(
            workspace,
            "--approve-artifact",
            "strategy",
            "--reviewer",
            "钱琳（拜访策略审核岗）",
            "--actor-id",
            "reviewer-strategy",
            "--action-event-id",
            "approve-strategy",
        )
        record_action_assertion(
            workspace,
            event_id="ready-strategic",
            actor_id="ready-strategic",
            operation="mark_ready:strategic_account",
            artifact_type="comprehensive_report",
        )
        self.govern_success(
            workspace,
            "--mark-ready",
            "--reviewer",
            "刘宁（战略账户责任岗）",
            "--actor-id",
            "ready-strategic",
            "--action-event-id",
            "ready-strategic",
        )
        return self.govern_success(workspace, "--profile", "release")

    def test_briefing_requires_exchange_agenda(self):
        briefing = VALIDATOR.Document(
            Path("/tmp/示例医院会前速览.md"),
            "",
            {"page_proxy": "markdown-one-page/v1", "review_status": "pending", "delivery_state": "draft_for_review"},
            complete_briefing_body(include_agenda=False, complete_opportunity=True),
        )
        issues: list[object] = []
        VALIDATOR.validate_briefing_contract(briefing, issues)
        self.assertIn("briefing_agenda_required", issue_codes(issues))

    def test_briefing_requires_complete_opportunity_rows(self):
        briefing = VALIDATOR.Document(
            Path("/tmp/示例医院会前速览.md"),
            "",
            {"page_proxy": "markdown-one-page/v1", "review_status": "pending", "delivery_state": "draft_for_review"},
            complete_briefing_body(include_agenda=True, complete_opportunity=False),
        )
        issues: list[object] = []
        VALIDATOR.validate_briefing_contract(briefing, issues)
        self.assertIn("briefing_opportunity_rows_invalid", issue_codes(issues))

    def test_standard_strategy_keyword_paragraph_is_not_a_section_contract(self):
        total = total_document(business_mode="standard_visit", route="visit_prep", depth="standard")
        strategy = keyword_only_standard_strategy()
        for strict in (False, True):
            with self.subTest(strict=strict):
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=strict,
                    current_time=NOW,
                )
                self.assertIn("presales_section_missing", issue_codes(issues))

    def test_letter_greeting_only_external_body_is_rejected(self):
        internal = VALIDATOR.Document(
            Path("/tmp/示例医院客户信-内部待审核.md"),
            "",
            {
                "module_status": "completed",
                "review_status": "pending",
                "external_output_required": "true",
                "recipient_role": "信息中心主任",
                "letter_purpose": "说明本次需求验证交流背景",
                "expected_action": "确认一次需求验证交流",
                "signer": "客户负责人李明",
            },
            """## 1. 内部审核摘要（严禁外发）
收件对象为信息中心主任，期望确认一次需求验证交流，签署人为客户负责人李明。

## 3. 已批准外发正文边界

`EXTERNAL_BODY_START`

您好。

`EXTERNAL_BODY_END`
""",
        )
        issues: list[object] = []
        VALIDATOR.validate_letter_isolation({"customer_letter_internal": internal}, issues)
        self.assertIn("letter_external_body_too_short", issue_codes(issues))

    def test_account_comprehensive_report_cannot_reintroduce_meeting_plan(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
            body="""## 4.2 拜访执行与下一步

| 时间 | 议题/动作 | 我方owner | 材料/演示 | 目标信号 |
|---|---|---|---|---|
| 0—5分钟 | 开场 | 账户负责人 | 产品演示 | 确认会议目标 |
""",
        )
        strategy = account_strategy(empty_actions=False)
        for strict in (False, True):
            with self.subTest(strict=strict):
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=strict,
                    current_time=NOW,
                )
                self.assertIn("account_comprehensive_structure_forbidden", issue_codes(issues))

    def test_account_strategy_action_rows_require_operational_fields(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        strategy = account_strategy(empty_actions=True)
        for strict in (False, True):
            with self.subTest(strict=strict):
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=strict,
                    current_time=NOW,
                )
                self.assertIn("account_strategy_action_invalid", issue_codes(issues))

    def test_briefing_rejects_empty_fixed_cells(self):
        body = """## 一句话判断
建议先核实客户任务与决策路径，依据 CLM-I-001。

## 会前必须知道
| 事实 | 类型与依据 | 业务意义 |
|---|---|---|
|  | F CLM-I-001 |  |

## 机会与边界
| 项目 | 当前判断 | 依据claim_id |
|---|---|---|
| Need |  | CLM-I-001 |
| Authority |  | CLM-I-001 |
| Budget/Procurement |  | CLM-I-001 |
| Competition |  | CLM-I-001 |
| 建议 |  | CLM-I-001 |

## 建议交流节奏
| 时间 | 议题/动作 | 目标信号 |
|---|---|---|
| 0—5分钟 |  |  |
| 5—20分钟 |  |  |
| 20—25分钟 |  |  |
| 25—30分钟 |  |  |

## 三个现场问题
1. 当前需要解决的核心任务是什么？
2. 谁负责预算与采购决策？
3. 下一步可以确认什么动作？

## 最小推进动作
- 动作：确认一次需求验证交流
- 依据claim_id：CLM-I-001
- Owner：账户负责人
- Due date：2026-09-26
- 红线：不得承诺未授权价格与效果

## 未决风险
预算、采购时序与正式责任角色仍需进一步确认。
"""
        briefing = VALIDATOR.Document(
            Path("/tmp/示例医院会前速览.md"),
            "",
            {
                "page_proxy": "markdown-one-page/v1",
                "module_status": "completed",
                "review_status": "pending",
                "delivery_state": "draft_for_review",
            },
            body,
        )
        issues: list[object] = []
        VALIDATOR.validate_briefing_contract(briefing, issues)
        codes = issue_codes(issues)
        self.assertIn("briefing_fact_content_invalid", codes)
        self.assertIn("briefing_opportunity_content_invalid", codes)
        self.assertIn("briefing_agenda_content_invalid", codes)

    def test_briefing_cannot_hide_the_delivery_inside_html_comments(self):
        briefing = VALIDATOR.Document(
            Path("/tmp/示例医院会前速览.md"),
            "",
            {
                "page_proxy": "markdown-one-page/v1",
                "module_status": "completed",
                "review_status": "pending",
                "delivery_state": "draft_for_review",
            },
            "<!--\n" + complete_briefing_body(include_agenda=True, complete_opportunity=True) + "\n-->",
        )
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                issues: list[object] = []
                VALIDATOR.validate_briefing_contract(briefing, issues)
                self.assertIn("briefing_html_comment_forbidden", issue_codes(issues))

    def test_standard_strategy_rejects_empty_shell_sections_and_embedded_crm_word(self):
        total = total_document(business_mode="standard_visit", route="visit_prep", depth="standard")
        strategy = keyword_only_standard_strategy()
        strategy.body = """## 目标与最小推进动作
已讨论。
## 机会资格
已讨论。
## 议程
已讨论。
## 参会分工
已讨论。
## 材料
已讨论。
## 会后行动
已讨论CRM/PIMS。
"""
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": strategy},
            issues,
            strict=False,
            current_time=NOW,
        )
        codes = issue_codes(issues)
        self.assertIn("presales_section_empty", codes)
        self.assertIn("presales_section_missing", codes)

    def test_scheduled_action_section_rejects_a_second_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "output")
            load_issues: list[object] = []
            documents = VALIDATOR.load_documents(workspace, load_issues)
            self.assertFalse([issue for issue in load_issues if issue.severity == "error"])
            strategy = next(
                document
                for document in documents
                if document.frontmatter.get("artifact_type") == "visit_strategy"
            )
            extra = """

| 阶段 | 内容 | 我方负责人 | 附件 |
|---|---|---|---|
| 开场 | 确认会议目标 | 客户负责人 | 产品演示 |
"""
            strategy.body = strategy.body.replace("\n## CRM/PIMS", extra + "\n## CRM/PIMS", 1)
            issues: list[object] = []
            VALIDATOR.validate_scheduled_strategy_sections(strategy, issues)
            self.assertIn("scheduled_strategy_structure_invalid", issue_codes(issues))

    def test_account_comprehensive_rejects_prose_and_renamed_meeting_tables(self):
        strategy = account_strategy(empty_actions=False)
        bodies = (
            """## 4.2 拜访执行与下一步
14:00开场，由客户负责人说明目标；14:10展示产品；信息中心主任和我方顾问出席。
""",
            """## 4.2 执行与下一步
| 时段 | 讨论主题 | 负责人 | 资料 | 目标 |
|---|---|---|---|---|
| 0—5分钟 | 开场 | 账户负责人 | 产品方案 | 确认目标 |
""",
        )
        for body in bodies:
            with self.subTest(body=body.splitlines()[0]):
                total = total_document(
                    business_mode="strategic_account",
                    route="strategy",
                    depth="deep",
                    strategy_variant="account_planning",
                    body=body,
                )
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=False,
                    current_time=NOW,
                )
                self.assertIn("account_comprehensive_structure_forbidden", issue_codes(issues))

    def test_account_full_report_rejects_untimed_meeting_table_three_times_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            load_issues: list[object] = []
            documents = VALIDATOR.load_documents(workspace, load_issues)
            self.assertFalse([issue for issue in load_issues if issue.severity == "error"])
            by_type = {document.frontmatter.get("artifact_type"): document for document in documents}
            total = by_type["comprehensive_report"]
            injected = """

## 5. 执行准备

| 阶段 | 讨论主题 | 客户角色 | 我方负责人 | 资料包 |
|---|---|---|---|---|
| 开局 | 对齐交流目标 | 信息中心主任 | 账户负责人 | 产品介绍 |
| 核心 | 讲解解决方案并收集反馈 | 信息中心主任 | 方案顾问 | 系统截图 |
| 收口 | 确认下次交流 | 信息中心主任 | 账户负责人 | 方案资料 |
"""
            original_body = total.body
            total.body = original_body + injected
            for attempt in range(3):
                with self.subTest(attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        by_type,
                        issues,
                        strict=False,
                        current_time=NOW,
                    )
                    self.assertIn(
                        "account_comprehensive_structure_forbidden",
                        issue_codes(issues),
                    )

            total.path.write_text(
                total.text.replace(original_body, total.body, 1),
                encoding="utf-8",
            )
            released = run_python(
                "validate_outputs.py",
                [str(workspace), "--profile", "release", "--json"],
            )
            self.assertEqual(released.returncode, 1, released.stderr or released.stdout)
            release_codes = {
                issue["code"] for issue in json.loads(released.stdout)["issues"]
            }
            self.assertIn("account_comprehensive_structure_forbidden", release_codes)

    def test_no_go_rejects_external_proposal_and_trial_actions_three_times(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        strategy = account_strategy(empty_actions=False)
        strategy.frontmatter["minimum_next_step"] = "观察项目窗口"
        strategy.body = strategy.body.replace("- 建议：monitor", "- 建议：no_go")
        strategy.body = strategy.body.replace("验证项目窗口 | observe", "观察项目窗口 | observe", 1)
        strategy.body = strategy.body.replace("核实预算窗口 | recheck", "提交产品方案给客户 | recheck", 1)
        strategy.body = strategy.body.replace("做出投入判断 | recheck", "邀请客户开展产品试用 | recheck", 1)
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=False,
                    current_time=NOW,
                )
                self.assertIn("account_strategy_no_go_conflict", issue_codes(issues))

    def test_letter_requires_separate_salutation_body_and_signature(self):
        internal = VALIDATOR.Document(
            Path("/tmp/示例医院客户信-内部待审核.md"),
            "",
            {
                "module_status": "completed",
                "review_status": "pending",
                "external_output_required": "true",
                "recipient_role": "信息中心主任",
                "letter_purpose": "说明本次需求验证交流背景",
                "expected_action": "确认一次需求验证交流",
                "signer": "客户负责人李明",
            },
            """`EXTERNAL_BODY_START`
信息中心主任确认一次需求验证交流客户负责人李明
`EXTERNAL_BODY_END`
""",
        )
        issues: list[object] = []
        VALIDATOR.validate_letter_isolation({"customer_letter_internal": internal}, issues)
        self.assertIn("letter_external_structure_invalid", issue_codes(issues))

    def test_letter_rejects_expected_action_characters_scattered_across_prose(self):
        internal = VALIDATOR.Document(
            Path("/tmp/示例医院客户信-内部待审核.md"),
            "",
            {
                "module_status": "completed",
                "review_status": "pending",
                "external_output_required": "true",
                "recipient_role": "信息中心主任",
                "letter_purpose": "说明本次需求验证交流背景",
                "expected_action": "确认一次需求验证交流",
                "signer": "客户负责人李明",
            },
            """`EXTERNAL_BODY_START`
信息中心主任，您好：
确有一些情况需要说明。认知需要长期积累，一线同事也有很多次讨论；需进一步了解客户求解过程并验看材料，证据需要证实后再交流。
客户负责人李明
`EXTERNAL_BODY_END`
""",
        )
        issues: list[object] = []
        VALIDATOR.validate_letter_isolation({"customer_letter_internal": internal}, issues)
        self.assertIn("letter_expected_action_missing", issue_codes(issues))

    def test_account_requires_investment_intensity_and_reason(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        strategy = account_strategy(empty_actions=False, omit_no_go_fields=True)
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": strategy},
            issues,
            strict=False,
            current_time=NOW,
        )
        self.assertIn("account_strategy_no_go_fields_invalid", issue_codes(issues))

    def test_standard_and_strategic_totals_require_decision_ready_core(self):
        for business_mode, route, depth in (
            ("standard_visit", "visit_prep", "standard"),
            ("strategic_account", "strategy", "deep"),
        ):
            with self.subTest(business_mode=business_mode):
                total = total_document(
                    business_mode=business_mode,
                    route=route,
                    depth=depth,
                    strategy_variant=("account_planning" if business_mode == "strategic_account" else None),
                    body="## 2. 任务上下文与成果状态\n状态表存在，但没有业务结论。\n",
                )
                strategy = account_strategy(empty_actions=False) if business_mode == "strategic_account" else keyword_only_standard_strategy()
                issues: list[object] = []
                VALIDATOR.validate_operating_governance(
                    {"comprehensive_report": total, "visit_strategy": strategy},
                    issues,
                    strict=False,
                    current_time=NOW,
                )
                self.assertIn("comprehensive_section_missing", issue_codes(issues))

    def test_account_action_section_rejects_a_second_renamed_meeting_table(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        strategy = account_strategy(empty_actions=False)
        second_table = """

| 阶段 | 内容 | 我方负责人 | 附件 |
|---|---|---|---|
| 开场 | 确认会议目标 | 账户负责人 | 产品演示 |
| 核心 | 讲解方案并邀请参会人反馈 | 方案顾问 | 方案简介 |
| 收口 | 确认下次会议 | 账户负责人 | 会议纪要 |
"""
        strategy.body = strategy.body.replace("\n## 验证计划", second_table + "\n## 验证计划")
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": strategy},
            issues,
            strict=False,
            current_time=NOW,
        )
        self.assertIn("account_strategy_action_invalid", issue_codes(issues))

    def test_account_no_go_rejects_advancement_action(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        strategy = account_strategy(empty_actions=False)
        strategy.body = strategy.body.replace("- 建议：monitor", "- 建议：no_go")
        strategy.body = strategy.body.replace("验证项目窗口 | observe", "继续推进项目窗口 | observe", 1)
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": strategy},
            issues,
            strict=False,
            current_time=NOW,
        )
        self.assertIn("account_strategy_no_go_conflict", issue_codes(issues))

    def test_account_empty_core_sections_are_not_a_completed_strategy(self):
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
        )
        issues: list[object] = []
        VALIDATOR.validate_operating_governance(
            {"comprehensive_report": total, "visit_strategy": account_strategy(empty_actions=False)},
            issues,
            strict=False,
            current_time=NOW,
        )
        self.assertIn("account_strategy_structure_invalid", issue_codes(issues))

    def test_comprehensive_requires_gcp_and_exactly_one_action_table(self):
        strategy = account_strategy(empty_actions=False)
        body = """## 决策摘要
| 核心问题 | 当前结论 | claim_id | 对业务决策的意义 |
|---|---|---|---|
| 客户主体 | 主体已经公开资料确认 | CLM-I-001 | 可以继续开展限定验证 |
| 责任角色 | 正式责任角色仍待确认 | CLM-I-001 | 应先核实决策结构边界 |
| 当前任务 | 核心业务任务仍待验证 | CLM-I-001 | 现阶段保持低投入验证 |

## 综合判断链
| 环节 | 判断 | claim_id | 反证/局限 | 置信度 | 验证问题或动作 |
|---|---|---|---|---|---|
| 发展阶段 | 当前建设阶段仍待客户确认 | CLM-I-001 | 公开资料没有当前项目阶段 | 中 | 核实当前建设阶段和任务 |
| 核心矛盾 | 当前业务矛盾仍待客户确认 | CLM-I-001 | 缺少客户正式需求材料 | 低 | 核实具体压力和目标结果 |
| 决策者关注 | 正式决策关注事项尚待核实 | CLM-I-001 | 不推断个人偏好与权限 | 低 | 确认正式责任角色和关注点 |
| 信息化支撑 | 先开展需求验证与边界澄清 | CLM-I-001 | 产品适配范围仍未验证 | 中 | 仅讨论已授权产品能力 |
| 最小推进动作 | 验证项目窗口 | CLM-I-001 | 依赖客户提供正式反馈 | 中 | 由账户负责人完成窗口复核 |

## 机会资格与投入建议
| 维度 | 当前判断 | claim_id | 缺口/验证问题 |
|---|---|---|---|
| Budget | 正式预算状态尚无可靠证据 | CLM-I-001 | 核实正式预算安排 |
| Authority | 正式决策角色尚待确认 | CLM-I-001 | 核实预算采购角色 |
| Need | 真实业务任务尚待确认 | CLM-I-001 | 核实任务目标结果 |
| Timing/采购时序 | 正式采购时序尚无证据 | CLM-I-001 | 核实审批采购窗口 |
| 竞争位置 | 当前竞争位置尚待确认 | CLM-I-001 | 核实存量供应商约束 |
- 建议：monitor
- 投入强度：低；依据：任务角色预算窗口仍待验证
- 继续投入的前提/停止条件：确认真实任务和正式责任角色；否则停止主动投入

## 执行与下一步
| action | action_disposition | external_interaction | resource_commitment | owner | due_date | 依赖 | 完成标准 | 继续/调整/no-go条件 | CRM/PIMS候选 |
|---|---|---|---|---|---|---|---|---|---|
| 验证项目窗口 | observe | customer_contact | none | 账户负责人 | 2026-09-26 | 客户确认反馈 | 形成书面窗口结论 | 无法确认时转为观察 | 是 |

| 阶段 | 内容 | 我方负责人 | 附件 |
|---|---|---|---|
| 开场 | 确认会议目标 | 账户负责人 | 产品演示 |
"""
        total = total_document(
            business_mode="strategic_account",
            route="strategy",
            depth="deep",
            strategy_variant="account_planning",
            body=body,
        )
        issues: list[object] = []
        VALIDATOR.validate_comprehensive_delivery_contract(total, strategy, issues)
        codes = issue_codes(issues)
        self.assertIn("comprehensive_section_missing", codes)
        self.assertIn("comprehensive_action_invalid", codes)

    def test_letter_three_line_action_shell_requires_context(self):
        internal = VALIDATOR.Document(
            Path("/tmp/示例医院客户信-内部待审核.md"),
            "",
            {
                "module_status": "completed",
                "review_status": "pending",
                "external_output_required": "true",
                "recipient_role": "信息中心主任",
                "letter_purpose": "说明本次需求验证交流背景",
                "expected_action": "确认一次需求验证交流",
                "signer": "客户负责人李明",
            },
            """`EXTERNAL_BODY_START`
信息中心主任，您好：
烦请确认一次需求验证交流。
客户负责人李明
`EXTERNAL_BODY_END`
""",
        )
        issues: list[object] = []
        VALIDATOR.validate_letter_isolation({"customer_letter_internal": internal}, issues)
        self.assertIn("letter_purpose_anchor_missing", issue_codes(issues))

    def test_letter_generic_context_sentence_cannot_replace_purpose(self):
        internal = VALIDATOR.Document(
            Path("/tmp/示例医院客户信-内部待审核.md"),
            "",
            {
                "module_status": "completed",
                "review_status": "pending",
                "external_output_required": "true",
                "recipient_role": "张主任，信息中心主任，身份已确认",
                "letter_purpose": "确认下一次技术交流安排",
                "expected_action": "确认九月技术交流时间",
                "signer": "王经理，客户负责人",
            },
            """`EXTERNAL_BODY_START`
张主任，您好：
相关事项已有相应记录。诚请您确认九月技术交流时间。
王经理
`EXTERNAL_BODY_END`
""",
        )
        issues: list[object] = []
        VALIDATOR.validate_letter_isolation({"customer_letter_internal": internal}, issues)
        self.assertIn("letter_purpose_anchor_missing", issue_codes(issues))

    def test_N102_briefing_core_sections_hidden_in_code_are_rejected_three_times(self):
        valid = complete_briefing_body(include_agenda=True, complete_opportunity=True)
        frontmatter = {
            "schema": "discovery-call-output/v2.5",
            "artifact_type": "briefing_delivery",
            "context_id": "dcx-20260827-abcdefgh",
            "latest_run_id": "dcr-20260827T120000-abcd",
            "customer_id": "customer-001",
            "customer_display_name": "示例医院",
            "organization_scope": "示例医院",
            "safe_name": "示例医院",
            "content_version": "1",
            "updated_at": "2026-08-27T12:00:00Z",
            "runtime_owner": "测试负责人",
            "connector_status": "not_applicable",
            "freshness_status": "current",
            "evidence_cutoff_date": "2026-08-27",
            "page_proxy": "markdown-one-page/v1",
            "module_status": "completed",
            "review_status": "pending",
            "delivery_state": "draft_for_review",
        }
        variants = {
            "fenced": f"```markdown\n{valid}\n```",
            "indented": "\n".join(
                ("    " + line) if line else line
                for line in valid.splitlines()
            ),
        }
        for name, body in variants.items():
            briefing = VALIDATOR.Document(
                Path("/tmp/示例医院会前速览.md"),
                "",
                dict(frontmatter),
                body,
            )
            for attempt in range(3):
                with self.subTest(variant=name, attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_briefing_contract(briefing, issues)
                    VALIDATOR.validate_frontmatter(briefing, issues, strict=False)
                    self.assertIn("briefing_section_invalid", issue_codes(issues))
                    self.assertIn("delivery_code_block_forbidden", issue_codes(issues))

    def test_N103_briefing_empty_links_cannot_hide_facts_claims_or_questions_three_times(self):
        valid = complete_briefing_body(include_agenda=True, complete_opportunity=True)
        variants = {
            "fact": valid.replace(
                "客户主体已确认",
                "[](客户主体已确认)",
                1,
            ),
            "claim": valid.replace("CLM-I-001", "[](CLM-I-001)", 1),
            "question": valid.replace(
                "当前最需要解决的业务问题是什么？",
                "[](当前最需要解决的业务问题是什么？)",
                1,
            ),
        }
        for name, body in variants.items():
            briefing = VALIDATOR.Document(
                Path("/tmp/示例医院会前速览.md"),
                "",
                {
                    "page_proxy": "markdown-one-page/v1",
                    "module_status": "completed",
                    "review_status": "pending",
                    "delivery_state": "draft_for_review",
                },
                body,
            )
            for attempt in range(3):
                with self.subTest(variant=name, attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_briefing_contract(briefing, issues)
                    self.assertIn("briefing_markdown_link_forbidden", issue_codes(issues))

    def test_N104_letter_hidden_negated_or_meta_contracts_are_rejected_three_times(self):
        visible = """\
张主任，您好：
感谢您此前围绕系统建设开展交流。
此次来函旨在确认下一次技术交流安排。
诚请您确认九月技术交流时间。
王经理"""
        variants = {
            "fenced": (
                f"```text\n{visible}\n```",
                "letter_external_markdown_forbidden",
            ),
            "indented": (
                "\n".join("    " + line for line in visible.splitlines()),
                "letter_external_markdown_forbidden",
            ),
            "empty_links": (
                """张主任，您好：
感谢您此前围绕系统建设开展交流。
[](确认下一次技术交流安排)
诚请您[](确认九月技术交流时间)。
王经理""",
                "letter_external_markdown_forbidden",
            ),
            "negated_action": (
                """张主任，您好：
感谢您此前围绕系统建设开展交流。
此次来函旨在确认下一次技术交流安排。
可否不确认九月技术交流时间。
王经理""",
                "letter_expected_action_missing",
            ),
            "purpose_metadata": (
                """张主任，您好：
感谢您此前围绕系统建设开展交流。
发信目的为确认下一次技术交流安排。
诚请您确认九月技术交流时间。
王经理""",
                "letter_purpose_meta_forbidden",
            ),
        }
        for name, (body, expected_code) in variants.items():
            letter = completed_letter(body)
            for attempt in range(3):
                with self.subTest(variant=name, attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_letter_isolation(
                        {"customer_letter_internal": letter},
                        issues,
                    )
                    self.assertIn(expected_code, issue_codes(issues))

    def test_N105_completed_artifacts_reject_html_cf_and_code_globally_three_times(self):
        payloads = {
            "html_comment": (
                "\n<!-- 影子行动：向客户提交方案 -->\n",
                "delivery_hidden_content_forbidden",
            ),
            "raw_html": (
                "\n<details><summary>补充</summary>影子行动</details>\n",
                "delivery_hidden_content_forbidden",
            ),
            "format_character": (
                "\n内部复核\u200b机会资格。\n",
                "invisible_format_character_forbidden",
            ),
            "fenced_code": (
                "\n```text\n影子行动：向客户提交方案\n```\n",
                "delivery_code_block_forbidden",
            ),
            "indented_code": (
                "\n    影子行动：向客户提交方案\n",
                "delivery_code_block_forbidden",
            ),
        }
        for business_mode in ("standard_visit", "strategic_account"):
            with tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode=business_mode,
                )
                by_type = loaded_by_type(workspace)
                for artifact_type in ("comprehensive_report", "visit_strategy"):
                    original = by_type[artifact_type]
                    for name, (suffix, expected_code) in payloads.items():
                        mutated = VALIDATOR.Document(
                            original.path,
                            original.text,
                            dict(original.frontmatter),
                            original.body + suffix,
                        )
                        for attempt in range(3):
                            with self.subTest(
                                business_mode=business_mode,
                                artifact_type=artifact_type,
                                payload=name,
                                attempt=attempt,
                            ):
                                issues: list[object] = []
                                VALIDATOR.validate_frontmatter(mutated, issues, strict=False)
                                self.assertIn(expected_code, issue_codes(issues))

                total = by_type["comprehensive_report"]
                write_mutated_body(total, total.body + payloads["html_comment"][0])
                self.assert_cli_profiles_reject(
                    workspace,
                    "delivery_hidden_content_forbidden",
                )

    def test_N106_scheduled_shadow_actions_in_allowed_h2_or_h3_are_rejected_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "output")
            strategy = loaded_by_type(workspace)["visit_strategy"]
            renamed_table = """

| 步骤 | 交流事项 | 对方人员 | 本方人员 | 携带物 |
|---|---|---|---|---|
| 开始 | 说明解决办法 | 信息中心主任 | 方案顾问 | 产品资料 |
"""
            numbered_h3 = """

### 追加推进
1. 向客户提交解决办法并安排试用
"""
            variants = {
                "renamed_table_in_allowed_h2": strategy.body.replace(
                    "\n## CRM/PIMS",
                    renamed_table + "\n## CRM/PIMS",
                    1,
                ),
                "numbered_action_under_h3": strategy.body.replace(
                    "\n## CRM/PIMS",
                    numbered_h3 + "\n## CRM/PIMS",
                    1,
                ),
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    strategy.path,
                    strategy.text,
                    dict(strategy.frontmatter),
                    body,
                )
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_scheduled_strategy_sections(mutated, issues)
                        self.assertIn(
                            "scheduled_strategy_structure_invalid",
                            issue_codes(issues),
                        )

            write_mutated_body(strategy, variants["renamed_table_in_allowed_h2"])
            self.assert_cli_profiles_reject(
                workspace,
                "scheduled_strategy_structure_invalid",
            )

    def test_N107_standard_total_rejects_extra_h2_renamed_shadow_action_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(Path(temporary) / "output")
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            shadow = """

## 5. 补充推进

| 事项 | 状态动作 | 责任角色 | 日期 | 完成信号 |
|---|---|---|---|---|
| 安排客户试用 | 继续实施 | 账户负责人 | 2026-09-30 | 客户进入测试环境 |
"""
            mutated = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                total.body + shadow,
            )
            mutated_map = dict(by_type)
            mutated_map["comprehensive_report"] = mutated
            for attempt in range(3):
                with self.subTest(attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        mutated_map,
                        issues,
                        strict=False,
                        current_time=NOW,
                    )
                    self.assertIn(
                        "comprehensive_structure_forbidden",
                        issue_codes(issues),
                    )

            write_mutated_body(total, mutated.body)
            self.assert_cli_profiles_reject(
                workspace,
                "comprehensive_structure_forbidden",
            )

    def test_N108_account_strategy_rejects_h2_h3_and_renamed_meeting_tables_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            strategy = by_type["visit_strategy"]
            meeting_table = """

| 环节 | 内容 | 人员 | 物件 |
|---|---|---|---|
| 开场 | 说明解决办法 | 信息中心主任 | 产品资料 |
| 核心 | 展示方案并收集反馈 | 方案顾问 | 系统截图 |
| 收口 | 安排下次交流 | 账户负责人 | 方案资料 |
"""
            variants = {
                "extra_h2": strategy.body + "\n## 执行准备\n" + meeting_table,
                "extra_h3": strategy.body.replace(
                    "\n## 验证计划",
                    "\n### 执行准备\n" + meeting_table + "\n## 验证计划",
                    1,
                ),
                "renamed_table_in_allowed_h2": strategy.body.replace(
                    "\n## 验证计划",
                    meeting_table + "\n## 验证计划",
                    1,
                ),
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    strategy.path,
                    strategy.text,
                    dict(strategy.frontmatter),
                    body,
                )
                mutated_map = dict(by_type)
                mutated_map["visit_strategy"] = mutated
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                        )
                        self.assertIn(
                            "account_strategy_structure_invalid",
                            issue_codes(issues),
                        )

            write_mutated_body(strategy, variants["extra_h2"])
            self.assert_cli_profiles_reject(
                workspace,
                "account_strategy_structure_invalid",
            )

    def test_N109_no_go_free_text_and_cf_bypasses_are_rejected_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            original = by_type["visit_strategy"]
            frontmatter, base_body = controlled_no_go_strategy(original)
            variants = {
                "deliver_solution": base_body.replace(
                    "被动观察证据变化 | observe",
                    "复核后向客户交付解决办法 | observe",
                    1,
                ),
                "enter_test_environment": base_body.replace(
                    "被动观察证据变化 | observe",
                    "检查后安排客户进入测试环境 | observe",
                    1,
                ),
                "zero_width": base_body.replace(
                    "内部复核机会资格 | recheck",
                    "内部复核\u200b机会资格 | recheck",
                    1,
                ),
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    original.path,
                    original.text,
                    dict(frontmatter),
                    body,
                )
                mutated_map = dict(by_type)
                mutated_map["visit_strategy"] = mutated
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                        )
                        VALIDATOR.validate_frontmatter(mutated, issues, strict=False)
                        codes = issue_codes(issues)
                        self.assertIn("account_strategy_no_go_conflict", codes)
                        if name == "zero_width":
                            self.assertIn("invisible_format_character_forbidden", codes)

    def test_N110_letter_vacuous_purpose_and_action_block_preflight_and_direct_three_times(self):
        variants = {
            "letter_purpose": ("相关事项已说明", True),
            "expected_action": ("相关事项已完成", False),
        }

        def payload_with(field: str, value: str) -> dict[str, object]:
            values = {
                "customer_name": "甲医院",
                "organization_scope": "甲医院",
                "recipient_role": "信息中心主任",
                "letter_scenario": "拜访后正式跟进",
                "letter_purpose": "确认下一次技术交流安排",
                "expected_action": "确认九月技术交流时间",
                "signer": "战略咨询部",
                "delivery_channel": "正式邮件",
            }
            values[field] = value
            return {
                "schema": "discovery-call-intake/v1",
                "request_id": f"req-{field}",
                "business_mode": "letter",
                "candidate_sets": [
                    {
                        "field": name,
                        "candidates": [
                            {
                                "candidate_id": f"{name}-1",
                                "value": item,
                                "status": "asserted",
                                "source_ref": "test:user-turn:1",
                            }
                        ],
                    }
                    for name, item in values.items()
                ],
                "confirmations": [],
            }

        for field, (value, purpose) in variants.items():
            for attempt in range(3):
                with self.subTest(field=field, surface="direct", attempt=attempt):
                    self.assertFalse(
                        PREFLIGHT.substantive_letter_field(value, purpose=purpose)
                    )
                with self.subTest(field=field, surface="preflight", attempt=attempt):
                    result = PREFLIGHT.evaluate_intake(
                        payload_with(field, value),
                        now=NOW,
                    )
                    self.assertEqual(result["status"], "blocked")
                    matching = [
                        item
                        for item in result["missing_requirements"]
                        if item["field"] == field
                    ]
                    self.assertTrue(matching)
                    self.assertEqual(
                        {item["code"] for item in matching},
                        {"required_value_non_substantive"},
                    )

    def test_N111_no_go_dependency_scenario_verification_and_crm_smuggling_fails_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            original = by_type["visit_strategy"]
            total = by_type["comprehensive_report"]
            frontmatter, base_body = controlled_no_go_strategy(original)
            base = VALIDATOR.Document(
                original.path,
                original.text,
                dict(frontmatter),
                base_body,
            )
            base_map = dict(by_type)
            base_map["visit_strategy"] = base
            base_map["comprehensive_report"] = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                controlled_no_go_total(total),
            )
            action_outcomes = {
                "stop": ("停止主动投入", "no_go_recorded", "reopen_internal_review"),
                "archive": ("归档当前机会", "opportunity_archived", "reopen_internal_review"),
                "observe": ("被动观察证据变化", "evidence_watch_recorded", "archive_if_unchanged"),
                "recheck": ("内部复核机会资格", "qualification_review_recorded", "keep_no_go_if_unresolved"),
            }
            for attempt in range(3):
                with self.subTest(surface="controlled_baseline", attempt=attempt):
                    baseline_issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        base_map,
                        baseline_issues,
                        strict=False,
                        current_time=NOW,
                    )
                    self.assertFalse(
                        [issue for issue in baseline_issues if issue.severity == "error"]
                    )
                    for disposition, (action, completion, trigger) in action_outcomes.items():
                        self.assertTrue(
                            VALIDATOR.no_go_action_semantics_valid(
                                disposition,
                                action,
                                "账户负责人",
                                "内部复核",
                                completion,
                                trigger,
                                "none",
                                "none",
                            )
                        )

            variants = {
                "dependency": base_body.replace(
                    "| 内部复核 | qualification_review_recorded |",
                    "| 客户确认方案 | qualification_review_recorded |",
                    1,
                ),
                "scenario": base_body.replace(
                    "| 内部复核机会资格 | 账户负责人 | 2026-10-25 |",
                    "| 安排客户进入测试环境 | 账户负责人 | 2026-10-25 |",
                    1,
                ),
                "verification": base_body.replace(
                    "| unknown | 内部复核机会资格 | internal_evidence |",
                    "| unknown | 向客户交付解决办法 | internal_evidence |",
                    1,
                ),
                "crm": base_body.replace(
                    "| action | 内部复核机会资格 | 建议 |",
                    "| action | 邀请客户开展试用 | 建议 |",
                    1,
                ),
            }
            for name, body in variants.items():
                self.assertNotEqual(body, base_body, name)
                mutated = VALIDATOR.Document(
                    original.path,
                    original.text,
                    dict(frontmatter),
                    body,
                )
                mutated_map = dict(by_type)
                mutated_map["visit_strategy"] = mutated
                for attempt in range(3):
                    with self.subTest(surface=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                        )
                        self.assertIn(
                            "account_strategy_no_go_conflict",
                            issue_codes(issues),
                        )

    def test_N112_total_governance_fields_cannot_be_smuggled_in_allowed_h2_h3_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            wrong_parent = """

## 5. 高价值发现

- ready_for_use：true
"""
            smuggled_values = """

## 6. 异常审核队列

| 审核项 | 类型 | 待审核内容 | claim_id/source_id | 风险 | runtime_owner | 审核结论 |
|---|---|---|---|---|---|---|
| REV-001 | 承诺 | 投入边界待审核 | CLM-I-001 | 资源误判 | 测试负责人 | pending |

### 可用状态

- ready_for_use：true
- 必要审核人：商务审核岗；立即安排演示
- review_due_at：下周
- 未通过原因/解除条件：无；邀请客户试用
"""
            variants = {
                "allowed_h2_wrong_parent": total.body + wrong_parent,
                "allowed_h3_smuggled_values": total.body + smuggled_values,
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    total.path,
                    total.text,
                    dict(total.frontmatter),
                    body,
                )
                mutated_map = dict(by_type)
                mutated_map["comprehensive_report"] = mutated
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                        )
                        self.assertIn(
                            "account_comprehensive_structure_forbidden",
                            issue_codes(issues),
                        )

            write_mutated_body(total, variants["allowed_h3_smuggled_values"])
            self.assert_cli_profiles_reject(
                workspace,
                "account_comprehensive_structure_forbidden",
            )

    def test_N113_high_value_findings_cannot_launder_claims_or_meeting_sequences_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            ledger_issues: list[object] = []
            claims, sources = VALIDATOR.collect_ledgers(
                list(by_type.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            prefix = """

## 5. 高价值发现

| 序号 | claim_id | claim_type | provenance | 发现 | impact_type | 业务影响 | 置信度 |
|---|---|---|---|---|---|---|---|
"""
            variants = {
                "claim_laundering": (
                    total.body
                    + prefix
                    + "| 1 | CLM-I-001 | F2 | public | 客户已确认项目预算 | decision | 可以直接进入投标决策 | 高 |\n",
                    "comprehensive_finding_claim_mismatch",
                ),
                "meeting_sequence": (
                    total.body
                    + prefix
                    + "| 1 | CLM-I-001 | F | public | 示例医院为本次研究主体 | decision | 开场介绍方案，收口确认下次交流的投入决策 | 高 |\n",
                    "account_comprehensive_structure_forbidden",
                ),
            }
            for name, (body, expected_code) in variants.items():
                mutated = VALIDATOR.Document(
                    total.path,
                    total.text,
                    dict(total.frontmatter),
                    body,
                )
                mutated_map = dict(by_type)
                mutated_map["comprehensive_report"] = mutated
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                            claims=claims,
                            sources=sources,
                        )
                        self.assertIn(expected_code, issue_codes(issues))

            write_mutated_body(total, variants["claim_laundering"][0])
            self.assert_cli_profiles_reject(
                workspace,
                "comprehensive_finding_claim_mismatch",
            )

    def test_N114_no_go_owner_cells_cannot_smuggle_actions_or_unbound_names_three_times(self):
        owners = (
            "向客户提交产品方案的账户负责人",
            "账户负责人负责把材料交给客户",
            "张主任",
        )
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            strategy = by_type["visit_strategy"]
            total = by_type["comprehensive_report"]
            strategy_frontmatter, strategy_body = controlled_no_go_strategy(strategy)
            total_body = controlled_no_go_total(total)
            controlled_strategy = VALIDATOR.Document(
                strategy.path,
                strategy.text,
                strategy_frontmatter,
                strategy_body,
            )
            controlled_total = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                total_body,
            )
            controlled_map = dict(by_type)
            controlled_map["visit_strategy"] = controlled_strategy
            controlled_map["comprehensive_report"] = controlled_total
            for attempt in range(3):
                with self.subTest(owner="controlled_baseline", attempt=attempt):
                    baseline_issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        controlled_map,
                        baseline_issues,
                        strict=False,
                        current_time=NOW,
                    )
                    self.assertFalse(
                        [issue for issue in baseline_issues if issue.severity == "error"]
                    )

            for owner in owners:
                strategy_variant = strategy_body.replace(
                    "| none | none | 账户负责人 | 2026-09-25 | 内部复核 |",
                    f"| none | none | {owner} | 2026-09-25 | 内部复核 |",
                    1,
                )
                total_variant = total_body.replace(
                    "| none | none | 账户负责人 | 2026-09-25 | 内部复核 |",
                    f"| none | none | {owner} | 2026-09-25 | 内部复核 |",
                    1,
                )
                self.assertNotEqual(strategy_variant, strategy_body, owner)
                self.assertNotEqual(total_variant, total_body, owner)
                for surface, body, expected_code in (
                    ("strategy", strategy_variant, "account_strategy_no_go_conflict"),
                    ("total", total_variant, "comprehensive_no_go_conflict"),
                ):
                    mutated_map = dict(controlled_map)
                    if surface == "strategy":
                        mutated_map["visit_strategy"] = VALIDATOR.Document(
                            strategy.path,
                            strategy.text,
                            dict(strategy_frontmatter),
                            body,
                        )
                    else:
                        mutated_map["comprehensive_report"] = VALIDATOR.Document(
                            total.path,
                            total.text,
                            dict(total.frontmatter),
                            body,
                        )
                    for attempt in range(3):
                        with self.subTest(owner=owner, surface=surface, attempt=attempt):
                            issues: list[object] = []
                            VALIDATOR.validate_operating_governance(
                                mutated_map,
                                issues,
                                strict=False,
                                current_time=NOW,
                            )
                            self.assertIn(expected_code, issue_codes(issues))

    def test_N115_high_value_synonym_execution_plan_is_rejected_three_times_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            ledger_issues: list[object] = []
            claims, sources = VALIDATOR.collect_ledgers(
                list(by_type.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            finding = """

## 5. 高价值发现

| 序号 | claim_id | claim_type | provenance | 发现 | impact_type | 业务影响 | 置信度 |
|---|---|---|---|---|---|---|---|
| 1 | CLM-I-001 | F | public | 示例医院为本次研究主体 | decision | 可据此判断王经理负责同张主任对齐目标并准备后续安排 | 高 |
"""
            mutated = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                total.body + finding,
            )
            mutated_map = dict(by_type)
            mutated_map["comprehensive_report"] = mutated
            for attempt in range(3):
                with self.subTest(attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        mutated_map,
                        issues,
                        strict=False,
                        current_time=NOW,
                        claims=claims,
                        sources=sources,
                    )
                    self.assertIn(
                        "comprehensive_finding_claim_mismatch",
                        issue_codes(issues),
                    )

            write_mutated_body(total, mutated.body)
            self.assert_cli_profiles_reject(
                workspace,
                "comprehensive_finding_claim_mismatch",
            )

    def test_N116_legacy_gap_tables_and_synonym_plans_fail_while_typed_table_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            ledger_issues: list[object] = []
            claims, _sources = VALIDATOR.collect_ledgers(
                list(by_type.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            legacy_header = """

## 7. 关键缺口与验证计划

| 缺口 | 优先级 | 待核实事项 | 影响 | 验证方式 | 责任角色/时点 |
|---|---|---|---|---|---|
"""
            variants = {
                "legacy_six_columns": (
                    total.body
                    + legacy_header
                    + "| 责任角色待核实 | 高 | 确认正式责任角色 | 影响机会判断 | 内部复核 | 账户负责人/2026-09-30 |\n"
                ),
                "synonym_customer_plan": (
                    total.body
                    + legacy_header
                    + "| 交流边界待核实 | 高 | 同王经理核对安排并把资料交给张主任 | 影响资源决策 | 共同确认 | 账户负责人/2026-09-30 |\n"
                ),
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    total.path,
                    total.text,
                    dict(total.frontmatter),
                    body,
                )
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_account_comprehensive_contract(
                            mutated,
                            set(),
                            set(),
                            issues,
                            claims=claims,
                        )
                        self.assertIn(
                            "account_comprehensive_structure_forbidden",
                            issue_codes(issues),
                        )

            typed_gap = """

## 7. 关键缺口与验证计划

| claim_ref | claim_type_ref | provenance_ref | evidence_state | impact_type | verification_mode | owner | due_date |
|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | insufficient | verification | authorized_customer_contact | 账户负责人 | 2026-09-30 |
"""
            positive = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                total.body + typed_gap,
            )
            for attempt in range(3):
                with self.subTest(variant="typed_positive", attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_account_comprehensive_contract(
                        positive,
                        set(),
                        set(),
                        issues,
                        claims=claims,
                    )
                    codes = issue_codes(issues)
                    self.assertNotIn("comprehensive_gap_contract_invalid", codes)
                    self.assertNotIn("account_comprehensive_structure_forbidden", codes)

            write_mutated_body(total, variants["synonym_customer_plan"])
            self.assert_cli_profiles_reject(
                workspace,
                "account_comprehensive_structure_forbidden",
            )

    def test_N117_strategy_review_mirrors_fail_and_canonical_release_passes_three_times(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            strategy = loaded_by_type(workspace)["visit_strategy"]
            profiles = VALIDATOR.load_business_profiles([])
            contract = VALIDATOR.strategy_variant_contract(
                "strategic_account",
                "account_planning",
                profiles=profiles,
            )
            self.assertIsNotNone(contract)
            legacy_review_status = """- strategy_variant：account_planning
- review_status：pending
- reviewer：待定
- reviewed_at：待审核
- ready_for_use：true
- review_due_at：2026-09-30T12:00:00+08:00
- 未通过原因/解除条件：审核通过后立即安排客户试用
"""
            variants = {
                "legacy_review_h2": (
                    strategy.body
                    + "\n## 审核与可用状态\n\n"
                    + legacy_review_status
                ),
                "nested_ready_h3": (
                    strategy.body
                    + "\n### 可用状态\n\n"
                    + "- ready_for_use：true\n"
                    + "- 解除条件：审核通过后立即安排客户试用\n"
                ),
            }
            for name, body in variants.items():
                mutated = VALIDATOR.Document(
                    strategy.path,
                    strategy.text,
                    dict(strategy.frontmatter),
                    body,
                )
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_account_action_contract(
                            mutated,
                            contract,
                            issues,
                        )
                        self.assertIn(
                            "account_strategy_structure_invalid",
                            issue_codes(issues),
                        )

        def govern(workspace: Path, *arguments: str) -> dict[str, object]:
            result = run_python(
                "validate_outputs.py",
                [str(workspace), *arguments, "--json"],
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["errors"], 0, payload)
            return payload

        for repetition in range(1, 4):
            with self.subTest(variant="canonical_release", repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                govern(workspace, "--profile", "candidate")

                record_action_assertion(
                    workspace,
                    event_id="approve-institution",
                    actor_id="reviewer-institution",
                    operation="approve_artifact:institution",
                    artifact_type="institution_research",
                )
                govern(
                    workspace,
                    "--approve-artifact",
                    "institution",
                    "--reviewer",
                    "周洁（机构事实审核岗）",
                    "--actor-id",
                    "reviewer-institution",
                    "--action-event-id",
                    "approve-institution",
                )

                record_action_assertion(
                    workspace,
                    event_id="approve-leader",
                    actor_id="reviewer-leader",
                    operation="approve_artifact:leader",
                    artifact_type="leader_research",
                )
                govern(
                    workspace,
                    "--approve-artifact",
                    "leader",
                    "--reviewer",
                    "孙宁（人物事实审核岗）",
                    "--actor-id",
                    "reviewer-leader",
                    "--action-event-id",
                    "approve-leader",
                )

                record_action_assertion(
                    workspace,
                    event_id="approve-strategy",
                    actor_id="reviewer-strategy",
                    operation="approve_artifact:strategy",
                    artifact_type="visit_strategy",
                )
                govern(
                    workspace,
                    "--approve-artifact",
                    "strategy",
                    "--reviewer",
                    "钱琳（拜访策略审核岗）",
                    "--actor-id",
                    "reviewer-strategy",
                    "--action-event-id",
                    "approve-strategy",
                )

                record_action_assertion(
                    workspace,
                    event_id="ready-strategic",
                    actor_id="ready-strategic",
                    operation="mark_ready:strategic_account",
                    artifact_type="comprehensive_report",
                )
                govern(
                    workspace,
                    "--mark-ready",
                    "--reviewer",
                    "刘宁（战略账户责任岗）",
                    "--actor-id",
                    "ready-strategic",
                    "--action-event-id",
                    "ready-strategic",
                )
                released = govern(workspace, "--profile", "release")
                self.assertEqual(released["validation_profile"], "release")

                by_type = loaded_by_type(workspace)
                released_strategy = by_type["visit_strategy"]
                released_total = by_type["comprehensive_report"]
                self.assertEqual(released_strategy.frontmatter["review_status"], "approved")
                self.assertEqual(released_total.frontmatter["ready_for_use"], "true")
                self.assertNotRegex(
                    released_strategy.body,
                    r"(?m)^#{2,6}\s+.*(?:审核|可用状态)",
                )
                self.assertNotRegex(
                    released_strategy.body,
                    r"(?m)^\s*[-*+]\s+(?:review_status|ready_for_use|未通过原因/解除条件)：",
                )

    def test_N118_no_go_total_decision_synonym_customer_plan_fails_three_times_and_release(self):
        smuggled_row = (
            "| 当前任务 | 可据此判断王经理负责同张主任对齐目标并提交产品方案 "
            "| CLM-I-001 | maintain_no_go |"
        )
        original_row = (
            "| 当前任务 | insufficient_evidence | CLM-I-001 | maintain_no_go |"
        )
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            strategy = by_type["visit_strategy"]
            total = by_type["comprehensive_report"]
            strategy_frontmatter, strategy_body = controlled_no_go_strategy(strategy)
            total_body = controlled_no_go_total(total)
            mutated_body = total_body.replace(original_row, smuggled_row, 1)
            self.assertNotEqual(mutated_body, total_body)
            controlled_map = dict(by_type)
            controlled_map["visit_strategy"] = VALIDATOR.Document(
                strategy.path,
                strategy.text,
                strategy_frontmatter,
                strategy_body,
            )
            controlled_map["comprehensive_report"] = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                mutated_body,
            )
            ledger_issues: list[object] = []
            claims, sources = VALIDATOR.collect_ledgers(
                list(controlled_map.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            for attempt in range(3):
                with self.subTest(surface="direct", attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_operating_governance(
                        controlled_map,
                        issues,
                        strict=False,
                        current_time=NOW,
                        claims=claims,
                        sources=sources,
                    )
                    self.assertIn(
                        "comprehensive_no_go_contract_invalid",
                        issue_codes(issues),
                    )

            install_controlled_no_go_workspace(workspace)
            total = loaded_by_type(workspace)["comprehensive_report"]
            release_body = total.body.replace(original_row, smuggled_row, 1)
            self.assertNotEqual(release_body, total.body)
            write_mutated_body(total, release_body)
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
            self.assert_cli_profiles_reject(
                workspace,
                "comprehensive_no_go_contract_invalid",
            )

        for repetition in range(1, 4):
            with self.subTest(surface="canonical_release", repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                install_controlled_no_go_workspace(workspace)
                released = self.complete_strategic_release(workspace)
                self.assertEqual(released["validation_profile"], "release")
                by_type = loaded_by_type(workspace)
                total = by_type["comprehensive_report"]
                self.assertEqual(total.frontmatter["ready_for_use"], "true")
                self.assertIn("- 建议：no_go", total.body)
                self.assertIn("| CLM-I-001 | F | public |", total.body)
                self.assertIn("| risk | internal_review |", total.body)
                self.assertNotIn("## 主张与来源导航", total.body)

    def test_no_go_total_optional_sections_remain_closed_three_times(self):
        valid_navigation = """

## 主张与来源导航

| 序号 | claim_id | artifact_type | usage_code |
|---|---|---|---|
| 1 | CLM-I-001 | institution_research | decision_summary |

| 序号 | source_id | artifact_type | source_status |
|---|---|---|---|
| 1 | SRC-I-001 | institution_research | current |
"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            strategy = by_type["visit_strategy"]
            total = by_type["comprehensive_report"]
            strategy_frontmatter, strategy_body = controlled_no_go_strategy(strategy)
            total_body = controlled_no_go_total(total)
            base_map = dict(by_type)
            base_map["visit_strategy"] = VALIDATOR.Document(
                strategy.path,
                strategy.text,
                strategy_frontmatter,
                strategy_body,
            )
            ledger_issues: list[object] = []
            claims, sources = VALIDATOR.collect_ledgers(
                list(base_map.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            variants = {
                "non_fact_finding": total_body.replace(
                    "| 1 | CLM-I-001 | F | public |",
                    "| 1 | CLM-I-001 | H | public |",
                    1,
                ),
                "customer_contact_gap": total_body.replace(
                    "| risk | internal_review |",
                    "| risk | authorized_customer_contact |",
                    1,
                ),
                "navigation_forbidden": total_body + valid_navigation,
            }
            for name, body in variants.items():
                self.assertNotEqual(body, total_body, name)
                mutated_map = dict(base_map)
                mutated_map["comprehensive_report"] = VALIDATOR.Document(
                    total.path,
                    total.text,
                    dict(total.frontmatter),
                    body,
                )
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_operating_governance(
                            mutated_map,
                            issues,
                            strict=False,
                            current_time=NOW,
                            claims=claims,
                            sources=sources,
                        )
                        self.assertIn(
                            "comprehensive_no_go_contract_invalid",
                            issue_codes(issues),
                        )

    def test_N119_total_free_text_legacy_tables_and_raci_smuggling_fail_three_times(self):
        raci = """

### 2.1 本次RACI与审核SLA

| 角色 | 姓名（稳定角色/账号） | 本次责任 | 截止时间/状态 |
|---|---|---|---|
| account_owner | 账户负责人 | account_decision | pending |
| runtime_owner | 运行负责人 | research_execution | 2026-09-30 |
| evidence_reviewer | 证据负责人 | evidence_review | pending |
| commercial_reviewer | 商务审核岗 | commercial_review | pending |
| external_approver | not_applicable | external_approval | not_applicable |
| authorization_owner | 账户负责人 | data_authorization | pending |
"""
        review_queue = """

## 6. 异常审核队列

| review_id | review_type | claim_or_source_ref | risk_code | owner | review_status |
|---|---|---|---|---|---|
| REV-001 | low_confidence | CLM-I-001 | decision_risk | 证据负责人 | pending |
"""
        typed_gap = """

## 7. 关键缺口与验证计划

| claim_ref | claim_type_ref | provenance_ref | evidence_state | impact_type | verification_mode | owner | due_date |
|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | insufficient | verification | internal_review | 账户负责人 | 2026-09-30 |
"""
        navigation = """

## 主张与来源导航

| 序号 | claim_id | artifact_type | usage_code |
|---|---|---|---|
| 1 | CLM-I-001 | institution_research | decision_summary |

| 序号 | source_id | artifact_type | source_status |
|---|---|---|---|
| 1 | SRC-I-001 | institution_research | current |
"""
        legacy_review = """

## 6. 异常审核队列

| 审核项 | 类型 | 待审核内容 | claim_id/source_id | 风险 | runtime_owner | 审核结论 |
|---|---|---|---|---|---|---|
| REV-001 | 承诺 | 向张主任提交产品方案 | CLM-I-001 | 资源误判 | 账户负责人 | pending |
"""
        legacy_navigation = """

## 主张与来源导航

| 序号 | 判断/事实 | claim_id | source_id | 用途 |
|---|---|---|---|---|
| 1 | 由账户负责人联系张主任并提交产品材料 | CLM-I-001 | SRC-I-001 | 下次交流 |
"""
        with tempfile.TemporaryDirectory() as temporary:
            workspace = build_pending_strategy_workspace(
                Path(temporary) / "output",
                business_mode="strategic_account",
            )
            by_type = loaded_by_type(workspace)
            total = by_type["comprehensive_report"]
            ledger_issues: list[object] = []
            claims, _sources = VALIDATOR.collect_ledgers(
                list(by_type.values()),
                ledger_issues,
            )
            self.assertFalse(
                [issue for issue in ledger_issues if issue.severity == "error"]
            )
            raci_body = total.body.replace(
                "\n## 3. 综合判断链",
                raci + "\n## 3. 综合判断链",
                1,
            )
            self.assertNotEqual(raci_body, total.body)
            positive_body = raci_body + review_queue + typed_gap + navigation
            positive = VALIDATOR.Document(
                total.path,
                total.text,
                dict(total.frontmatter),
                positive_body,
            )
            for attempt in range(3):
                with self.subTest(variant="typed_positive", attempt=attempt):
                    issues: list[object] = []
                    VALIDATOR.validate_account_comprehensive_contract(
                        positive,
                        set(),
                        set(),
                        issues,
                        claims=claims,
                    )
                    self.assertFalse(
                        [issue for issue in issues if issue.severity == "error"]
                    )

            smuggled_raci = raci.replace(
                "| account_owner | 账户负责人 | account_decision | pending |",
                "| account_owner | 账户负责人 | 向张主任提交产品方案 | pending |",
                1,
            )
            variants = {
                "gap_trailing_free_text": (
                    total.body
                    + typed_gap
                    + "\n会后由账户负责人同张主任对齐安排，并把方案材料交给客户。\n"
                ),
                "legacy_review_table": total.body + legacy_review,
                "legacy_navigation_table": total.body + legacy_navigation,
                "raci_responsibility_smuggling": total.body.replace(
                    "\n## 3. 综合判断链",
                    smuggled_raci + "\n## 3. 综合判断链",
                    1,
                ),
            }
            for name, body in variants.items():
                self.assertNotEqual(body, total.body, name)
                mutated = VALIDATOR.Document(
                    total.path,
                    total.text,
                    dict(total.frontmatter),
                    body,
                )
                for attempt in range(3):
                    with self.subTest(variant=name, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_account_comprehensive_contract(
                            mutated,
                            set(),
                            set(),
                            issues,
                            claims=claims,
                        )
                        self.assertIn(
                            "account_comprehensive_structure_forbidden",
                            issue_codes(issues),
                        )

    def test_N120_complete_negated_letter_is_blocked_atomically_across_lifecycle_three_times(self):
        negated_external_body = """非张主任：
感谢您此前的交流。
本函并非旨在确认下一次技术交流安排。
请勿确认九月技术交流时间。
此信并非王经理签署。"""
        expected_letter_codes = {
            "letter_external_structure_invalid",
            "letter_expected_action_missing",
            "letter_purpose_anchor_missing",
        }

        direct_letter = completed_letter(negated_external_body)
        for attempt in range(3):
            with self.subTest(surface="direct", attempt=attempt):
                issues: list[object] = []
                VALIDATOR.validate_letter_isolation(
                    {"customer_letter_internal": direct_letter},
                    issues,
                )
                self.assertTrue(
                    expected_letter_codes.issubset(issue_codes(issues))
                )

        def install_negated_body(workspace: Path) -> None:
            letter = loaded_by_type(workspace)["customer_letter_internal"]
            mutated_body = re.sub(
                r"(?ms)(`EXTERNAL_BODY_START`\s*\n).*?(\n`EXTERNAL_BODY_END`)",
                lambda match: (
                    match.group(1)
                    + negated_external_body
                    + match.group(2)
                ),
                letter.body,
                count=1,
            )
            self.assertNotEqual(mutated_body, letter.body)
            write_mutated_body(letter, mutated_body)
            _rebuild_manifest(workspace, ["institution", "letter"])

        def file_snapshot(workspace: Path) -> dict[str, bytes]:
            return {
                path.relative_to(workspace).as_posix(): path.read_bytes()
                for path in sorted(workspace.rglob("*"))
                if path.is_file()
            }

        def assert_safe_state(workspace: Path) -> None:
            by_type = loaded_by_type(workspace)
            self.assertNotIn("customer_letter_external", by_type)
            internal = by_type["customer_letter_internal"]
            total = by_type["comprehensive_report"]
            self.assertEqual(internal.frontmatter["review_status"], "pending")
            self.assertEqual(internal.frontmatter["external_output_required"], "false")
            self.assertFalse(
                any(internal.frontmatter.get(field, "") for field in VALIDATOR.APPROVAL_FIELDS)
            )
            self.assertFalse(
                any(
                    internal.frontmatter.get(field, "")
                    for field in VALIDATOR.LETTER_FACT_REVIEW_FIELDS
                )
            )
            self.assertEqual(total.frontmatter["ready_for_use"], "false")
            manifest = json.loads(
                (workspace / "runtime" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["ready_for_use"])
            self.assertFalse(list(workspace.glob("*客户信（外发版）.md")))
            self.assertFalse(list((workspace / "archive").rglob("*.md")) if (workspace / "archive").exists() else [])

        def assert_blocked_without_write(
            workspace: Path,
            *arguments: str,
            mutating: bool,
        ) -> None:
            before = file_snapshot(workspace)
            result = run_python(
                "validate_outputs.py",
                [str(workspace), *arguments, "--json"],
            )
            self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            codes = {issue["code"] for issue in payload["issues"]}
            self.assertTrue(expected_letter_codes.issubset(codes), sorted(codes))
            if mutating:
                self.assertIn("operation_preflight_failed", codes)
            self.assertIsNone(payload["operation"])
            self.assertIsNone(payload["result_path"])
            self.assertEqual(file_snapshot(workspace), before)
            assert_safe_state(workspace)

        for repetition in range(1, 4):
            with self.subTest(surface="full_lifecycle", repetition=repetition), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_letter_workspace(Path(temporary) / "output")
                install_negated_body(workspace)
                assert_safe_state(workspace)
                lifecycle_baseline = file_snapshot(workspace)

                assert_blocked_without_write(
                    workspace,
                    "--profile",
                    "candidate",
                    mutating=False,
                )

                facts_event = f"n120-{repetition}-facts"
                assert_blocked_without_write(
                    workspace,
                    "--review-letter-facts",
                    "--reviewer",
                    "吴芳（客户信事实复核岗）",
                    "--actor-id",
                    "reviewer-letter-facts",
                    "--action-event-id",
                    facts_event,
                    mutating=True,
                )

                approval_event = f"n120-{repetition}-approval"
                assert_blocked_without_write(
                    workspace,
                    "--approve-letter",
                    "--approver",
                    "李明（客户沟通审批岗）",
                    "--actor-id",
                    "approver-li",
                    "--action-event-id",
                    approval_event,
                    mutating=True,
                )

                assert_blocked_without_write(
                    workspace,
                    "--emit-external",
                    "--actor-id",
                    "requester-wang",
                    "--request-event-id",
                    f"n120-{repetition}-missing-request",
                    mutating=True,
                )

                ready_event = f"n120-{repetition}-ready"
                assert_blocked_without_write(
                    workspace,
                    "--mark-ready",
                    "--reviewer",
                    "陈洁（交付就绪审核岗）",
                    "--actor-id",
                    "ready-letter",
                    "--action-event-id",
                    ready_event,
                    mutating=True,
                )

                assert_blocked_without_write(
                    workspace,
                    "--profile",
                    "release",
                    mutating=False,
                )
                self.assertEqual(file_snapshot(workspace), lifecycle_baseline)
                registry = json.loads(
                    (workspace / "runtime" / "governance-context.json").read_text(
                        encoding="utf-8"
                    )
                )
                for event_id in (facts_event, approval_event, ready_event):
                    self.assertNotIn(event_id, registry["action_assertions"])

    def test_N121_status_registry_claim_gap_and_link_smuggling_fails_atomically_three_times(self):
        smuggled_plan = "王经理同张主任对齐目标并递交产品资料"

        def mutate_status_cell(body: str, label: str, index: int, value: str) -> str:
            lines = body.splitlines()
            for line_index, line in enumerate(lines):
                cells = VALIDATOR.split_table_cells(line) if line.lstrip().startswith("|") else []
                if cells and cells[0] == label:
                    self.assertEqual(len(cells), 15)
                    cells[index] = value
                    lines[line_index] = "| " + " | ".join(cells) + " |"
                    return "\n".join(lines) + ("\n" if body.endswith("\n") else "")
            self.fail(f"未找到状态行：{label}")

        def byte_snapshot(workspace: Path) -> tuple[tuple[str, str, bytes], ...]:
            snapshot: list[tuple[str, str, bytes]] = []
            for path in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
                relative = path.relative_to(workspace).as_posix()
                if path.is_symlink():
                    snapshot.append((relative, "symlink", str(path.readlink()).encode("utf-8")))
                elif path.is_dir():
                    snapshot.append((relative, "directory", b""))
                else:
                    snapshot.append((relative, "file", path.read_bytes()))
            return tuple(snapshot)

        def install_variant(workspace: Path, variant: str) -> None:
            if variant == "no_go":
                install_controlled_no_go_workspace(workspace)

        for variant in ("strategic", "no_go"):
            with self.subTest(phase="direct", variant=variant), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode="strategic_account",
                )
                install_variant(workspace, variant)
                by_type = loaded_by_type(workspace)
                total = by_type["comprehensive_report"]
                ledger_issues: list[object] = []
                claims, _sources = VALIDATOR.collect_ledgers(
                    list(by_type.values()),
                    ledger_issues,
                )
                self.assertFalse(
                    [issue for issue in ledger_issues if issue.severity == "error"]
                )
                for attempt in range(3):
                    with self.subTest(phase="direct_positive", variant=variant, attempt=attempt):
                        issues: list[object] = []
                        VALIDATOR.validate_status_sync(
                            by_type,
                            issues,
                            strict=False,
                            claims=claims,
                        )
                        self.assertFalse(
                            [issue for issue in issues if issue.severity == "error"]
                        )

                institution = by_type["institution_research"]
                status_variants = {
                    "key_claim_ids": (
                        mutate_status_cell(total.body, "机构研究", 11, smuggled_plan),
                        "key_claim_ids_contract_invalid",
                    ),
                    "gaps_blockers": (
                        mutate_status_cell(total.body, "机构研究", 13, smuggled_plan),
                        "gaps_blockers_contract_invalid",
                    ),
                    "link_display": (
                        mutate_status_cell(
                            total.body,
                            "机构研究",
                            14,
                            f"[向客户提交产品方案](./{institution.path.name})",
                        ),
                        "status_link_mismatch",
                    ),
                }
                for surface, (body, expected_code) in status_variants.items():
                    mutated_map = dict(by_type)
                    mutated_map["comprehensive_report"] = VALIDATOR.Document(
                        total.path,
                        total.text,
                        dict(total.frontmatter),
                        body,
                    )
                    for attempt in range(3):
                        with self.subTest(
                            phase="direct_negative",
                            variant=variant,
                            surface=surface,
                            attempt=attempt,
                        ):
                            issues = []
                            VALIDATOR.validate_status_sync(
                                mutated_map,
                                issues,
                                strict=False,
                                claims=claims,
                            )
                            self.assertIn(expected_code, issue_codes(issues))

        for variant in ("strategic", "no_go"):
            for repetition in range(1, 4):
                with self.subTest(
                    phase="release",
                    variant=variant,
                    repetition=repetition,
                ), tempfile.TemporaryDirectory() as temporary:
                    workspace = build_pending_strategy_workspace(
                        Path(temporary) / "output",
                        business_mode="strategic_account",
                    )
                    install_variant(workspace, variant)
                    released = self.complete_strategic_release(workspace)
                    self.assertEqual(released["validation_profile"], "release")
                    by_type = loaded_by_type(workspace)
                    total = by_type["comprehensive_report"]
                    institution = by_type["institution_research"]
                    original_text = total.text
                    release_variants = {
                        "key_claim_ids": (
                            mutate_status_cell(total.body, "机构研究", 11, smuggled_plan),
                            "key_claim_ids_contract_invalid",
                        ),
                        "gaps_blockers": (
                            mutate_status_cell(total.body, "机构研究", 13, smuggled_plan),
                            "gaps_blockers_contract_invalid",
                        ),
                        "link_display": (
                            mutate_status_cell(
                                total.body,
                                "机构研究",
                                14,
                                f"[向客户提交产品方案](./{institution.path.name})",
                            ),
                            "status_link_mismatch",
                        ),
                    }
                    for surface, (body, expected_code) in release_variants.items():
                        total.path.write_text(
                            original_text.replace(total.body, body, 1),
                            encoding="utf-8",
                        )
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                        before = byte_snapshot(workspace)
                        result = run_python(
                            "validate_outputs.py",
                            [str(workspace), "--profile", "release", "--json"],
                        )
                        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                        payload = json.loads(result.stdout)
                        codes = {issue["code"] for issue in payload["issues"]}
                        self.assertIn(expected_code, codes)
                        self.assertIsNone(payload["operation"])
                        self.assertIsNone(payload["result_path"])
                        self.assertEqual(byte_snapshot(workspace), before)
                        total.path.write_text(original_text, encoding="utf-8")
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])

    def test_N125_strategy_navigation_links_usage_and_gaps_are_closed_three_times(self):
        smuggled_action = "王经理同张主任对齐目标并递交产品资料"

        def tree_snapshot(workspace: Path) -> tuple[tuple[str, str, bytes], ...]:
            snapshot: list[tuple[str, str, bytes]] = []
            for path in sorted(workspace.rglob("*"), key=lambda item: item.as_posix()):
                relative = path.relative_to(workspace).as_posix()
                if path.is_symlink():
                    snapshot.append((relative, "symlink", str(path.readlink()).encode("utf-8")))
                elif path.is_dir():
                    snapshot.append((relative, "directory", b""))
                else:
                    snapshot.append((relative, "file", path.read_bytes()))
            return tuple(snapshot)

        def navigation_section(by_type: dict[str, VALIDATOR.Document], branch: str) -> str:
            institution = by_type["institution_research"]
            leader = by_type["leader_research"]
            first_usage = "target" if branch == "scheduled" else "strategic_question"
            return f"""

## {'11' if branch == 'scheduled' else '10'}. 依据导航与缺口

| 序号 | claim_id | 来源成果 | 使用位置 |
|---|---|---|---|
| 1 | CLM-I-001 | [机构研究成果](./{institution.path.name}) | {first_usage} |
| 2 | CLM-L-001 | [人物研究成果](./{leader.path.name}) | qualification |

| claim_ref | claim_type_ref | provenance_ref | evidence_state | impact_type | verification_mode | owner | due_date |
|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | insufficient | verification | internal_review | 账户负责人 | 2026-09-25 |
"""

        def install_navigation(workspace: Path, branch: str) -> None:
            by_type = loaded_by_type(workspace)
            strategy = by_type["visit_strategy"]
            self.assertNotIn("依据导航与缺口", strategy.body)
            write_mutated_body(
                strategy,
                strategy.body.rstrip() + navigation_section(by_type, branch),
            )
            _rebuild_manifest(workspace, ["institution", "leader", "strategy"])

        def navigation_variants(
            by_type: dict[str, VALIDATOR.Document],
            branch: str,
        ) -> dict[str, str]:
            strategy = by_type["visit_strategy"]
            institution = by_type["institution_research"]
            first_usage = "target" if branch == "scheduled" else "strategic_question"
            valid_row = (
                f"| 1 | CLM-I-001 | [机构研究成果](./{institution.path.name}) | {first_usage} |"
            )
            valid_gap = (
                "| CLM-I-001 | F | public | insufficient | verification | "
                "internal_review | 账户负责人 | 2026-09-25 |"
            )
            replacements = {
                "mailto_target": (
                    valid_row,
                    f"| 1 | CLM-I-001 | [机构研究成果](mailto:zhang@example.org) | {first_usage} |",
                ),
                "http_target": (
                    valid_row,
                    f"| 1 | CLM-I-001 | [机构研究成果](https://example.org/product) | {first_usage} |",
                ),
                "display_smuggling": (
                    valid_row,
                    f"| 1 | CLM-I-001 | [向客户提交产品方案](./{institution.path.name}) | {first_usage} |",
                ),
                "usage_smuggling": (
                    valid_row,
                    f"| 1 | CLM-I-001 | [机构研究成果](./{institution.path.name}) | {smuggled_action} |",
                ),
                "gap_action_link": (
                    valid_gap,
                    "| CLM-I-001 | F | public | insufficient | verification | "
                    f"[{smuggled_action}](./{institution.path.name}) | 账户负责人 | 2026-09-25 |",
                ),
            }
            variants: dict[str, str] = {}
            for name, (original, replacement) in replacements.items():
                mutated = strategy.body.replace(original, replacement, 1)
                self.assertNotEqual(mutated, strategy.body, name)
                variants[name] = mutated
            return variants

        def validate_direct(
            by_type: dict[str, VALIDATOR.Document],
            branch: str,
            body: str,
            claims: dict[str, VALIDATOR.ClaimDefinition],
        ) -> set[str]:
            strategy = by_type["visit_strategy"]
            mutated = VALIDATOR.Document(
                strategy.path,
                strategy.text,
                dict(strategy.frontmatter),
                body,
            )
            mutated_map = dict(by_type)
            mutated_map["visit_strategy"] = mutated
            issues: list[object] = []
            if branch == "scheduled":
                VALIDATOR.validate_scheduled_strategy_sections(
                    mutated,
                    issues,
                    by_type=mutated_map,
                    claims=claims,
                )
            else:
                profiles = VALIDATOR.load_business_profiles([])
                contract = VALIDATOR.strategy_variant_contract(
                    "strategic_account",
                    "account_planning",
                    profiles=profiles,
                )
                self.assertIsNotNone(contract)
                VALIDATOR.validate_account_action_contract(
                    mutated,
                    contract,
                    issues,
                    by_type=mutated_map,
                    claims=claims,
                )
            return issue_codes(issues)

        def complete_release(workspace: Path, branch: str, repetition: int) -> dict[str, object]:
            self.govern_success(workspace, "--profile", "candidate")
            suffix = f"n125-{branch}-{repetition}"
            record_action_assertion(
                workspace,
                event_id=f"{suffix}-institution",
                actor_id="reviewer-institution",
                operation="approve_artifact:institution",
                artifact_type="institution_research",
            )
            self.govern_success(
                workspace,
                "--approve-artifact",
                "institution",
                "--reviewer",
                "周洁（机构事实审核岗）",
                "--actor-id",
                "reviewer-institution",
                "--action-event-id",
                f"{suffix}-institution",
            )
            record_action_assertion(
                workspace,
                event_id=f"{suffix}-leader",
                actor_id="reviewer-leader",
                operation="approve_artifact:leader",
                artifact_type="leader_research",
            )
            self.govern_success(
                workspace,
                "--approve-artifact",
                "leader",
                "--reviewer",
                "孙宁（人物事实审核岗）",
                "--actor-id",
                "reviewer-leader",
                "--action-event-id",
                f"{suffix}-leader",
            )
            record_action_assertion(
                workspace,
                event_id=f"{suffix}-strategy",
                actor_id="reviewer-strategy",
                operation="approve_artifact:strategy",
                artifact_type="visit_strategy",
            )
            self.govern_success(
                workspace,
                "--approve-artifact",
                "strategy",
                "--reviewer",
                "钱琳（拜访策略审核岗）",
                "--actor-id",
                "reviewer-strategy",
                "--action-event-id",
                f"{suffix}-strategy",
            )
            business_mode = "standard_visit" if branch == "scheduled" else "strategic_account"
            ready_actor = "ready-standard" if branch == "scheduled" else "ready-strategic"
            record_action_assertion(
                workspace,
                event_id=f"{suffix}-ready",
                actor_id=ready_actor,
                operation=f"mark_ready:{business_mode}",
                artifact_type="comprehensive_report",
            )
            self.govern_success(
                workspace,
                "--mark-ready",
                "--reviewer",
                "陈洁（交付就绪审核岗）" if branch == "scheduled" else "刘宁（战略账户责任岗）",
                "--actor-id",
                ready_actor,
                "--action-event-id",
                f"{suffix}-ready",
            )
            return self.govern_success(workspace, "--profile", "release")

        for branch, business_mode in (
            ("scheduled", "standard_visit"),
            ("account", "strategic_account"),
        ):
            with self.subTest(phase="direct", branch=branch), tempfile.TemporaryDirectory() as temporary:
                workspace = build_pending_strategy_workspace(
                    Path(temporary) / "output",
                    business_mode=business_mode,
                )
                install_navigation(workspace, branch)
                by_type = loaded_by_type(workspace)
                ledger_issues: list[object] = []
                claims, _sources = VALIDATOR.collect_ledgers(
                    list(by_type.values()),
                    ledger_issues,
                )
                self.assertFalse(
                    [issue for issue in ledger_issues if issue.severity == "error"]
                )
                strategy = by_type["visit_strategy"]
                for attempt in range(3):
                    with self.subTest(phase="direct_positive", branch=branch, attempt=attempt):
                        self.assertNotIn(
                            "strategy_navigation_contract_invalid",
                            validate_direct(by_type, branch, strategy.body, claims),
                        )
                for surface, body in navigation_variants(by_type, branch).items():
                    for attempt in range(3):
                        with self.subTest(
                            phase="direct_negative",
                            branch=branch,
                            surface=surface,
                            attempt=attempt,
                        ):
                            self.assertIn(
                                "strategy_navigation_contract_invalid",
                                validate_direct(by_type, branch, body, claims),
                            )

        for branch, business_mode in (
            ("scheduled", "standard_visit"),
            ("account", "strategic_account"),
        ):
            for repetition in range(1, 4):
                with self.subTest(
                    phase="candidate_release",
                    branch=branch,
                    repetition=repetition,
                ), tempfile.TemporaryDirectory() as temporary:
                    workspace = build_pending_strategy_workspace(
                        Path(temporary) / "output",
                        business_mode=business_mode,
                    )
                    install_navigation(workspace, branch)
                    positive_before = tree_snapshot(workspace)
                    candidate = self.govern_success(workspace, "--profile", "candidate")
                    self.assertEqual(candidate["validation_profile"], "candidate")
                    self.assertEqual(tree_snapshot(workspace), positive_before)

                    by_type = loaded_by_type(workspace)
                    strategy = by_type["visit_strategy"]
                    original_candidate_text = strategy.text
                    for surface, body in navigation_variants(by_type, branch).items():
                        strategy.path.write_text(
                            original_candidate_text.replace(strategy.body, body, 1),
                            encoding="utf-8",
                        )
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                        before = tree_snapshot(workspace)
                        result = run_python(
                            "validate_outputs.py",
                            [str(workspace), "--profile", "candidate", "--json"],
                        )
                        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                        payload = json.loads(result.stdout)
                        self.assertIn(
                            "strategy_navigation_contract_invalid",
                            {issue["code"] for issue in payload["issues"]},
                        )
                        self.assertIsNone(payload["operation"])
                        self.assertIsNone(payload["result_path"])
                        self.assertEqual(tree_snapshot(workspace), before)
                        strategy.path.write_text(original_candidate_text, encoding="utf-8")
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])

                    released = complete_release(workspace, branch, repetition)
                    self.assertEqual(released["validation_profile"], "release")
                    release_before = tree_snapshot(workspace)
                    release_positive = self.govern_success(workspace, "--profile", "release")
                    self.assertEqual(release_positive["validation_profile"], "release")
                    self.assertEqual(tree_snapshot(workspace), release_before)

                    by_type = loaded_by_type(workspace)
                    strategy = by_type["visit_strategy"]
                    original_release_text = strategy.text
                    for surface, body in navigation_variants(by_type, branch).items():
                        strategy.path.write_text(
                            original_release_text.replace(strategy.body, body, 1),
                            encoding="utf-8",
                        )
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
                        before = tree_snapshot(workspace)
                        result = run_python(
                            "validate_outputs.py",
                            [str(workspace), "--profile", "release", "--json"],
                        )
                        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                        payload = json.loads(result.stdout)
                        self.assertIn(
                            "strategy_navigation_contract_invalid",
                            {issue["code"] for issue in payload["issues"]},
                        )
                        self.assertIsNone(payload["operation"])
                        self.assertIsNone(payload["result_path"])
                        self.assertEqual(tree_snapshot(workspace), before)
                        strategy.path.write_text(original_release_text, encoding="utf-8")
                        _rebuild_manifest(workspace, ["institution", "leader", "strategy"])


if __name__ == "__main__":
    unittest.main()
