# _DIR_META.md

## Architecture Vision
深度防御型写作流水线 (Deep Defense Writing Pipeline)。
通过强制性的红队攻击、恶魔辩护和逻辑审计，产出无懈可击的战略文章。

## Member Index
- `SKILL.md`: [Manifest] 核心流水线定义。
- `scripts/workflow_engine.py`: [Engine] 状态与进度管理引擎。
- `agents/`: [UI] Gemini 身份。
- `references/`: [Knowledge]
  - `agents.md`: 专家角色定义 (Thinker, Red Team, etc.)。
  - `templates.md`: 输出模版 (Red Team Report, Context)。

> ⚠️ **Protocol**: 严禁跳过 Phase 1 (Red Teaming)。没有冲突的文章没有灵魂。
