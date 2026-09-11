from __future__ import annotations

import json
import re
from pathlib import Path

from tests.common import load_json, run_python
from tests.common import runtime_tx as tx


def _replace_frontmatter(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    end = next(
        index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
    )
    seen: set[str] = set()
    for index in range(1, end):
        key = lines[index].partition(":")[0]
        if key in updates:
            lines[index] = f"{key}: {json.dumps(updates[key], ensure_ascii=False)}"
            seen.add(key)
    for key in updates.keys() - seen:
        lines.insert(end, f"{key}: {json.dumps(updates[key], ensure_ascii=False)}")
        end += 1
    return "\n".join(lines[: end + 1]).rstrip() + "\n"


def _document(original: str, updates: dict[str, str], body: str) -> str:
    return _replace_frontmatter(original, updates) + "\n" + body.strip() + "\n"


def _rebuild_manifest(workspace: Path, selected_modules: list[str]) -> None:
    old = load_json(workspace / tx.MANIFEST_REL)
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
    manifest = tx.build_manifest(
        workspace,
        identity={
            "context_id": total["context_id"],
            "customer_id": total["customer_id"],
            "customer_display_name": total["customer_display_name"],
            "organization_scope": total["organization_scope"],
        },
        business_mode=total["business_mode"],
        route=total["route"],
        depth=total["depth"],
        latest_run_id=total["latest_run_id"],
        content_version=total["content_version"],
        stage=total["workflow_stage"],
        ready_for_use=total["ready_for_use"] == "true",
        selected_modules=selected_modules,
        authorization=old.get("authorization", {}),
        transaction_sequence=int(old["transaction_sequence"]) + 1,
    )
    tx.atomic_write_json(workspace / tx.MANIFEST_REL, manifest)


def build_pending_letter_workspace(output_root: Path) -> Path:
    """Build the smallest non-strict-valid workspace for letter lifecycle tests."""
    initialized = run_python(
        "init_workspace.py",
        [
            "示例医院",
            "--output-root",
            str(output_root),
            "--task-timezone",
            "Asia/Shanghai",
            "--runtime-owner",
            "测试负责人",
            "--business-mode",
            "letter",
            "--json",
        ],
    )
    if initialized.returncode:
        raise RuntimeError(initialized.stderr or initialized.stdout)
    workspace = Path(json.loads(initialized.stdout)["workspace"])
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    institution_path = next(workspace.glob("*机构研究报告.md"))
    letter_path = next(workspace.glob("*客户信（内部待审核稿）.md"))
    total_original = total_path.read_text(encoding="utf-8")
    institution_original = institution_path.read_text(encoding="utf-8")
    letter_original = letter_path.read_text(encoding="utf-8")
    initial = tx.parse_frontmatter(total_original)
    run_id = initial["latest_run_id"]
    timestamp = initial["updated_at"]
    cutoff = initial["evidence_cutoff_date"]

    institution_body = """
# 示例医院机构研究报告

公开资料确认示例医院为本次研究主体（CLM-I-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于客户信主体确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | 主体确认 | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_text = _document(
        institution_original,
        {
            "module_status": "completed",
            "review_status": "not_required",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
        },
        institution_body,
    )

    letter_context = {
        "letter_scenario": "拜访后正式跟进",
        "recipient_role": "张主任，信息中心主任，身份已确认",
        "letter_purpose": "确认下一次技术交流安排",
        "expected_action": "确认九月技术交流时间",
        "signer": "王经理，客户负责人",
        "delivery_channel": "正式电子邮件",
    }
    letter_body = f"""
# 示例医院客户信（内部待审核稿）

## 1. 内部摘要

- 信件场景：{letter_context["letter_scenario"]}
- 收件对象：{letter_context["recipient_role"]}
- 发信目的：{letter_context["letter_purpose"]}
- 期望动作：{letter_context["expected_action"]}
- 签署人：{letter_context["signer"]}
- 发送渠道：{letter_context["delivery_channel"]}
- 事实依据：CLM-I-001

## 2. 候选正文

`EXTERNAL_BODY_START`

张主任，您好：

感谢您此前的交流。诚请您确认九月技术交流的合适时间，我们将据此安排相关同事参加。

王经理

`EXTERNAL_BODY_END`

## 4. 版本与审核记录（严禁外发）

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner | review_status |
|---|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | 完成客户信内部稿并提交审核 | 测试负责人 | pending |
"""
    letter_text = _document(
        letter_original,
        {
            "module_status": "completed",
            "review_status": "pending",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
            **letter_context,
            "external_output_required": "false",
            "approver": "",
            "approved_at": "",
            "approved_content_version": "",
            "approved_body_sha256": "",
            "approved_context_sha256": "",
        },
        letter_body,
    )

    status_header = (
        "| 模块 | selected_in_run | run_action | module_status | review_status | "
        "connector_status | freshness_status | content_version | latest_run_id | "
        "updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | "
        "gaps/blockers | 成果链接 |"
    )
    uncalled = {
        "人物研究": "",
        "内部检索": "",
        "交流策略": "",
        "客户信外发版": "",
    }
    status_rows = [
        f"| 机构研究 | true | created | completed | not_required | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [机构研究](./{institution_path.name}) |",
        *(
            f"| {label} | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |"
            for label in uncalled
            if label != "客户信外发版"
        ),
        f"| 客户信内部审核稿 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [客户信内部审核稿](./{letter_path.name}) |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
    ]
    run_summary = (
        "route=letter; depth=standard; objective=letter; "
        "selected_modules=institution,letter; created=institution,letter; "
        "updated=none; reused=none; generated=none; "
        "not_called=leader,internal,strategy,external_letter; "
        f"target_evidence_cutoff_date={cutoff}"
    )
    total_banner = next(
        line for line in total_original.splitlines() if "内部研究档位：" in line
    )
    total_body = f"""
# 示例医院客户研究与拜访准备报告

{total_banner}

本次客户信由公开事实 CLM-I-001 支撑。

## 2. 任务上下文与成果状态

{status_header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(status_rows)}

## 2.1 本次RACI

| 角色 | 姓名（稳定角色/账号） |
|---|---|
| account_owner | 合成客户负责人（测试岗） |

| action | owner | due_date |
|---|---|---|
| 确认后续交流条件 | 合成行动负责人（测试岗） | {cutoff} |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | {run_summary} | 测试负责人 |
"""
    total_text = _document(
        total_original,
        {
            "module_status": "completed",
            "review_status": "not_required",
            "freshness_status": "current",
            "content_version": "1",
            "latest_run_id": run_id,
            "updated_at": timestamp,
            "evidence_cutoff_date": cutoff,
            "workflow_stage": "review",
            "ready_for_use": "false",
            "readiness_reviewer": "",
            "readiness_reviewed_at": "",
            "readiness_content_version": "",
            "readiness_body_sha256": "",
        },
        total_body,
    )

    institution_path.write_text(institution_text, encoding="utf-8")
    letter_path.write_text(letter_text, encoding="utf-8")
    total_path.write_text(total_text, encoding="utf-8")
    _rebuild_manifest(workspace, ["institution", "letter"])
    return workspace


def build_pending_strategy_workspace(
    output_root: Path,
    *,
    business_mode: str = "standard_visit",
    role_only: bool = False,
    official_template: bool = False,
) -> Path:
    """Build synthetic pending review evidence; never perform a real approval."""
    initialized = run_python(
        "init_workspace.py",
        [
            "示例医院",
            "--output-root",
            str(output_root),
            "--task-timezone",
            "Asia/Shanghai",
            "--runtime-owner",
            "测试负责人",
            "--business-mode",
            business_mode,
            "--modules",
            "institution,leader,strategy",
            "--json",
        ],
    )
    if initialized.returncode:
        raise RuntimeError(initialized.stderr or initialized.stdout)
    workspace = Path(json.loads(initialized.stdout)["workspace"])
    total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
    institution_path = next(workspace.glob("*机构研究报告.md"))
    leader_path = next(workspace.glob("*人物研究报告.md"))
    strategy_path = next(workspace.glob("*交流策略与议题设计.md"))
    originals = {
        "total": total_path.read_text(encoding="utf-8"),
        "institution": institution_path.read_text(encoding="utf-8"),
        "leader": leader_path.read_text(encoding="utf-8"),
        "strategy": strategy_path.read_text(encoding="utf-8"),
    }
    initial = tx.parse_frontmatter(originals["total"])
    run_id = initial["latest_run_id"]
    timestamp = initial["updated_at"]
    cutoff = initial["evidence_cutoff_date"]
    terminal = {
        "module_status": "completed",
        "freshness_status": "current",
        "content_version": "1",
        "latest_run_id": run_id,
        "updated_at": timestamp,
        "evidence_cutoff_date": cutoff,
    }

    institution_body = """
# 示例医院机构研究报告

公开资料确认示例医院为本次研究主体（CLM-I-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-26机构口径 | SRC-I-001 | 无 | 高 | 用于拜访主体确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-25 | 2026-08-26 | A | official-site | public | 示例医院 | 主体确认 | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
    institution_path.write_text(
        _document(
            originals["institution"],
            {**terminal, "review_status": "not_required"},
            institution_body,
        ),
        encoding="utf-8",
    )

    leader_body = """
# 示例医院人物研究报告

公开任职信息显示张主任负责信息化工作（CLM-L-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-L-001 | F | public | verified_single | 张主任负责信息化工作 | 2026-08-26公开任职口径 | SRC-L-001 | 无 | 高 | 用于拜访对象确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-L-001 | 示例医院领导介绍 | 示例医院 | https://example.org/hospital/leader | 2026-08-25 | 2026-08-26 | A | official-leader | public | 示例医院 | 任职确认 | sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | official:leader-page | true |
"""
    if role_only:
        leader_body = leader_body.replace(
            "公开任职信息显示张主任负责信息化工作",
            "正式部门职责确认信息中心负责信息化工作",
        ).replace("张主任负责信息化工作", "信息中心承担院级信息化建设职责")
        leader_body = (
            leader_body.replace("公开任职口径", "正式部门职责口径")
            .replace("示例医院领导介绍", "示例医院信息中心职责")
            .replace("任职确认", "正式角色职责确认")
            .replace("拜访对象确认", "角色职责依据，不包含具名身份判断")
        )
        leader_body += "\n## 研究范围与边界\n\n角色级研究；未指定具名对象，不含具名主张。正式职责依据为 CLM-L-001；不推断任职者身份或个人权限。\n"
    leader_path.write_text(
        _document(
            originals["leader"],
            {
                **terminal,
                "review_status": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "reviewed_content_version": "",
                "reviewed_body_sha256": "",
            },
            leader_body,
        ),
        encoding="utf-8",
    )

    strategy_context = {
        "target_contact_level": "信息中心（正式部门角色，不指定姓名）"
        if role_only
        else "信息中心主任张主任",
        "visit_objective": "确认院级数据治理需求与决策路径",
        "minimum_next_step": "确定下一次需求澄清会时间",
    }
    strategy_body = f"""
# 示例医院交流策略与议题设计

- 拜访对象：{strategy_context["target_contact_level"]}
- 拜访目标：{strategy_context["visit_objective"]}
- 最小推进动作：{strategy_context["minimum_next_step"]}
- 事实依据：CLM-I-001、CLM-L-001

## 机会资格

以客户任务、预算、权限和时序为现场验证重点。

## 议程

围绕现状、目标和下一步展开。

## 参会分工

客户负责人主持，方案顾问记录问题。

## 材料与演示计划

使用经授权的方案简介。

## 会后行动

由客户负责人跟进下一次需求澄清会，并形成CRM/PIMS候选记录。

| action | owner | due_date |
|---|---|---|
| 确认后续交流条件 | 合成行动负责人（测试岗） | {cutoff} |
"""
    if official_template:
        template_body = originals["strategy"].split("---", 2)[2]
        values = {
            **strategy_context,
            "拜访对象与层级": strategy_context["target_contact_level"],
            "拜访目标": strategy_context["visit_objective"],
            "时间/待确认": "待确认会议时间",
            "true/false": "false",
            "会议结束时可观察的结果": "明确需求验证责任与下一次沟通条件",
            "内容": "围绕院级信息化职责验证数据治理需求",
            "开放式问题": "目前哪些数据治理问题需要跨部门确认？",
            "预算来源/状态/口径/未知": "预算未知，现场验证来源与审批程序",
            "业务/技术/预算/采购/验收角色": "信息中心技术角色；预算采购权限待验证",
            "任务、压力与可观察结果": "确认院级数据治理需求及验收口径",
            "关键节点": "采购时序未知，现场核验",
            "存量、竞争、我司匹配与短板": "产品匹配待验证，尚无竞争证据",
            "问题": "需要补充哪些正式资料？",
            "win/conditional_win/monitor/no_go": "monitor",
            "低/中/高": "低",
            "0—5分钟": "0—5分钟",
            "5—25分钟": "5—25分钟",
            "最后5分钟": "25—30分钟",
            "开场": "确认目标",
            "核心议题": "需求澄清",
            "收口": "确认下一步",
            "角色": "信息中心技术角色",
            "姓名/稳定角色": "合成客户负责人",
            "最小推进动作": strategy_context["minimum_next_step"],
            "姓名/稳定角色/待确认": "合成方案负责人",
            "R/A/C/I": "R",
            "姓名/角色": "合成材料负责人",
            "版本、external_use": "v1，内部演示授权，external_use=false",
            "用于验证关键假设的问题": "数据治理需求有哪些正式依据？",
            "用于确认角色与流程的问题": "哪些角色负责技术及预算确认？",
            "用于形成最小下一步的问题": "下一次需求澄清需哪些资料？",
            "唯一主动作": "确认需求澄清条件",
            "真人/稳定角色": "合成行动负责人",
            "YYYY-MM-DD": cutoff,
            "是/否": "是",
            "最多一个备选": "暂无备选动作",
            "触发条件": "未能确认沟通条件则到期复核",
            "相对链接": f"[机构研究](./{institution_path.name})",
            "章节": "机会资格",
            "pending/approved/changes_requested": "pending",
            "姓名（稳定角色/账号）/待定": "待定",
            "带时区时间/空": "空",
            "带时区时间": timestamp,
            "内容/无": "尚待人工审核",
        }
        # Official template renders these slots from the same structured context.
        values.update(
            {"strategy." + key: value for key, value in strategy_context.items()}
        )
        strategy_body = re.sub(
            r"\{\{([^{}]+)\}\}",
            lambda match: (
                ("CLM-L-001" if match[1].startswith("CLM-L/") else "CLM-I-001")
                if match[1].startswith("CLM-")
                else values[match[1]]
            ),
            template_body,
        )
    strategy_path.write_text(
        _document(
            originals["strategy"],
            {
                **terminal,
                "review_status": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "reviewed_content_version": "",
                "reviewed_body_sha256": "",
                **strategy_context,
            },
            strategy_body,
        ),
        encoding="utf-8",
    )

    header = (
        "| 模块 | selected_in_run | run_action | module_status | review_status | "
        "connector_status | freshness_status | content_version | latest_run_id | "
        "updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | "
        "gaps/blockers | 成果链接 |"
    )
    rows = [
        f"| 机构研究 | true | created | completed | not_required | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001 | none | 无 | [机构研究](./{institution_path.name}) |",
        f"| 人物研究 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-L-001 | none | 无 | [人物研究](./{leader_path.name}) |",
        "| 内部检索 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
        f"| 交流策略 | true | created | completed | pending | not_applicable | current | 1 | {run_id} | {timestamp} | synced | CLM-I-001, CLM-L-001 | none | 无 | [交流策略](./{strategy_path.name}) |",
        "| 客户信内部审核稿 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
        "| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | 无 |  |",
    ]
    summary = (
        f"route={initial['route']}; depth={initial['depth']}; objective={business_mode}; "
        "selected_modules=institution,leader,strategy; "
        "created=institution,leader,strategy; updated=none; reused=none; "
        "generated=none; not_called=internal,letter,external_letter; "
        f"target_evidence_cutoff_date={cutoff}"
    )
    total_banner = next(
        line for line in originals["total"].splitlines() if "内部研究档位：" in line
    )
    total_body = f"""
# 示例医院客户研究与拜访准备报告

{total_banner}

本次拜访由 CLM-I-001 和 CLM-L-001 支撑。

## 2. 任务上下文与成果状态

{header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## 2.1 本次RACI

| 角色 | 姓名（稳定角色/账号） |
|---|---|
| account_owner | 合成客户负责人（测试岗） |

| action | owner | due_date |
|---|---|---|
| 确认后续交流条件 | 合成行动负责人（测试岗） | {cutoff} |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {timestamp} | 1 | {run_id} | {summary} | 测试负责人 |
"""
    total_path.write_text(
        _document(
            originals["total"],
            {
                **terminal,
                "review_status": "not_required",
                "workflow_stage": "review",
                "ready_for_use": "false",
                "readiness_reviewer": "",
                "readiness_reviewed_at": "",
                "readiness_content_version": "",
                "readiness_body_sha256": "",
            },
            total_body,
        ),
        encoding="utf-8",
    )
    _rebuild_manifest(workspace, ["institution", "leader", "strategy"])
    return workspace
