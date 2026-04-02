# JSON Schema for personal-monthly-insights (V8.1)

The agent MUST save its reasoning results to `~/.gemini/MEMORY/personal-insights/agent_audit_result.json` using this exact JSON skeleton.

```json
{
  "project_areas": { "areas": [ { "name": "...", "session_count": 0, "description": "..."} ] },
  "behavioral_analysis": {
    "intro": "...",
    "overall": "总体趋势定性描述",
    "coach_summary": "### 🦅 指挥官行为与意图综合审计\n作为教练对意图潜台词的深度解析，必须包含‘意图分析’与‘非对称建议’，严禁在此处复读指标数据。",
    "points": [ { "title": "指标名称", "description": "针对该指标的深层解读点" } ]
  },
  "interaction_style": { "narrative": "...", "key_pattern": "..." },
  "what_works": { "intro": "...", "impressive_workflows": [ { "title": "...", "description": "..."} ] },
  "friction_analysis": {
    "intro": "...",
    "categories": [
      {
        "category": "例如：无前置约束的盲目重试",
        "root_cause_pattern": "深度归因，例如：用户直接抛出报错日志，未提供排查范围，导致 Agent 进入无意义的修改配置循环。",
        "examples": ["具体的会话场景引用"]
      }
    ]
  },
  "workflow_engineering": {
    "prompt_assets": [
      {
        "target_friction": "针对上述的哪项摩擦",
        "asset_type": "前置约束(Constraint) / 结构化交接(Handoff) / 验证清单(Checklist)",
        "copy_paste_template": "这里必须输出一段具体的、可以直接被用户复制粘贴进提示词或放入 Gotchas 的文本。"
      }
    ],
    "automation_candidates": [
      {
        "candidate_name": "建议的新 Skill 或 Hook 名称",
        "rationale": "为什么建议自动化这个流程（例如：发现了重复 5 次以上的类似修改）",
        "implementation_sketch": "该 Skill/Hook 的初步实现伪代码或核心逻辑描述"
      }
    ]
  },
  "suggestions": { "config_additions": [ { "addition": "...", "why": "..." } ], "usage_patterns": [ { "title": "...", "suggestion": "...", "detail": "..." } ] },
  "on_the_horizon": { "intro": "...", "opportunities": [ { "title": "...", "whats_possible": "...", "how_to_try": "..."} ] },
  "fun_ending": { "headline": "...", "detail": "..." },
  "at_a_glance": { "whats_working": "...", "whats_hindering": "...", "quick_wins": "...", "ambitious_workflows": "..." },
  "distributions": {
    "goal_dist": {"调试错误": 5, "实现功能": 10},
    "satisfaction_dist": {"满意": 12, "尚可": 3},
    "friction_dist": {"理解偏差": 2, "代码缺陷": 4},
    "interaction_anti_patterns": {"未验证先编码": 4, "中途打断/放弃": 3, "假设未对齐": 5},
    "emotional_tone_dist": {"专注": 8, "焦虑": 1},
    "helpfulness_dist": {"非常有效": 10},
    "session_type_dist": {"单一任务": 8, "多任务": 5},
    "topic_cloud": {"Python": 10, "React": 8, "Refactoring": 5},
    "radar_data": [85, 90, 75, 88, 80, 85]
  }
}
```

## Structural Requirements:
- **`behavioral_analysis.points`**: MUST contain exactly 8 points corresponding to the 8 dashboard charts.
- **`coach_summary`**: MUST provide qualitative, expert-level insights (Commander-mode coaching). DO NOT just list numbers.
- **`workflow_engineering.prompt_assets`**: MUST provide a ready-to-use text block for the user to copy.

```