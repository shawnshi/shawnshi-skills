import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from audit_gate import validate


class AuditGateTests(unittest.TestCase):
    def test_literal_template_syntax_is_non_blocking_in_free_form(self):
        errors, warnings = validate("证据：原文把 [事件] 作为字段示例。")

        self.assertEqual(errors, [])
        self.assertTrue(any("possible unresolved template markers" in item for item in warnings))

    def test_template_mode_blocks_unresolved_template_fields(self):
        errors, _ = validate(
            "# [日期] Daily Audit\n\n证据：用户提供的日志。",
            enforce_template_fields=True,
        )

        self.assertTrue(any("possible unresolved template markers" in item for item in errors))

    def test_style_terms_remain_editorial_warnings(self):
        errors, warnings = validate("证据存在，但草稿写了冷酷判词。")

        self.assertEqual(errors, [])
        self.assertTrue(any("potentially shaming" in item for item in warnings))

    def test_complete_energy_section_passes_template_contract(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 2026-08-01，本地 Garmin。
- **组件覆盖与新鲜度:** sleep=complete；观测日期 2026-08-01。
- **睡眠观察:** 观测日期 2026-08-01，7.2 小时。
- **HRV 与静息心率观察:** 各自观测日期均已披露。
- **Body Battery 与压力观察:** 各自观测日期均已披露。
- **同期关系:** 只记录时间共现。
- **执行带宽:** not_scored
- **数据缺口与不可判断事项:** 无。
- **一般性恢复建议:** 保持观察。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertEqual(errors, [])

    def test_template_mode_blocks_missing_energy_fields(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **执行带宽:** not_scored
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("energy-management section missing fields" in item for item in errors))

    def test_blocks_numeric_composite_energy_score(self):
        errors, _ = validate("证据：Garmin。\n- 能量总分：78")

        self.assertTrue(any("composite energy" in item for item in errors))

    def test_blocks_python_none_in_user_facing_text(self):
        errors, _ = validate("证据：本地 Garmin。睡眠时长：None")

        self.assertTrue(any("Python None" in item for item in errors))

    def test_allows_python_none_in_unrelated_technical_evidence(self):
        errors, _ = validate("证据：脚本返回 Python None。")

        self.assertEqual(errors, [])

    def test_blocks_missing_health_value_as_zero(self):
        errors, _ = validate("证据：本地 Garmin。\n- 睡眠时长：0 小时（无有效观测）")

        self.assertTrue(any("physiological value 0" in item for item in errors))

    def test_blocks_partial_cloud_fallback(self):
        errors, _ = validate("证据：本地状态 partial，因此执行云端查询回退。")

        self.assertTrue(any("partial local Garmin" in item for item in errors))

    def test_allows_partial_status_when_cloud_fallback_was_not_executed(self):
        errors, _ = validate("证据：本地状态 partial，未执行云端回退。")

        self.assertEqual(errors, [])

    def test_blocks_affirmative_fallback_after_a_negated_fallback_clause(self):
        errors, _ = validate(
            "证据：本地状态 partial，未执行云端回退，随后执行云端查询。"
        )

        self.assertTrue(any("partial local Garmin" in item for item in errors))

    def test_blocks_multiline_partial_cloud_fallback(self):
        errors, _ = validate(
            "证据：本地状态 partial。\n下一步：执行云端回退。"
        )

        self.assertTrue(any("partial local Garmin" in item for item in errors))

    def test_blocks_mixed_partial_fallback_statement(self):
        errors, _ = validate(
            "partial 时通常未执行云端回退，但本次随后执行云端回退。"
        )

        self.assertTrue(any("partial local Garmin" in item for item in errors))

    def test_blocks_sleep_debt_when_source_does_not_provide_it(self):
        text = "证据：Garmin。sleep_debt_h=2.5；sleep_debt_status=not_provided_by_source"
        errors, _ = validate(text)

        self.assertTrue(any("sleep debt value" in item for item in errors))

    def test_blocks_forced_schedule_or_training_decision(self):
        errors, _ = validate("证据：昨夜睡眠较短，因此必须取消会议。")

        self.assertTrue(any("must not force" in item for item in errors))

    def test_allows_explicitly_non_forcing_health_statement(self):
        errors, _ = validate("证据：昨夜睡眠较短，但不需要取消会议。")

        self.assertEqual(errors, [])

    def test_blocks_forced_action_after_a_non_forcing_clause(self):
        errors, _ = validate(
            "证据：睡眠较短，不需要取消会议，但必须停止训练。"
        )

        self.assertTrue(any("must not force" in item for item in errors))

    def test_blocks_multiline_health_forced_action(self):
        errors, _ = validate("昨夜睡眠较短。\n因此必须取消会议。")

        self.assertTrue(any("must not force" in item for item in errors))

    def test_blocks_multiline_python_none_in_health_context(self):
        errors, _ = validate("睡眠数据如下。\n- 睡眠时长: None")

        self.assertTrue(any("Python None" in item for item in errors))

    def test_blocks_generic_none_field_in_health_data_block(self):
        errors, _ = validate("证据：睡眠数据如下。\n- value: None")

        self.assertTrue(any("Python None" in item for item in errors))

    def test_allows_no_data_fallback_rule_after_partial_non_fallback(self):
        errors, _ = validate(
            "本地状态 partial，未执行云端回退。只有 no_data 时才允许云端查询。"
        )

        self.assertEqual(errors, [])

    def test_allows_unrelated_market_live_query_after_partial_status(self):
        errors, _ = validate(
            "本地状态 partial，未执行云端回退。下一节说明实时查询仅用于行情。"
        )

        self.assertEqual(errors, [])

    def test_allows_unrelated_project_owner_schedule_action(self):
        errors, _ = validate("昨夜睡眠较短。项目负责人必须取消会议。")

        self.assertEqual(errors, [])

    def test_allows_unrelated_debug_none_after_health_statement(self):
        errors, _ = validate("睡眠数据已完整。脚本调试返回 Python None。")

        self.assertEqual(errors, [])

    def test_allows_unrelated_schedule_statement(self):
        errors, _ = validate("证据：项目负责人需要取消会议。")

        self.assertEqual(errors, [])

    def test_warns_on_health_causality_overreach(self):
        errors, warnings = validate("证据：HRV 下降说明认知能力下降。")

        self.assertEqual(errors, [])
        self.assertTrue(any("health causality" in item for item in warnings))

    def test_warns_when_shared_upstream_signals_are_double_counted(self):
        text = "证据：Body Battery 与睡眠评分构成双重证据并相互印证。"
        errors, warnings = validate(text)

        self.assertEqual(errors, [])
        self.assertTrue(any("share upstream signals" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
