# _DIR_META.md

## Architecture Vision
万字级深度研究流水线 (Cognitive Assembly Line)。
通过“分章生产-状态同步-物理拼接”的工业化流程，突破 LLM 上下文限制，产出高密度、可审计的战略报告。

## Member Index
- `SKILL.md`: [Manifest] 核心流水线定义。
- `scripts/`: [Engine]
  - `memory_manager.py`: 语义核心维护（Working Memory）。
  - `assembler.py`: 物理拼接与密度卫士。
- `references/`: [Knowledge]
  - `workflows.md`: 详细SOP。
  - `editor.md`: 3D 逻辑审计标准。
- `agents/`: [UI] Gemini 身份。

> ⚠️ **Protocol**: 报告拼接严禁使用 LLM 摘要，必须调用 `assembler.py`。
