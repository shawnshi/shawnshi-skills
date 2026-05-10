# JSON Schema for personal-monthly-insights (V9.0)

Save the reasoning result to `~/.gemini/MEMORY/raw/personal-insights/agent_audit_result.json` using this structure.

```json
{
  "version": "9.0",
  "project_areas": { "areas": [ { "name": "...", "session_count": 0, "description": "..." } ] },
  "behavioral_analysis": {
    "intro": "...",
    "overall": "总体趋势定性描述",
    "coach_summary": "高密度定性教练解读，必须解释意图、摩擦和非对称建议，不能只是复读数字。",
    "points": [
      { "title": "指标名称", "description": "针对该指标的深层解读点" }
    ]
  },
  "interaction_style": { "narrative": "...", "key_pattern": "..." },
  "what_works": { "intro": "...", "impressive_workflows": [ { "title": "...", "description": "..." } ] },
  "friction_analysis": {
    "intro": "...",
    "categories": [
      {
        "category": "例如：无前置约束的盲目重试",
        "root_cause_pattern": "深度归因",
        "examples": ["具体场景引用"]
      }
    ]
  },
  "workflow_engineering": {
    "prompt_assets": [
      {
        "target_friction": "针对的摩擦点",
        "asset_type": "Constraint / Handoff / Checklist",
        "copy_paste_template": "可直接复制粘贴的文本"
      }
    ],
    "automation_candidates": [
      {
        "candidate_name": "建议的新 Skill 或 Hook 名称",
        "rationale": "为什么值得自动化",
        "implementation_sketch": "核心逻辑描述"
      }
    ]
  },
  "suggestions": {
    "config_additions": [ { "addition": "...", "why": "..." } ],
    "usage_patterns": [ { "title": "...", "suggestion": "...", "detail": "..." } ]
  },
  "on_the_horizon": { "intro": "...", "opportunities": [ { "title": "...", "whats_possible": "...", "how_to_try": "..." } ] },
  "fun_ending": { "headline": "...", "detail": "..." },
  "at_a_glance": {
    "whats_working": "...",
    "whats_hindering": "...",
    "quick_wins": "...",
    "ambitious_workflows": "..."
  },
  "distributions": {
    "goal_dist": { "调试错误": 5, "实现功能": 10 },
    "satisfaction_dist": { "满意": 12, "尚可": 3 },
    "friction_dist": { "理解偏差": 2, "代码缺陷": 4 },
    "interaction_anti_patterns": { "未验证先编码": 4, "中途打断/放弃": 3 },
    "emotional_tone_dist": { "专注": 8, "焦虑": 1 },
    "helpfulness_dist": { "非常有效": 10 },
    "session_type_dist": { "单一任务": 8, "多任务": 5 },
    "topic_cloud": { "Python": 10, "React": 8 },
    "radar_data": [85, 90, 75, 88, 80, 85]
  }
}
```

## Structural Requirements

- `behavioral_analysis.points` must contain exactly **8** items.
- `coach_summary` must be qualitative and strategic, not a list of raw numbers.
- `workflow_engineering.prompt_assets` must contain at least one ready-to-copy asset.
- `workflow_engineering.automation_candidates` must contain at least one automation proposal.

## Result Gate

A renderable audit must prove all five items:

1. One core anti-pattern is named.
2. Subjective friction is tied to at least one objective metric or telemetry clue.
3. One copyable workflow asset exists.
4. One automation candidate exists.
5. One next-cycle action exists in `at_a_glance.quick_wins` or `suggestions.usage_patterns`.
