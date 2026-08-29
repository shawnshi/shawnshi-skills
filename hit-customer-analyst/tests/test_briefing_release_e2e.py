from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tests.common import governance, load_json, run_python, runtime_tx as tx, write_intake
from tests.fixture_builder import (
    FIXTURE_EVIDENCE_CUTOFF,
    bind_candidate_machine_bundle,
    install_governance_context,
    record_action_assertion,
)


def _new_run() -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return (
        f"dcr-{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4]}",
        now.isoformat().replace("+00:00", "Z"),
    )


def _workspace_hashes(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class BriefingReleaseE2ETests(unittest.TestCase):
    def _govern(self, workspace: Path, *args: str) -> dict:
        result = run_python("validate_outputs.py", [str(workspace), *args, "--json"])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], 0, payload)
        return payload

    def _init_build_and_commit_candidate(self, root: Path) -> Path:
        intake = write_intake(root / "intakes", "示例医院", "briefing")
        initialized = run_python(
            "init_workspace.py",
            [
                "示例医院",
                "--output-root",
                str(root / "live"),
                "--task-timezone",
                "Asia/Shanghai",
                "--runtime-owner",
                "测试负责人",
                "--business-mode",
                "briefing",
                "--evidence-cutoff-date",
                FIXTURE_EVIDENCE_CUTOFF,
                "--intake-input",
                str(intake),
                "--json",
            ],
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr or initialized.stdout)
        workspace = Path(json.loads(initialized.stdout)["workspace"])
        install_governance_context(workspace)
        total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
        initial_total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
        initial_run = initial_total["latest_run_id"]
        initial_updated = initial_total["updated_at"]
        revision, digest = tx.manifest_state(workspace)
        run_id, timestamp = _new_run()
        cutoff = initial_total["evidence_cutoff_date"]

        institution_body = """
# 示例医院机构研究报告

公开资料确认示例医院为本次研究主体（CLM-I-001）。

## 9. 主张台账

| claim_id | claim_type | provenance | verification_status | 主张内容 | 时间/口径 | 支持 source_id | 反证 source_id | 置信度 | 下游影响/备注 |
|---|---|---|---|---|---|---|---|---|---|
| CLM-I-001 | F | public | verified_single | 示例医院为本次研究主体 | 2026-08-27机构口径 | SRC-I-001 | 无 | 高 | 用于拜访主体确认 |

## 10. 来源台账

| source_id | 标题/文档名 | 发布者/提供者 | URL/稳定定位 | 发布/更新日期 | 访问日期 | 来源等级 | source_group | 权限 | 适用客户/项目 | 备注 | source_fingerprint | upstream_id | external_use |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-I-001 | 示例医院官网简介 | 示例医院 | https://example.org/hospital/profile | 2026-08-27 | 2026-08-27 | A | official-site | public | 示例医院 | none | sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | official:example-hospital | true |
"""
        strategy_body = """
# 示例医院交流策略与议题设计

## 目标与最小推进动作

| 项目 | 内容 | claim_id |
|---|---|---|
| 主要目标 | 核实客户核心任务 | CLM-I-001 |
| 最小推进动作 | 确认下一次技术交流 | CLM-I-001 |
| 成功标准 | 客户确认后续技术交流责任人与时间 | CLM-I-001 |

- 目标对象：信息中心主任

## 机会资格

| 维度 | 当前判断 | claim_id | 待验证问题 |
|---|---|---|---|
| Budget | 预算状态尚无可靠证据 | CLM-I-001 | 核实正式预算或采购安排 |
| Authority | 已知对象层级但决策角色尚待确认 | CLM-I-001 | 核实预算采购和验收责任角色 |
| Need | 核心任务需要客户现场确认 | CLM-I-001 | 核实任务压力与目标结果 |
| Timing/采购时序 | 当前没有可靠采购时序证据 | CLM-I-001 | 核实审批计划和采购窗口 |
| 竞争位置 | 存量供应商格局尚待核实 | CLM-I-001 | 核实现有系统和切换约束 |

- 建议：monitor
- 投入强度：低
- 前提与停止条件：确认真实任务和责任角色；无法确认时转为观察

## 议程

| 时间 | 环节/议题 | 客户对象 | 我方owner | 目标信号 |
|---|---|---|---|---|
| 0—5分钟 | 对齐交流目标和证据边界 | 信息中心主任 | 客户负责人 | 客户确认或修正交流目标 |
| 5—25分钟 | 验证核心任务和决策角色 | 信息中心主任 | 方案顾问 | 获得任务与角色的事实反馈 |
| 最后5分钟 | 收口并确认后续技术交流 | 信息中心主任 | 客户负责人 | 明确动作责任人与日期 |

## 参会分工

| 参会人/角色 | RACI | 负责内容 | 备用安排 |
|---|---|---|---|
| 客户负责人 | A | 主持交流并确认下一步 | 无法出席时由账户责任岗接替 |
| 方案顾问 | R | 记录事实和能力边界 | 使用书面问题清单补充记录 |

## 材料计划

| 材料/演示 | 用途与展示时点 | owner | 版本/授权 | 备用/不展示边界 |
|---|---|---|---|---|
| 授权方案简介 | 客户确认任务后按需展示 | 方案顾问 | 当前授权外发版本 | 未确认需求前不展示产品能力清单 |

## 会后行动

| action | owner | due_date | 依赖 | 完成标准 | CRM/PIMS候选 |
|---|---|---|---|---|---|
| 确认下一次技术交流 | 客户负责人 | 2026-08-27 | 客户确认沟通窗口 | 形成书面时间与责任人记录 | 是 |

## CRM/PIMS

| 候选类型 | 内容 | owner | due_date | 写回状态 |
|---|---|---|---|---|
| action | 确认下一次技术交流并记录责任人 | 客户负责人 | 2026-08-27 | candidate_only |
| verification | 核实任务角色预算与采购时序 | 方案顾问 | 2026-08-27 | candidate_only |
"""
        briefing_body = f"""
# 示例医院会前速览

> 一页交付物｜结论、事实与建议分开

## 一句话判断

客户主体已经公开资料核实，本次先验证核心任务与决策路径，再确认最小下一步（CLM-I-001）。

## 会前必须知道

| 事实 | 事实类型与claim_id | 对本次拜访的意义 |
|---|---|---|
| 示例医院为本次研究主体 | F；CLM-I-001 | 可据此开展限定范围的拜访准备 |

## 机会与边界

| 项目 | 当前判断 | 依据claim_id |
|---|---|---|
| Need | 核心任务需现场核实 | CLM-I-001 |
| Authority | 已知对象层级，具体决策角色需现场确认 | CLM-I-001 |
| Budget/Procurement | 未获得可核验预算或采购证据 | CLM-I-001 |
| Competition | 存量格局待现场核实 | CLM-I-001 |
| 建议 | 建议=monitor；投入强度=低；边界=先完成事实验证 | CLM-I-001 |

## 建议交流节奏

| 时间 | 议题/动作 | 目标信号 |
|---:|---|---|
| 0—5分钟 | 确认客户目标 | 客户修正或确认目标 |
| 5—20分钟 | 交流核心任务 | 获得事实反馈 |
| 20—25分钟 | 验证角色与采购边界 | 明确预算角色等未知事项 |
| 25—30分钟 | 确认可执行下一步安排 | 明确动作与责任人 |

## 三个现场问题

1. 当前最需要优先解决的业务任务是什么？
2. 谁负责业务、技术、预算和采购决策？
3. 下一次技术交流应由谁在何时组织？

## 最小推进动作

- 动作：确认下一次技术交流
- 依据claim_id：CLM-I-001
- Owner：客户负责人
- Due date：{cutoff}
- 红线：不承诺效果、价格或工期

## 未决风险

预算、采购时序和竞争格局均缺少证据；未现场确认前只作为问题，不作结论。
"""
        status_header = (
            "| 模块 | selected_in_run | run_action | module_status | review_status | "
            "connector_status | freshness_status | content_version | latest_run_id | "
            "updated_at | summary_sync_status | key_claim_ids | downstream_invalidation | "
            "gaps/blockers | 成果链接 |"
        )
        total_body = f"""
# 示例医院客户研究与拜访准备报告

本次会前速览与交流策略由已核实主体事实 CLM-I-001 支撑。

## 2. 任务上下文与成果状态

{status_header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 机构研究 | true | created | queued | not_started | not_applicable | current | 1 | {initial_run} | {initial_updated} | pending | none | none | input_missing | [机构研究](./示例医院机构研究报告.md) |
| 人物研究 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |
| 内部检索 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |
| 交流策略 | true | created | queued | not_started | not_applicable | current | 1 | {initial_run} | {initial_updated} | pending | none | none | input_missing | [交流策略](./示例医院交流策略与议题设计.md) |
| 会前速览 | true | created | queued | not_started | not_applicable | current | 1 | {initial_run} | {initial_updated} | pending | none | none | input_missing | [会前速览](./示例医院会前速览.md) |
| 客户信内部审核稿 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |
| 客户信外发版 | false | not_called | not_called | not_required | not_applicable | current |  |  |  | not_applicable |  | none | none |  |

## 8.1 刷新结果记录

| run_id | 新增 | 更正 | 失效 | 未变化 | 待确认 |
|---|---|---|---|---|---|

## 9. 版本与同步记录

| updated_at | content_version | latest_run_id | 变更摘要 | runtime_owner |
|---|---|---|---|---|
| {initial_updated} | 1 | {initial_run} | route=visit_prep; depth=quick; objective=visit_prep运行; selected_modules=institution,strategy,briefing; created=institution,strategy,briefing; updated=none; reused=none; generated=none; not_called=leader,internal,letter,external_letter; target_evidence_cutoff_date={cutoff} | 测试负责人 |
"""
        payload = {
            "schema": "discovery-call-candidate-run/v1",
            "context_id": initial_total["context_id"],
            "expected_manifest_revision": revision,
            "expected_manifest_sha256": digest,
            "run": {
                "run_id": run_id,
                "updated_at": timestamp,
                "evidence_cutoff_date": cutoff,
                "runtime_owner": "测试负责人",
                "workflow_stage": "review",
                "module_status": "completed",
                "freshness_status": "current",
                "objective": "形成可审核会前速览",
            },
            "artifacts": [
                {
                    "artifact_type": "institution_research",
                    "action": "updated",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "body": institution_body,
                    "key_claim_ids": "CLM-I-001",
                },
                {
                    "artifact_type": "visit_strategy",
                    "action": "updated",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "body": strategy_body,
                    "metadata": {
                        "strategy_variant": "scheduled_visit",
                        "target_contact_level": "信息中心主任",
                        "visit_objective": "核实客户核心任务",
                        "minimum_next_step": "确认下一次技术交流",
                    },
                    "key_claim_ids": "CLM-I-001",
                },
                {
                    "artifact_type": "briefing_delivery",
                    "action": "updated",
                    "module_status": "completed",
                    "freshness_status": "current",
                    "body": briefing_body,
                    "key_claim_ids": "CLM-I-001",
                },
            ],
            "total_body": total_body,
        }
        payload_path = root / "briefing-candidate.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        built = run_python(
            "build_candidate.py",
            [
                str(workspace),
                "--payload",
                str(payload_path),
                "--output-root",
                str(root / "candidates"),
                "--intake-input",
                str(intake),
                "--json",
            ],
        )
        self.assertEqual(built.returncode, 0, built.stderr or built.stdout)
        result = json.loads(built.stdout)
        candidate = Path(result["candidate_workspace"])
        self.assertEqual(
            tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))["latest_run_id"],
            initial_run,
            "candidate build must remain isolated from the initialized live workspace",
        )
        bind_candidate_machine_bundle(candidate, ["institution", "strategy"])
        candidate_check = run_python(
            "validate_outputs.py", [str(candidate), "--profile", "candidate", "--json"]
        )
        self.assertEqual(candidate_check.returncode, 0, candidate_check.stdout or candidate_check.stderr)
        self.assertEqual(json.loads(candidate_check.stdout)["errors"], 0)

        command = [*result["next_commit"]["argv"]]
        command.insert(-1, "--strict")
        committed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(committed.returncode, 0, committed.stderr or committed.stdout)
        self.assertEqual(
            tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))["latest_run_id"],
            run_id,
        )
        machine_manifest = load_json(workspace / "runtime" / "manifest.json")
        self.assertEqual(machine_manifest["evidence_run_id"], run_id)
        self.assertEqual(
            set(machine_manifest["runtime_files"]),
            {
                "search-plan.json",
                "source-cache.json",
                "evidence-manifest.json",
                "run-metrics.json",
                "governance-context.json",
            },
        )
        evidence = load_json(workspace / "runtime" / "evidence-manifest.json")
        cache = load_json(workspace / "runtime" / "source-cache.json")
        self.assertTrue(evidence["sources"])
        self.assertTrue(all(source.get("capture_receipt") for source in evidence["sources"].values()))
        self.assertTrue(all(entry.get("capture_receipt") for entry in cache["entries"].values()))
        return workspace

    def _ready_release(self, root: Path) -> Path:
        workspace = self._init_build_and_commit_candidate(root)
        actions = (
            (
                "approve-institution",
                "reviewer-institution",
                "approve_artifact:institution",
                "institution_research",
                ("--approve-artifact", "institution", "--reviewer", "周洁（机构事实审核岗）"),
            ),
            (
                "approve-strategy",
                "reviewer-strategy",
                "approve_artifact:strategy",
                "visit_strategy",
                ("--approve-artifact", "strategy", "--reviewer", "钱琳（拜访策略审核岗）"),
            ),
            (
                "approve-briefing",
                "reviewer-briefing",
                "approve_artifact:briefing",
                "briefing_delivery",
                ("--approve-artifact", "briefing", "--reviewer", "何静（会前简报事实审核岗）"),
            ),
            (
                "ready-briefing",
                "ready-briefing",
                "mark_ready:briefing",
                "comprehensive_report",
                ("--mark-ready", "--reviewer", "刘宁（客户责任岗）"),
            ),
        )
        for event_id, actor_id, operation, artifact_type, arguments in actions:
            record_action_assertion(
                workspace,
                event_id=event_id,
                actor_id=actor_id,
                operation=operation,
                artifact_type=artifact_type,
            )
            self._govern(
                workspace,
                *arguments,
                "--actor-id",
                actor_id,
                "--action-event-id",
                event_id,
            )

        released = self._govern(workspace, "--profile", "release")
        self.assertEqual(released["validation_profile"], "release")
        total_path = next(workspace.glob("*客户研究与拜访准备报告.md"))
        briefing_path = next(workspace.glob("*会前速览.md"))
        total = tx.parse_frontmatter(total_path.read_text(encoding="utf-8"))
        briefing = tx.parse_frontmatter(briefing_path.read_text(encoding="utf-8"))
        self.assertEqual(total["ready_for_use"], "true")
        self.assertEqual(briefing["review_status"], "approved")
        self.assertEqual(briefing["delivery_state"], "ready")
        self.assertEqual(briefing["review_action_event_id"], "approve-briefing")
        self.assertEqual(total["readiness_action_event_id"], "ready-briefing")

        registry = load_json(workspace / "runtime" / "governance-context.json")
        expected_operations = {
            "approve-institution": "approve_artifact:institution",
            "approve-strategy": "approve_artifact:strategy",
            "approve-briefing": "approve_artifact:briefing",
            "ready-briefing": "mark_ready:briefing",
        }
        for event_id, operation in expected_operations.items():
            event = registry["action_assertions"][event_id]
            self.assertTrue(event["consumed_at"])
            self.assertTrue(event["consumed_by_run_id"])
            governance.validate_global_nonce_claim(
                event,
                workspace=workspace,
                event_id=event_id,
                operation=operation,
                consumed_at=event["consumed_at"],
            )
        return workspace

    def test_init_candidate_three_signed_reviews_and_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            self._ready_release(Path(temporary))

    def test_post_approval_briefing_body_drift_fails_release_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._ready_release(Path(temporary))
            briefing_path = next(workspace.glob("*会前速览.md"))
            briefing_path.write_text(
                briefing_path.read_text(encoding="utf-8").replace(
                    "客户主体已经公开资料核实",
                    "客户主体被审批后擅自改写",
                    1,
                ),
                encoding="utf-8",
            )
            before = _workspace_hashes(workspace)
            nonce_dir = Path(os.environ[governance.NONCE_DIR_ENV])
            nonce_before = _workspace_hashes(nonce_dir)
            result = run_python(
                "validate_outputs.py", [str(workspace), "--profile", "release", "--json"]
            )
            self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
            codes = {issue["code"] for issue in json.loads(result.stdout)["issues"]}
            self.assertIn("review_body_drift", codes)
            self.assertIn("runtime_manifest_artifact_drift", codes)
            self.assertEqual(_workspace_hashes(workspace), before)
            self.assertEqual(_workspace_hashes(nonce_dir), nonce_before)


if __name__ == "__main__":
    unittest.main()
