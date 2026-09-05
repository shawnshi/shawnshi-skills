import unittest
import importlib.util
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
TEMPLATE_TEXT = (SKILL_ROOT / "assets" / "ooda_template.md").read_text(
    encoding="utf-8"
)
GATE_PATH = SKILL_ROOT / "scripts" / "evidence_gate.py"
SPEC = importlib.util.spec_from_file_location("mentat_evidence_gate", GATE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class MentatInsightDiaryContractTests(unittest.TestCase):
    def test_generation_defaults_to_canonical_atomic_save(self):
        for required in (
            "生成完成后自动保存",
            "personal-diary-writer",
            "canonical Mentat 目标",
            "同日原子替换",
            "标题数量等于 1",
            "授权范围摘要与实际写入范围摘要相等",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_p0_and_p1_contracts_block_meta_logs_and_separate_receipts(self):
        for required in (
            "blocked_no_substantive_events",
            "blocked_low_density",
            "不生成八段正文、不创建写入范围回执、不保存空洞条目",
            "journal_meta",
            "正文与保存回执分离",
            "不进入八段正文",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_p2_contract_has_fixed_dimensions_and_thresholds(self):
        for required in (
            "facts",
            "results",
            "tradeoffs",
            "friction",
            "continuity",
            "总分 0–3",
            "总分 4–6",
            "总分 7–10",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_preview_and_noncanonical_writes_do_not_inherit_authorization(self):
        for required in (
            "草稿、预览、分析、审计技能或不保存",
            "自定义路径、外部系统、知识库、STQM 和 Vector Lake",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_template_matches_writer_ooda_gate_and_does_not_preclaim_save(self):
        headings = (
            "**1. 观测 (Observe)：**",
            "**2. 导向 (Orient)：**",
            "**3. 决策 (Decide)：**",
            "**4. 执行 (Act)：**",
            "**5. 系统自我反思 (Self-Reflection)**",
            "**6. 对指挥官的观察与建议 (Commander Observation & Suggestion)**",
            "**7. 认知结晶 (Cognitive Distillations)：**",
            "**8. [Message to Future Mentat]**",
        )
        positions = []
        for required in headings:
            with self.subTest(required=required):
                self.assertIn(required, TEMPLATE_TEXT)
                self.assertIn(required, SKILL_TEXT)
                positions.append(TEMPLATE_TEXT.index(required))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("**未决问题**", TEMPLATE_TEXT)
        self.assertNotIn("日志已归档", TEMPLATE_TEXT)
        self.assertIn("不得预先声称本条已经保存", TEMPLATE_TEXT)

    def test_new_sections_keep_evidence_and_authorization_boundaries(self):
        for required in (
            "不得伪装主观意识或隐藏推理",
            "不做人格、动机或能力定性",
            "生成结晶不等于授权写入知识库",
            "不包含隐藏推理、凭据或越权指令",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_collection_precedes_scoring_and_preserves_privacy(self):
        self.assertLess(SKILL_TEXT.index("## 取证前置检查"), SKILL_TEXT.index("## P0 实质事件门"))
        for required in (
            "collection.status=ready",
            "needs_source",
            "source_error",
            "不得用空数组代替尚未执行的取证",
            "不自动读取私人日记、健康数据、邮件或全部会话目录",
            "已有可用来源时直接读取最小相关片段",
            "不把错误转换成空事件",
            "跨日会话只提取目标日期的事件",
            "只对已检查范围下结论",
            "不验证取证完整性",
        ):
            with self.subTest(required=required):
                self.assertIn(required, SKILL_TEXT)

    def test_empty_input_only_proves_no_submitted_events(self):
        result = GATE.evaluate({"events": []})
        self.assertEqual(result["status"], "blocked_no_substantive_events")
        self.assertEqual(result["total_score"], 0)
        self.assertFalse(result["save_allowed"])
        self.assertNotIn("collection", result)

    def test_collection_metadata_does_not_change_event_score(self):
        event = {
            "kind": "execution",
            "summary": "ran a bounded task",
            "source": "current visible tool result",
        }
        payload = {"events": [event]}
        expected = GATE.evaluate(payload)
        payload["collection"] = {
            "status": "ready",
            "period": "2026-09-05",
            "timezone": "Asia/Shanghai",
            "checked_sources": ["current conversation"],
            "unchecked_sources": [],
            "errors": [],
        }
        self.assertEqual(GATE.evaluate(payload), expected)

    def test_plan_only_is_not_substantive(self):
        result = GATE.evaluate({"events": [{
            "kind": "plan", "summary": "plan a repair", "source": "user request"
        }]})
        self.assertEqual(result["status"], "blocked_no_substantive_events")
        self.assertEqual(result["excluded_event_count"], 1)
        self.assertFalse(result["save_allowed"])

    def test_evidence_gate_blocks_journal_meta_only(self):
        result = GATE.evaluate(
            {
                "events": [
                    {
                        "kind": "journal_meta",
                        "summary": "loaded the diary skill and computed a scope hash",
                        "source": "current session",
                        "artifact_or_state": "scope receipt",
                        "result": "hash matched",
                        "verification": "receipt",
                    }
                ]
            }
        )
        self.assertEqual(result["status"], "blocked_no_substantive_events")
        self.assertFalse(result["save_allowed"])
        self.assertEqual(result["total_score"], 0)

    def test_evidence_gate_blocks_low_density_business_event(self):
        result = GATE.evaluate(
            {
                "events": [
                    {
                        "kind": "execution",
                        "summary": "discussed a project",
                        "source": "user statement",
                    }
                ]
            }
        )
        self.assertEqual(result["status"], "blocked_low_density")
        self.assertEqual(result["total_score"], 1)
        self.assertFalse(result["save_allowed"])

    def test_evidence_gate_allows_thin_entry_at_four_points(self):
        result = GATE.evaluate(
            {
                "events": [
                    {
                        "kind": "state_change",
                        "summary": "updated a bounded artifact",
                        "source": "verified file",
                        "artifact_or_state": "artifact moved to review",
                        "result": "candidate created",
                        "next_trigger": "review completed",
                    }
                ]
            }
        )
        self.assertEqual(result["status"], "thin")
        self.assertEqual(result["total_score"], 4)
        self.assertTrue(result["save_allowed"])

    def test_evidence_gate_allows_full_entry_with_complete_evidence(self):
        result = GATE.evaluate(
            {
                "events": [
                    {
                        "kind": "failure",
                        "summary": "deployment validation failed and was repaired",
                        "source": "test output",
                        "artifact_or_state": "candidate artifact",
                        "result": "validation passed after repair",
                        "verification": "regression test passed",
                        "decision": "repair the candidate",
                        "rejected_alternative": "weaken the validation gate",
                        "decision_basis": "preserve the contract",
                        "issue": "schema mismatch",
                        "effect": "deployment blocked",
                        "resolution": "candidate corrected",
                        "next_trigger": "publish after review",
                        "completion_standard": "remote artifact hash matches",
                    }
                ]
            }
        )
        self.assertEqual(result["status"], "substantive")
        self.assertEqual(result["total_score"], 10)
        self.assertTrue(result["save_allowed"])


if __name__ == "__main__":
    unittest.main()
