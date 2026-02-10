# _DIR_META.md

## Architecture Vision
战略思想工厂 (Strategic Thought Factory)。
通过“逻辑-灵魂-校验”的三阶流水线，将原始信息加工为具有穿透力的深度文章。

## Member Index
- `SKILL.md`: [Manifest] 核心工作流定义。
- `scripts/assistant.py`: [Engine] 上下文组装引擎，负责聚合策略与模板。
- `references/`: [Knowledge] 写作规范、检查清单与反模式库。
- `templates/`: [Assets] 文章结构模板。
- `styles/`: [Assets] 风格调性配置。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 任何新的写作规范必须添加到 `references/GUIDELINES.md`，并在 `assistant.py` 中确认引用。
