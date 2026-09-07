"""Static regressions for AUDIT-20260906-01; no business data or side effects.

These checks prevent the audited contradictory clauses from returning. They
supplement, rather than replace, functional tests and fresh-session review.
"""
from pathlib import Path
import unittest


SKILLS = Path(__file__).resolve().parents[1]
AGENT = SKILLS.parent


def text(relative: str) -> str:
    return (AGENT / relative).read_text(encoding="utf-8")


class AutonomyContractTests(unittest.TestCase):
    def test_a01_refactor_and_review_have_one_trigger_scope(self):
        contract = text("pai/coding.md")
        self.assertIn("不包括失败断言最小闭包内", contract)
        for line in contract.splitlines():
            if line.startswith("| Refactor"):
                self.assertIn("§4 的触发条件", line)
        self.assertIn("架构级重构、高危补丁或用户要求独立审查时", contract)

    def test_a02_completion_scope_cannot_be_shrunk_after_failure(self):
        contract = text("pai/coding.md")
        for clause in (
            "集合须在修改前明确", "不得事后缩小集合以规避失败",
            "无法证明无关的失败仍属于阻塞", "用户明确要求全库通过时除外",
            "不阻止继续完成不依赖该步骤且已获授权的工作",
            "PARTIAL 的非关键证据延期批准要求保持不变",
            "验收集合内存在失败测试",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, contract)

    def test_a03_resource_indexes_do_not_imply_dependency_changes(self):
        contract = text("pai/references/data-state-supply.md")
        self.assertNotIn("任何 manifest/lockfile 变化", contract)
        self.assertIn("影响依赖来源、版本、解析或安装执行", contract)
        self.assertIn("不因文件名包含 manifest 就触发供应链审计", contract)
        self.assertIn("仍执行本节全部要求", contract)

    def test_a05_no_l4_fast_path_does_not_require_a_second_agent(self):
        contract = text("skills/personal-intelligence-hub/SKILL.md")
        self.assertNotIn("必须真实调用两个独立评估代理", contract)
        self.assertIn("真实调用独立 SemanticEvaluator", contract)
        self.assertIn("仅在 `deterministic_fast_path=false`", contract)
        self.assertIn("已登记的 NoL4Gate 回执", contract)
        self.assertIn("无 L4 但有重大资讯或冲突必须 targeted passed", contract)

    def test_a06_direct_and_conversation_brief_do_not_require_files(self):
        contract = text("skills/hit-digital-strategy-partner/SKILL.md")
        self.assertIn("不运行文件型门禁，也不为满足门禁创建文件", contract)
        self.assertIn("正式决策级交付必须使用 `--strict`", contract)
        self.assertIn("`brief` 文件仅可显式使用", contract)
        workflow = text("skills/hit-digital-strategy-partner/references/workflows.md")
        self.assertIn("不要求另行人工批准或运行脚本", workflow)
        self.assertIn("纯对话且不生成文件、不使用 Blackboard", workflow)

    def test_a07_deep_read_reuses_existing_search_authorization(self):
        contract = text("skills/cognitive-deep-reader/SKILL.md")
        self.assertNotIn("扩展到其他网络来源前先确认", contract)
        self.assertIn("既有授权的主题、来源和时间范围内直接执行", contract)
        self.assertIn("仅新增未授权范围", contract)

    def test_a07_osint_can_finish_authorized_material_analysis(self):
        contract = text("skills/senior-osint-analyst/SKILL.md")
        self.assertNotIn("在用户同意后仅分析其提供的材料", contract)
        self.assertIn("直接完成当前请求已经授权的材料分析", contract)
        self.assertIn("不得声称完成了最新 OSINT 检索", contract)

    def test_a08_missing_health_keeps_template_fields_without_collection(self):
        for name in ("templates.md", "energy_management.md"):
            with self.subTest(reference=name):
                contract = text("skills/personal-cognitive-auditor/references/" + name)
                self.assertIn("非模板自由文本复盘", contract)
                self.assertIn("固定模板或 canonical 保存", contract)
                self.assertIn("不得为满足模板强行采集数据", contract)

    def test_a10_outline_approval_does_not_generate_a_sample(self):
        contract = text("skills/magazine-illustrator/SKILL.md")
        self.assertNotIn("输出计划并生成一张代表性样张，然后只暂停一次", contract)
        self.assertIn("仅输出计划并暂停，不调用图像工具", contract)
        self.assertIn("不跳过用户明确指定的阶段", contract)

    def test_a11_conversion_output_is_not_extra_archiving(self):
        contract = text("skills/tool-markdown-converter/SKILL.md")
        self.assertIn("转换请求包含交付本次 Markdown 及必要资源文件的授权", contract)
        self.assertIn("仅预览或不保存请求除外", contract)
        self.assertIn("不额外归档原件或副本", contract)
        self.assertIn("不虚构文件路径", contract)

    def test_a12_diagram_drafts_keep_formal_approval_gate(self):
        contract = text("skills/technical-diagram-renderer/references/output-qa.md")
        self.assertIn("不阻止“可交付讨论草图”", contract)
        self.assertIn("不得标成拓扑已确认或正式设计", contract)
        self.assertIn("用户明确要求先批准的事项仍须等待", contract)
        self.assertIn("须完成全部适用复核及相应责任人审核", contract)

    def test_a12_unrendered_ppt_requires_accepted_draft_scope(self):
        contract = text("skills/tool-slide-architect/references/pptx-handoff.md")
        self.assertNotIn("缺少构建或渲染能力时交付蓝图", contract)
        self.assertIn("用户明确要求草稿或已接受该降级范围", contract)
        self.assertIn("不自行把最终交付降为草稿", contract)
        self.assertIn("不声称物理 QA 通过", contract)
        self.assertIn("完成内容、合规和物理 QA 后", contract)


if __name__ == "__main__":
    unittest.main()
