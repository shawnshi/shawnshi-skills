# _DIR_META.md

## Architecture Vision
通用语义转换器 (The Format Alchemist)。
利用微软 MarkItDown 技术，将多达 20 种格式（PDF, Office, Images, ZIP）无损映射为干净、结构化的 Markdown 文本，为 LLM 的深度分析提供统一的数据基座。

## Member Index
- `SKILL.md`: [Manifest] 核心转换逻辑与 Agent SOP。
- `scripts/`: [Engine]
  - `converter.py`: 封装 uvx 调用的稳健执行引擎。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 所有的转换请求必须首选 `scripts/converter.py` 以确保错误处理的一致性。
