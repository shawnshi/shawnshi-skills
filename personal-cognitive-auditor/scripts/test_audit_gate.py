import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
from audit_gate import (
    ACQUISITION_AUDIT_CONTRACT,
    ACQUISITION_FIELD_ENUMS,
    ALLOWED_TASK_STATUSES,
    ENERGY_REQUIRED_FIELDS,
    validate,
    validate_handoff_payload,
)


class AuditGateTests(unittest.TestCase):
    def test_quarterly_handoff_period_is_supported(self):
        payload = {
            "period_type": "quarterly",
            "audit_title": "2026-Q3 Quarterly Audit",
            "audit_body_markdown": "证据充分的季度审计正文",
            "next_tactics": ["形成下一季度行动清单"],
            "followup_flags": [],
            "requires_mentat_diary": False,
        }

        self.assertEqual(validate_handoff_payload(payload), [])

    def test_periodic_topology_accepts_unique_target_h2_and_h3_sections(self):
        text = (
            "## [2026-08] Monthly Cognitive Audit｜2026-08-01 至 2026-08-31\n\n"
            "### 时间范围与证据\n\n- 证据：完整。\n"
        )
        errors, _ = validate(text, period_type="monthly", period_id="2026-08")

        self.assertEqual(errors, [])

    def test_periodic_topology_blocks_atx_and_setext_h1_h2(self):
        tails = (
            "## 非目标区块\n\n- 证据：不得写入。\n",
            "   ## 缩进非目标区块\n\n- 证据：不得写入。\n",
            "Setext 非目标区块\n---\n",
            "Setext 一级区块\n===\n",
            "   # 缩进一级区块\n",
        )
        for tail in tails:
            with self.subTest(tail=tail):
                text = "## [2026-08] Monthly Cognitive Audit\n\n" + tail
                errors, _ = validate(
                    text,
                    period_type="monthly",
                    period_id="2026-08",
                )
                self.assertTrue(any("unique target H2" in item for item in errors))

    def test_periodic_topology_blocks_h1_or_mismatched_period(self):
        cases = (
            ("# 2026年8月审计\n\n## [2026-08] Monthly Cognitive Audit\n", "2026-08"),
            ("## [2026-07] Monthly Cognitive Audit\n", "2026-08"),
        )
        for text, period_id in cases:
            with self.subTest(text=text):
                errors, _ = validate(
                    text + "\n证据：存在。\n",
                    period_type="monthly",
                    period_id=period_id,
                )
                self.assertTrue(any("unique target H2" in item for item in errors))

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
- **采集审计:** sync_eligible=false; sync_attempted=not_attempted; task_status=not_checked; local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=historical_window
- **睡眠观察:** 观测日期 2026-08-01，7.2 小时。
- **HRV 与静息心率观察:** 各自观测日期均已披露。
- **Body Battery 与压力观察:** 各自观测日期均已披露。
- **执行带宽:** `not_scored`；不从 Garmin 指标生成认知或工作表现评分。
- **睡眠负债:** 来源未提供；sleep_debt_h=null，sleep_debt_status=not_provided_by_source，method=none，baseline_h=null，window_days=null。
- **摩擦解构:** 已记录日程负荷；主观感受未提供；生理观测仅作描述。
- **交叉归因:** 只记录时间共现，并保留日期错位和其他替代解释。
- **干预指令:** 若本人主观困倦，可选择休息十分钟；完成标准为记录主观状态。
- **数据缺口与不可判断事项:** 无。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertEqual(errors, [])

    def test_template_mode_blocks_missing_energy_section(self):
        errors, _ = validate(
            "# 2026-08-25 Daily Audit\n\n## 关键事实\n- 已提供事实。",
            enforce_template_fields=True,
        )

        self.assertIn("energy-management section missing", errors)

    def test_personal_diary_energy_heading_uses_same_strict_contract(self):
        text = """# 2026-08-25 星期二

## 能量管理 (Biological-Cognitive Correlation)
- **数据范围与来源:** 2026-08-23 至 2026-08-25，本地 Garmin，只读。
- **组件覆盖与新鲜度:** sleep/hrv/body_battery/heart_rate/stress 均有观测；最近观测日期 2026-08-24。
- **采集审计:** sync_eligible=true; sync_attempted=started; task_status=failed; local_reread=rejected; local_status=read_error; live_fallback=not_used; reason=terminal_coverage_stale
- **睡眠观察:** 观测日期 2026-08-24，6.3 小时。
- **HRV 与静息心率观察:** HRV 46 ms、静息心率 55 bpm，观测日期均为 2026-08-24。
- **Body Battery 与压力观察:** 峰值 100、低值 26、充入 55、平均压力 30，观测日期均为 2026-08-24。
- **执行带宽:** `not_scored`；行为证据为项目周会、方案编写和 PPT 讨论；不从健康指标推断工作能力。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source；method=none；baseline_h=null；window_days=null；另列实际睡眠 6.3 小时。
- **摩擦解构:** 已记录工作负荷；主观状态未知；生理观测仅到 2026-08-24。
- **交叉归因:** 工作事实与生理观测日期错位，不建立因果或能力判断。
- **干预指令:** 若沟通尚未开始，可准备一页清单；完成标准为列出目标和待决问题。
- **数据缺口与不可判断事项:** 2026-08-25 无终端观测，不能判断当天生理背景。
"""
        errors, warnings = validate(text, enforce_template_fields=True)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_personal_diary_old_six_field_shape_is_blocked(self):
        text = """# 2026-08-25 星期二

## 能量管理 (Biological-Cognitive Correlation)
- **系统态势:** 本地 Garmin partial。
- **执行带宽:** `not_scored`；不从 Garmin 推断工作能力。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source。
- **摩擦解构:** 工作负荷已记录。
- **交叉归因:** 不建立因果。
- **干预指令:** 由用户决定。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("energy-management section missing fields" in item for item in errors))
        self.assertTrue(any("数据范围与来源" in item for item in errors))

    def test_template_mode_blocks_missing_energy_fields(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **执行带宽:** not_scored
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("energy-management section missing fields" in item for item in errors))

    def test_previous_template_shape_is_blocked_when_four_projection_fields_are_missing(self):
        text = """# 周复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** sleep=partial；观测日期 2026-08-15。
- **睡眠观察:** 观测日期 2026-08-15，7.3 小时。
- **HRV 与静息心率观察:** 各自观测日期已披露。
- **Body Battery 与压力观察:** 各自观测日期已披露。
- **同期关系:** 只记录时间共现。
- **执行带宽:** not_scored
- **数据缺口与不可判断事项:** 无。
- **一般性恢复建议:** 保持观察。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("睡眠负债" in item for item in errors))
        self.assertTrue(any("摩擦解构" in item for item in errors))
        self.assertTrue(any("交叉归因" in item for item in errors))
        self.assertTrue(any("干预指令" in item for item in errors))
        self.assertTrue(any("require explanatory content" in item for item in errors))

    def test_template_mode_blocks_contentless_energy_projection_fields(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；不从健康指标生成认知或工作表现评分。
- **睡眠负债:** 来源未提供；sleep_debt_h=null，sleep_debt_status=not_provided_by_source，method=none，baseline_h=null，window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        safe_values = {
            "执行带宽": "`not_scored`；不从健康指标生成认知或工作表现评分。",
            "睡眠负债": "来源未提供；sleep_debt_h=null，sleep_debt_status=not_provided_by_source，method=none，baseline_h=null，window_days=null。",
            "摩擦解构": "已记录负荷为空；未知项已披露。",
            "交叉归因": "没有同日证据，不建立因果关系。",
            "干预指令": "没有健康依据时不生成强制安排。",
        }

        for field, safe_value in safe_values.items():
            with self.subTest(field=field):
                candidate = text.replace(
                    f"- **{field}:** {safe_value}",
                    f"- **{field}:** [DATA_UNAVAILABLE]",
                )
                errors, _ = validate(candidate, enforce_template_fields=True)
                explanatory = next(
                    item for item in errors if "require explanatory content" in item
                )
                self.assertIn(field, explanatory)

    def test_template_mode_blocks_sentinel_even_with_explanation(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；[DATA_UNAVAILABLE]，不从健康指标评分。
- **睡眠负债:** [DATA_UNAVAILABLE]；sleep_debt_h=null，sleep_debt_status=not_provided_by_source，method=none，baseline_h=null，window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        sentinel_error = next(
            item for item in errors if "must not expose DATA_UNAVAILABLE" in item
        )
        self.assertIn("执行带宽", sentinel_error)
        self.assertIn("睡眠负债", sentinel_error)

    def test_template_mode_accepts_source_provided_sleep_debt_with_status(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** sleep=complete；观测日期 2026-08-22。
- **采集审计:** sync_eligible=false; sync_attempted=not_attempted; task_status=not_checked; local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=historical_window
- **睡眠观察:** 观测日期 2026-08-22，7.0 小时。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；不从健康指标生成认知或工作表现评分。
- **睡眠负债:** sleep_debt_h=1.0；sleep_debt_status=provided_by_source；method=source_calculated；baseline_h=7.5；window_days=3。
- **摩擦解构:** 已记录睡眠观测；工作负荷、主观感受和外部约束未知。
- **交叉归因:** 没有同日工作证据，不建立因果关系。
- **干预指令:** 若本人主观困倦，可选择休息十分钟；完成标准为记录主观状态。
- **数据缺口与不可判断事项:** 只有睡眠组件完整，不作趋势判断。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertEqual(errors, [])

    def test_template_mode_requires_complete_null_sleep_debt_contract(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；不从健康指标生成认知或工作表现评分。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(
            any("complete unavailable-state fields" in item for item in errors)
        )

    def test_template_mode_blocks_incomplete_acquisition_audit(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **采集审计:** sync_eligible=true; sync_attempted=started
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；不从健康指标生成认知或工作表现评分。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source；method=none；baseline_h=null；window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("acquisition audit missing or invalid keys" in item for item in errors))

    def test_template_mode_blocks_contradictory_acquisition_audit(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **采集审计:** sync_eligible=false; sync_attempted=started; task_status=failed; local_reread=rejected; local_status=read_error; live_fallback=used; reason=sync_failed
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；不从健康指标生成认知或工作表现评分。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source；method=none；baseline_h=null；window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("acquisition audit state conflict" in item for item in errors))

    def test_acquisition_semantics_reject_nonterminal_task_status(self):
        from audit_gate import acquisition_semantic_errors

        errors = acquisition_semantic_errors(
            "sync_eligible=true; sync_attempted=waited_existing; task_status=running; "
            "local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=task_running"
        )
        self.assertTrue(any("terminal" in item for item in errors))

    def test_acquisition_semantics_accepts_drift_before_attempt(self):
        from audit_gate import acquisition_semantic_errors

        errors = acquisition_semantic_errors(
            "sync_eligible=false; sync_attempted=not_attempted; task_status=invalid; "
            "local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=task_arguments_drift"
        )
        self.assertEqual(errors, [])

    def test_acquisition_semantics_accepts_start_failure(self):
        from audit_gate import acquisition_semantic_errors

        errors = acquisition_semantic_errors(
            "sync_eligible=true; sync_attempted=not_attempted; task_status=start_failed; "
            "local_reread=not_run; local_status=not_run; live_fallback=not_used; reason=task_start_failed"
        )
        self.assertEqual(errors, [])

    def test_live_fallback_requires_structured_no_data(self):
        from audit_gate import acquisition_semantic_errors

        errors = acquisition_semantic_errors(
            "sync_eligible=false; sync_attempted=not_attempted; task_status=not_checked; "
            "local_reread=rejected; local_status=partial; live_fallback=used; reason=live_fallback_used"
        )
        self.assertTrue(any("local_status=no_data" in item for item in errors))

    def test_live_fallback_cannot_skip_an_eligible_sync_task(self):
        from audit_gate import acquisition_semantic_errors

        errors = acquisition_semantic_errors(
            "sync_eligible=true; sync_attempted=not_attempted; task_status=not_checked; "
            "local_reread=rejected; local_status=no_data; live_fallback=used; reason=live_fallback_used"
        )
        self.assertTrue(any("sync_eligible=false" in item for item in errors))

    def test_template_mode_blocks_execution_score_fields(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** `not_scored`；score=80；不从健康指标推断工作能力。
- **睡眠负债:** sleep_debt_h=null；sleep_debt_status=not_provided_by_source；method=none；baseline_h=null；window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("must not contain score" in item for item in errors))

    def test_template_mode_requires_not_scored_execution_boundary(self):
        text = """# 复盘

## 能量管理（描述性生理背景）
- **数据范围与来源:** 本地 Garmin。
- **组件覆盖与新鲜度:** 无有效观测。
- **睡眠观察:** 无有效观测。
- **HRV 与静息心率观察:** 无有效观测。
- **Body Battery 与压力观察:** 无有效观测。
- **执行带宽:** 依据当前观察保持稳定。
- **睡眠负债:** 来源未提供；sleep_debt_h=null，sleep_debt_status=not_provided_by_source，method=none，baseline_h=null，window_days=null。
- **摩擦解构:** 已记录负荷为空；未知项已披露。
- **交叉归因:** 没有同日证据，不建立因果关系。
- **干预指令:** 没有健康依据时不生成强制安排。
- **数据缺口与不可判断事项:** 本地无数据。
"""
        errors, _ = validate(text, enforce_template_fields=True)

        self.assertTrue(any("must retain not_scored" in item for item in errors))

    def test_all_bundled_templates_declare_every_energy_projection_field(self):
        skill_root = Path(__file__).parent.parent
        template_paths = [
            skill_root / "references" / "templates.md",
            *(skill_root / "prompts" / name for name in (
                "DAILY.md",
                "WEEKLY.md",
                "MONTHLY.md",
                "QUARTERLY.md",
                "ANNUAL.md",
            )),
        ]

        for path in template_paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for field in ENERGY_REQUIRED_FIELDS:
                    self.assertIn(f"**{field}:**", text)

    def test_acquisition_contract_matches_parser_across_content_surfaces(self):
        skill_root = Path(__file__).parent.parent
        contract_paths = [
            skill_root / "references" / "energy_management.md",
            skill_root / "references" / "templates.md",
            *(skill_root / "prompts" / name for name in (
                "DAILY.md",
                "WEEKLY.md",
                "MONTHLY.md",
                "QUARTERLY.md",
                "ANNUAL.md",
            )),
            skill_root.parent / "personal-diary-writer" / "SKILL.md",
        ]

        self.assertEqual(
            set(ACQUISITION_FIELD_ENUMS["task_status"]), ALLOWED_TASK_STATUSES
        )
        for path in contract_paths:
            with self.subTest(path=path):
                self.assertIn(
                    f"`{ACQUISITION_AUDIT_CONTRACT}`",
                    path.read_text(encoding="utf-8"),
                )

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

    def test_allows_actual_sleep_observation_when_sleep_debt_is_unavailable(self):
        text = (
            "sleep_debt_h=null；sleep_debt_status=not_provided_by_source；"
            "来源未提供睡眠负债。实际睡眠为 6.3 小时。"
        )
        errors, _ = validate(text)

        self.assertFalse(any("sleep debt value" in item for item in errors))

    def test_blocks_unattributed_numeric_sleep_debt_when_source_is_unavailable(self):
        text = "来源未提供睡眠负债 2.5 小时。"
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
