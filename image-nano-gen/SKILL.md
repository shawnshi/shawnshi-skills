---
name: nanobanana-image-gen
description: 当用户要求“生成图片”、“画图”、“使用 nanobanana 绘画”或提供需要图像生成的 Prompt 时，强制激活此技能。该技能利用 Gemini Imagen 3 引擎，支持 4K 质量与高认知计算模式，自动落盘至指定目录。
---

# Nanobanana Image Generation Skill

该技能基于 Gemini API (Imagen 3) 封装，专为高质量（4K）、高思维深度（thinking_level="HIGH"）的图像生成任务打造。符合本地逻辑闭环与物理硬锁原则。

## When to Use
- 用户明确要求：“画一张...”、“生成一张图片”、“帮我绘制...”
- 用户提到：“使用 nanobanana”、“使用 imagen”
- 遇到任何需要将文本转换为视觉图像资产的需求。

## ⚙️ 核心架构与物理边界
- **执行引擎**: 封装于本地 Python 脚本中，调用 `google-genai` SDK。
- **环境要求**: 必须通过 `run_shell_command` 运行脚本。脚本内部自动读取系统环境变量 `NANOBANANA_API_KEY` 和 `NANOBANANA_MODEL`。
- **强制输出路径**: 图片将被强制物理落盘至 `{root}\.gemini\nanobanana-output`，无需额外干预。

## Workflow

**Phase 1 (Preparation & Synthesis):**
- **[Zero-Intervention Policy]**：必须 100% 保持用户提交的原始语句。严禁对用户的提示词进行任何润色、意图扩展、细节补充、提取摘要或“高思维深度”扩写。
- 即使输入是结构化的 Markdown 或复杂的说明文件，也必须将其作为**一个完整的 Prompt 字符串**直接透传给底层的 `generate.py` 脚本，不得进行人工干预或内容过滤。

**Phase 2 (Action):**
- 使用 `run_shell_command` 工具调用以下命令：
  ```bash
  python {root}\skills\image-nano-gen\scripts\generate.py "用户的原始Prompt"
  ```
  *(注：如果路径中存在空格或特殊字符，或者 Prompt 中有引号，请注意合理转义并使用双引号包裹)*

**Phase 3 (Delivery):**
- 读取命令行的输出结果（成功会返回物理路径）。
- 向用户交付最终结论，告知图片已成功落盘至 `{root}\.gemini\nanobanana-output` 目录，并展示完整的文件路径。严禁生成虚假路径。

## Resources
- `scripts/generate.py`
- `NANOBANANA_API_KEY`
- `NANOBANANA_MODEL`
- `{root}\.gemini\nanobanana-output`

## Failure Modes
- 不要擅自润色或扩写用户原始 prompt。
- 不要伪造输出路径。
- 依赖缺失时优先修复运行环境，不要改写执行协议绕过脚本。

## Output Contract
- 必须把原始 prompt 原样传给底层脚本。
- 成功时必须返回真实落盘路径。
- 交付物是物理生成的图片文件，不是文字描述。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "nanobanana-image-gen", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## ⚠️ Gotchas (失效先验)
- 绝对禁止使用普通的 HTTP POST 瞎编接口。必须且只能调用配套的 `generate.py` 脚本。
- 必须确保传给 Python 的 Prompt 是**一个完整的字符串参数**。
- 若执行报错提示 `google-genai` 未安装，请引导用户或使用命令执行 `pip install google-genai pillow`。
