---
name: personal-monthly-insights
description: 战略元分析与摩擦基因解码器。当用户抱怨“效率低”、“感觉协作有摩擦”、“指令依赖度高”，或明确要求“出具系统交互报告”时，务必激活。该技能通过审计历史对话与元数据，提取人机协作的负熵规律，并同步洞察至记忆系统。
---

# personal-monthly-insights (V8.0: The Agentic Workflow Edition)

这是一个 100% Agent-Native 的技能。本技能的所有大规模逻辑推演、文本归纳均由 Agent （即现在的你）的脑核在运行时（Runtime）原生存执行，Python 脚本仅作为跨系统的“无脑物理数据泵 (Data Pump)”。

## 📋 4-Stage Agentic Pipeline (严格执行标准)

### Stage 1: 物理数据泵 (Physical Extraction)
- **对话提取**: 运行 `python analyze_insights_v4.py --period <PERIOD> --extract-only` (1d/7d/30d/90d/year)。
- **遥测提取 (Synergy)**: 同时运行 `python C:\Users\shich\.gemini\scripts\system_retro.py` 获取本周期的技能执行度量。
- **效果**: 脚本将生成会话快照 JSON，同时你已掌握了底层的 Token 消耗与失败率统计。

### Stage 2: 核心认知推演 (Cognitive Analysis)
- **动作**: 仔细阅读 `{root_dir}/MEMORY/personal-insights/raw_metrics_<PERIOD>.json` 并结合 Stage 1 获取的 **Quantitative Retro Analysis**。
- **要求**: 你必须启动最高级别的“战略审计官（工作流锻造师）”人格。深度理解过去的交互模式，识别项目领域。在分析痛点时，**必须从“现象陈述”下钻至“协作反模式 (Anti-patterns)”**（例如：未经 Schema 确认的盲目编码、不查阅上下文的无效试错等）。**必须将“用户主观抱怨”与“遥测客观数据”进行对齐分析**（例如：用户抱怨效率低是否对应了某个技能的高失败率或高延迟）。主动嗅探高频重复任务，挖掘建立自动化流水线、自定义技能 (Skill) 或钩子 (Hooks) 的机会，为用户思考超越常规的系统级提效方案。

### Stage 3: 洞察固化 (Insight Serialization)
- **动作**: 将你的推理结果，严格按照以下 JSON 骨架结构，使用 `write_file` 保存至 `{root_dir}/MEMORY/personal-insights/agent_audit_result.json`。
- **结构要求** (<JSON_Schema_V8>):
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

## 历史失效先验 (Gotchas)
- **[2026-03-26] 渲染器对齐与弹性渲染**：当修改 `JSON_Schema_V8` 时，必须同步检查并更新 `analyze_insights_v4.py` 中的渲染逻辑。图表解读数组 `points` 应采用弹性遍历，并为缺失索引提供优雅降级（Graceful Degradation），严禁硬编码索引范围导致页面内容断层。
- **[2026-03-26] 严禁数据复读**：在 `behavioral_analysis` 的 `coach_summary` 部分，严禁简单罗列 `distributions` 中的数据。此处必须作为人类专家的‘教练人格’，提供定性的、具备洞察力的意图推演和实战改进建议。
- **[2026-03-26] 字段完整性**：必须确保 `behavioral_analysis` 下的 `points` 数组至少包含 8 个点（对应报告中的 8 个图表），否则图表下方的解读文字将出现空白。

### Stage 4: 报告渲染与交付 (Render & Deliver)
- **动作**: 运行 `python analyze_insights_v4.py --period <PERIOD> --render --agent-file {root_dir}/MEMORY/personal-insights/agent_audit_result.json`
- **效果**: 生成精美的 HTML 与 Markdown Dashboard，并自动同步一小段总结进记忆系统。

## 🔄 Post-Audit Mandate & Delivery Example

NEVER end with just a file path. ALWAYS summarize the **Top 1 strategic adjustment** and provide an actionable **Workflow Asset (Prompt/Checklist)**.

**Example Delivery Format:**
Input: "帮我复盘一下最近7天的交互情况"
Output:
✅ **Strategic Audit Complete (Last 7 Days)**

I've analyzed your interactions using my native Agentic Workflow. Here is your at-a-glance snapshot:
- **Collaborative Sessions**: 36 
- **Time Invested**: 29.5 hours
- **Friction Highlight**: We hit frequent token-limit issues when debugging long Python stacks.

The interactive dashboard is saved at: [20260307_Strategic_Audit_7d.html](file:///...)

> **💡 Top 1 Strategic Workflow Asset (Copy & Paste ready):**
> **Target Friction:** Repeated failure due to missing context when modifying schemas.
> **Constraint Prompt (Add to Gotchas or use directly next time):**
> `Before writing any code or making changes, output ONLY: (1) your understanding of the file structure, (2) the data model assumptions. Wait for my confirmation.`

**Telemetry & Metadata (Mandatory):**
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root_dir}/MEMORY/skill_audit/telemetry/record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "personal-monthly-insights", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
