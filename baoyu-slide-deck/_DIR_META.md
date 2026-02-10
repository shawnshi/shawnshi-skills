# _DIR_META.md

## Architecture Vision
幻灯片语义工坊 (The Presentation Architect)。
将 Markdown 内容转化为出版级 PPTX。支持多模型渲染、文本可编辑化（Editable Text）及智能断点续传（Smart Resume），实现从“语义”到“视觉演示”的无损映射。

## Member Index
- `SKILL.md`: [Manifest] 核心指令、SOP 与维护协议。
- `scripts/`: [Engine]
  - `generate-prompts.py`: 语义转视觉提示词。
  - `generate-images.py`: 多模型渲染引擎。
  - `build-deck.py`: PPTX/PDF 组装器。
- `references/`: [Knowledge]
  - `cli-reference.md`: 详细参数与子命令。
  - `workflows.md`: 高级修改与调试流程。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 所有的 PPTX 生成逻辑必须通过 `scripts/build-deck.py` 执行，严禁手动操作 ZIP 包。
