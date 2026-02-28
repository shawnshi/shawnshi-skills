# _DIR_META.md

## Architecture Vision
深度防御型写作流水线 (Deep Defense Writing Pipeline)。
通过强制性的红队攻击、恶魔辩护和逻辑审计，产出无懈可击的战略文章。

## Member Index
- `SKILL.md`: [Manifest] 核心流水线定义（Phase 0-5 + Resource Map + Troubleshooting）。
- `scripts/workflow_engine.py`: [Engine] 状态与进度管理引擎（含 Phase 门控与原子写入）。
- `agents/gemini.yaml`: [UI] Gemini Agent 身份配置（含 instruction 系统指令）。
- `references/`: [Knowledge]
  - `agents.md`: Phase 0-4 专家角色定义（与 SKILL.md 一一对应）。
  - `templates.md`: 各 Phase 标准化输出模板（含示例填充）。
  - `CHECKLIST.md`: Phase 4 审计检查清单（17 项 / 4 维度）。
  - `ANTI_PATTERNS.md`: 废话黑名单 + 结构性反模式库（33+ 条）。

> ⚠️ **Protocol**: 严禁跳过 Phase 1 (Red Teaming)。没有冲突的文章没有灵魂。
