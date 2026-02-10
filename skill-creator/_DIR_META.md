# _DIR_META.md

## Architecture Vision
技能工厂 (The Skill Factory)。
负责定义、初始化并校验 Gemini 技能模块。作为 GEB-Flow 协议的守护者，确保所有扩展技能均符合“分形自描述”与“渐进式披露”的高级架构标准。

## Member Index
- `SKILL.md`: [Manifest] 技能创建的核心指南与 SOP。
- `scripts/`: [Engine]
  - `init_skill.py`: 技能初始化引擎（已升级支持 GEB-Flow）。
  - `quick_validate.py`: 规范性校验工具。
- `references/`: [Knowledge] UI 规范与 API 参考。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 每次升级 `init_skill.py` 的生成逻辑后，必须同步更新 `SKILL.md` 中的解剖结构说明。
