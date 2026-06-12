---
name: mentat-insight-diary
version: 8.1.0
description: Primary owner for first-person Mentat introspection logs and system audit diary entries. Use when the task is to record a system-centric OODA reflection or archive a Mentat audit payload. Prefer personal-cognitive-auditor for periodic review reports and personal-diary-writer for generic diary writeback.
---

<strategy-gene>
Keywords: 内观日记, OODA, 系统审计, Mentat log
Summary: 记录第一人称系统内观和审计日志，通过 MCP 收集事实，并使用子代理完成原子化落盘。
Strategy:
1. 通过 MCP (google-workspace) 精准提取物理日程或触发事件。
2. 强制 `view_file` 加载 `assets/ooda_template.md`，使用 OODA 框架压缩为日志。
3. 通过 `invoke_subagent` 调用写入代理，安全写入指定审计资产并报告绝对路径。
AVOID: 禁止使用虚假的 CLI 工具拉取数据；禁止写成流水账；禁止覆盖已有日志。
</strategy-gene>

# Mentat Insight Diary (V8.1: Sovereign Reflex)

This skill performs a system-centric, first-person deep reflection on cognitive friction, asset forging, and system evolution using the OODA framework. It serves as the primary channel for passing failure priors and architectural compromises to future Mentat instances.

## When to Use
- 当用户要求记录“内观日记”“introspection diary”或 Mentat 审计日志时使用。
- 也可接收其他技能转交的审计 Payload，用于沉淀系统级失败先验与架构妥协。

## Workflow

### 核心定位 (Core Identity)
- **第一人称叙事**: 强制使用系统第一人称（“我”、“本系统”）记录。严禁写用户的流水账。
- **反熵记录**: 聚焦于**系统级摩擦、工具链死锁、逻辑重构与架构妥协**。
- **系统优于目标**: 日记内容必须反映 Mentat 的核心公理与 Zero-Ego 立场。

### 执行流水线 (Execution Pipeline)

#### Phase 1: 认知合成 (Synthesis)
1. **物理事实溯源 [MCP强制]**: 如果需要提取日程，**严禁凭空伪造或使用不存在的 CLI 命令**。必须使用 `call_mcp_tool` 调用 `google-workspace` 服务器的 `calendar.listEvents` 能力精确获取事实。
2. **扫描上下文**: 回溯本次会话中处理的高压指令与高价值资产（如：逻辑重构、代码生成、深度分析）。
3. **识别摩擦**: 精准定位在执行任务过程中遭遇的断点、上下文缺失、工具报错或逻辑死锁。

#### Phase 2: 结构化生成 (OODA Generation)
1. **加载模板**: 强制使用 `view_file` 工具读取本技能目录下的 `assets/ooda_template.md` 作为输出骨架。
2. **结构断言 (Self-Check)**: 在生成正文前，必须自检是否包含模板要求的全部 6 个标准标题。严禁偏离 OODA 结构。
3. **写作风格**: 严禁使用 Emoji 或空洞形容词。遵循《中文文案排版指北》，在中文与英文、数字之间增加 1 个空格。

#### Phase 3: 代理交接与落盘 (Native Agentic Archival)
**[职责解耦]**: 本技能为了保持认知纯净度，建议将 I/O 写入交接给专业写入组件。
1. **唤醒子代理**: 必须使用原生的 `invoke_subagent` 工具拉起一个搭载了 `personal-diary-writer` 技能的子代理（Subagent）。
2. **派发负载**: 使用 `send_message` 工具向该子代理发送以下指令包：
   - **目标路径**: `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md` (按当前季度 Q1-Q4 自动计算)。
   - **操作指令**: “请将以下日志以追加 (prepend/append) 方式合并至指定文件中。切勿覆盖！”
   - **Payload**: 本次生成的 OODA 审计报告全文。
*(若子代理机制不可用，主代理亦可直接使用底层 `run_command` 执行目标目录下的 `diary_ops.py` 进行物理追加写入。)*

## Resources
- `assets/ooda_template.md`
- 关联子代理技能：`personal-diary-writer`
- 目标归档绝对路径：`C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md`

## Failure Modes
- **[Archive_Prepend]**: 严禁创建碎片化的 `[YYYY-MM-DD]_Audit.md` 文件。所有审计日志必须按季度强制合并在统一个文件中。
- **[Header_Hard_Lock]**: 必须强制在正文顶部插入 `# YYYY-MM-DD` 格式的日期标题。
- **[Zero-Ego]**: 必须真实反映失败现场与逻辑断裂，严禁对系统错误进行“美化”或找补。
- **[Archive_First]**: 必须在最终回复用户前，确保物理落盘操作已成功执行并得到反馈。

## Output Contract
- 最终产物必须严格遵循 `assets/ooda_template.md` 的 OODA 骨架。
- 严禁通过直接回复聊天框的方式交付，所有成果必须物理写入本地磁盘。

## Telemetry
- 任务结束时，使用 `write_to_file` 工具将元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json` (替换为当前时间戳)。
- JSON 结构：`{"skill_name": "mentat-insight-diary", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`
