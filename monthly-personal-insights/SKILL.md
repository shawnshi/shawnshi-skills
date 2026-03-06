---
name: monthly-personal-insights
description: 生成周期性战略元分析报告，解码协作摩擦基因并自动同步洞察至记忆系统。
triggers: ["出具我本月的系统交互报告", "分析我的指令依赖度", "最近效率很低分析下原因", "我感觉协作有摩擦", "生成本月元分析报告并同步记忆", "generate monthly insight report", "analyze my AI collaboration patterns", "run weekly digest", "本周复盘"]
---

# monthly-personal-insights (V7.0: Claude /insights Pipeline Parity)

## 📋 6-Stage Pipeline

### Stage 1: Session Filtering & Metadata
- Execute `python analyze_insights_v4.py --period <PERIOD>` (7d/30d/90d/year)
- Quality gates: exclude agent sub-sessions, <2 user messages, <1 minute
- Multi-source fusion: Gemini CLI logs + Antigravity brain logs

### Stage 2: Transcript Summarization
- Sessions >30k chars are chunked (25k) and summarized before analysis.

### Stage 3: Facet Extraction (Count-Based)
- Count-based schema: `goal_categories:{cat:count}`, `friction_counts:{type:count}`, `user_satisfaction_counts:{level:count}`
- New dimensions: `claude_helpfulness`, `session_type`, `underlying_goal`, `friction_detail`

### Stage 4: 7 Specialized Analyses
- Project Areas / Interaction Style / What Works / Friction Analysis / Suggestions / On the Horizon / Fun Ending

### Stage 5: At a Glance
- Executive summary: What's Working / What's Hindering / Quick Wins / Ambitious Workflows

### Stage 6: Report & Auto-Sync
- HTML interactive report (8 charts, 7 narrative sections, At-a-Glance cards)
- Markdown export + auto-sync to `memory.md`

## 🔄 Post-Audit Mandate
NEVER end with just a file path. ALWAYS summarize the **Top 1 strategic adjustment** for the next period.

