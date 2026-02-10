# _DIR_META.md

## Architecture Vision
知识库神经连接器 (The Knowledge Connector)。
实现 Gemini 与 Google NotebookLM 的深层桥接。通过浏览器自动化与持久化认证，提供具备“证据支撑”与“引用溯源”的确定性知识查询能力。

## Member Index
- `SKILL.md`: [Manifest] 核心工作流 SOP 与关键触发。
- `scripts/`: [Engine]
  - `run.py`: 环境隔离与脚本调度中心。
  - `ask_question.py`: 核心查询交互逻辑。
- `data/`: [Storage] 隔离存储认证状态与笔记本库（Gitignored）。
- `references/`: [Knowledge] 详细 CLI 手册、认证指南与故障排查。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 所有操作必须通过 `scripts/run.py` 调度，严禁直接调用子脚本。
