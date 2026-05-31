# _DIR_META.md

## Architecture Vision
母语级中文润色引擎 (Master Editor)。
专注于消除 AI 生成文本的机械感与“翻译腔”，通过语义清洗与语感重构，使文本呈现出真实人类专家的对话感与思维节奏。

## Member Index
- `SKILL.md`: [Manifest] 核心指令与“三层级润色”工作流。
- `scripts/humanize_engine.py`: [Engine] 语言分析与评分引擎。
- `references/`: [Knowledge]
  - `GUIDELINES.md`: 黑名单词汇与句式规范。
  - `CHECKLIST.md`: 质量核查清单。
  - `EXAMPLES.md`: 场景化案例（博客、汇报、回复）。
- `agents/gemini.yaml`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 每次重写后必须对照 `references/CHECKLIST.md` 执行二阶检查。
