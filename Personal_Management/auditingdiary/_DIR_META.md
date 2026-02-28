# _DIR_META.md

## Architecture Vision
个人知识管理（PKM）的认知审计层。
通过结构化的日志记录与周期性复盘，降低个人认知熵值，保持长期战略对齐。

## Member Index
- `SKILL.md`: [Required] 核心指令与工作流。
- `scripts/diary_ops.py`: [Engine] 负责原子写入、搜索与统计的确定性引擎。
- `prompts/`: [Assets] 周期性审计（周/月/年）的提示词模板。
- `references/`: [Knowledge]
  - `templates.md`: 日志与审计报告的结构模板。
  - `config.md`: 路径与偏好配置。
  - `semantic_layer.md`: 标签本体定义与语义约束。
  - `work_nodes.md`: 审计扫描目录索引。
- `agents/`: [UI] Gemini 适配配置。

> ⚠️ **Protocol**: 任何对日志文件 I/O 逻辑的修改，必须在 `scripts/diary_ops.py` 中进行，严禁在 SKILL.md 中硬编码读写逻辑。
