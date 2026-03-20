---
name: personal-monthly-insights
description: 战略元分析与摩擦基因解码器。当用户抱怨“效率低”、“感觉协作有摩擦”、“指令依赖度高”，或明确要求“出具系统交互报告”时，务必激活。该技能通过审计历史对话与元数据，提取人机协作的负熵规律，并同步洞察至记忆系统。
---

# personal-monthly-insights (V8.0: The Agentic Workflow Edition)

这是一个 100% Agent-Native 的技能。本技能的所有大规模逻辑推演、文本归纳均由 Agent （即现在的你）的脑核在运行时（Runtime）原生存执行，Python 脚本仅作为跨系统的“无脑物理数据泵 (Data Pump)”。

## 📋 4-Stage Agentic Pipeline (严格执行标准)

### Stage 1: 物理数据泵 (Physical Extraction)
- **动作**: 运行 `python analyze_insights_v4.py --period <PERIOD> --extract-only` (1d/7d/30d/90d/year)。
- **效果**: 脚本将过滤低质量会话、融合多源日志，并生成纯物理结构的包含会话快照的 JSON：`{root_dir}/MEMORY/personal-insights/raw_metrics_<PERIOD>.json`。

### Stage 2: 核心认知推演 (Cognitive Analysis)
- **动作**: 使用 `view_file` 或相关工具，仔细阅读上一步生成的 `{root_dir}/MEMORY/personal-insights/raw_metrics_<PERIOD>.json`。
- **要求**: 你必须启动最高级别的“战略审计官”人格。深度理解过去的交互模式，识别项目领域、显著的痛点/摩擦，并为用户思考超越常规的系统级提效方案。

### Stage 3: 洞察固化 (Insight Serialization)
- **动作**: 将你的推理结果，严格按照以下 JSON 骨架结构，使用 `write_to_file` 保存至 `{root_dir}/MEMORY/personal-insights/agent_audit_result.json`。
- **结构要求** (<JSON_Schema_V8>):
```json
{
  "project_areas": { "areas": [ { "name": "...", "session_count": 0, "description": "..."} ] },
  "interaction_style": { "narrative": "...", "key_pattern": "..." },
  "what_works": { "intro": "...", "impressive_workflows": [ { "title": "...", "description": "..."} ] },
  "friction_analysis": { "intro": "...", "categories": [ { "category": "...", "description": "...", "examples": ["..."]} ] },
  "suggestions": { "config_additions": [ { "addition": "...", "why": "..." } ], "usage_patterns": [ { "title": "...", "suggestion": "...", "detail": "..." } ] },
  "on_the_horizon": { "intro": "...", "opportunities": [ { "title": "...", "whats_possible": "...", "how_to_try": "..."} ] },
  "fun_ending": { "headline": "...", "detail": "..." },
  "at_a_glance": { "whats_working": "...", "whats_hindering": "...", "quick_wins": "...", "ambitious_workflows": "..." },
  "distributions": {
    "goal_dist": {"调试错误": 5, "实现功能": 10},
    "satisfaction_dist": {"满意": 12, "尚可": 3},
    "friction_dist": {"理解偏差": 2, "代码缺陷": 4},
    "emotional_tone_dist": {"专注": 8, "焦虑": 1},
    "helpfulness_dist": {"非常有效": 10},
    "session_type_dist": {"单一任务": 8, "多任务": 5},
    "topic_cloud": {"Python": 10, "React": 8, "Refactoring": 5},
    "radar_data": [85, 90, 75, 88, 80, 85] 
  }
}
```
*(注意: `distributions` 是为了雷达图和条形图能在 HTML 中正常渲染，你需要根据阅读的数据编造或合理推算这些数值，各项满分为 100)*

### Stage 4: 报告渲染与交付 (Render & Deliver)
- **动作**: 运行 `python analyze_insights_v4.py --period <PERIOD> --render --agent-file {root_dir}/MEMORY/personal-insights/agent_audit_result.json`
- **效果**: 生成精美的 HTML 与 Markdown Dashboard，并自动同步一小段总结进记忆系统。

## 🔄 Post-Audit Mandate & Delivery Example

NEVER end with just a file path. ALWAYS summarize the **Top 1 strategic adjustment** for the next period.

**Example Delivery Format:**
Input: "帮我复盘一下最近7天的交互情况"
Output:
✅ **Strategic Audit Complete (Last 7 Days)**

I've analyzed your interactions using my native Agentic Workflow. Here is your at-a-glance snapshot:
- **Collaborative Sessions**: 36 
- **Time Invested**: 29.5 hours
- **Friction Highlight**: We hit frequent token-limit issues when debugging long Python stacks.

The interactive dashboard (with 8 full charts powered by my deductions) is saved at:
[20260307_Strategic_Audit_7d.html](file:///...)

> **💡 Top 1 Strategic Adjustment for Next Week:**
> When handling multi-file refactoring, let's explicitly request to view the files individually before writing code, to lower our error fallback loops.
