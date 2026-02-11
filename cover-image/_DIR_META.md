# _DIR_META.md

## Architecture Vision
四维封面生成引擎 (The Visual Alchemist)。
通过“类型、风格、文字、情绪”四个维度的参数化控制，将文章语义自动转化为高审美、出版级的封面图像。

## Member Index
- `SKILL.md`: [Manifest] 核心工作流 SOP 与指令集。
- `scripts/`: [Engine] 图像生成执行脚本 (executor.py)。
- `references/`: [Knowledge] 
  - `gallery.md`: 类型与风格预览库。
  - `logic.md`: 自动选择逻辑与兼容性矩阵。
  - `dimensions/`: 维度细节说明。
  - `styles/`: 20 种样式的底层定义。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 每次新增样式，必须同步更新 `references/gallery.md` 和 `_DIR_META.md`。
