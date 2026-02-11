# _DIR_META.md

## Architecture Vision
文章语义配图引擎 (The Master Illustrator)。
分析长文结构，识别视觉增强点，通过 Type (信息结构) × Style (艺术审美) 双维矩阵生成高一致性的插图系列。

## Member Index
- `SKILL.md`: [Manifest] 核心指令、SOP 与维护协议。
- `scripts/`: [Engine] 图像生成执行脚本 (executor.py)。
- `references/`: [Knowledge]
  - `gallery.md`: 类型与风格预览。
  - `logic.md`: 自动选择与信号识别逻辑。
  - `styles/`: 20 种风格的底层 Prompt 定义。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 严禁生成字面意义的隐喻图（如“电锯切西瓜”），必须抽象为核心概念。
