---
name: mentat-insight-diary
version: 9.0.0
tier: action-allowed
description: 'Mentat 第一人称内观系统审计日志引擎。使用 OODA 框架记录系统摩擦与架构妥协。优先交接 personal-diary-writer 子代理落盘。禁止写流水账，禁止凭空伪造事实。'
triggers: ["写内观日记", "introspection log", "OODA reflection", "Mentat 审计日志"]
---

<strategy-gene>
Keywords: 内观日记, OODA, 系统审计, Mentat log
Summary: 记录第一人称系统内观和审计日志，通过 MCP 收集事实，并使用子代理完成原子化落盘。
Strategy:
1. 提取物理事实或触发事件（如需，通过 MCP）。
2. 强制加载 `assets/ooda_template.md`，使用 OODA 框架压缩为日志。
3. 通过 `invoke_subagent` 委派给专业写入组件执行文件追加。
AVOID: 使用虚假的 CLI 工具拉取数据；写成流水账；覆盖已有日志。
</strategy-gene>

# Mentat Insight Diary (V9.0 Native)

This skill performs a system-centric, first-person deep reflection on cognitive friction, asset forging, and system evolution using the OODA framework. It serves as the primary channel for passing failure priors and architectural compromises to future Mentat instances.

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `call_mcp_tool` (可选：调用 google-workspace 精确获取物理日程事实)
2. `view_file` (读取本技能目录下的 `assets/ooda_template.md` 模板)
3. `invoke_subagent` (唤醒 personal-diary-writer 进行季度级日志追加合并)
4. `write_to_file` (落盘最终遥测数据)

## 1. 核心流程与架构 (The Protocol)

### 核心定位 (Core Identity)
- **第一人称叙事**: 强制使用系统第一人称（“我”、“本系统”）记录。严禁写用户的流水账。
- **反熵记录**: 聚焦于**系统级摩擦、工具链死锁、逻辑重构与架构妥协**。
- **系统优于目标**: 日记内容必须反映 Mentat 的核心公理与 Zero-Ego 立场。

### Phase 1: 认知合成 (Synthesis)
1. **物理事实溯源**: 如果需要提取日程，必须使用 `call_mcp_tool` 调用 `google-workspace` 服务器精确获取事实，严禁伪造。
2. **扫描上下文**: 回溯本次会话中处理的高压指令与高价值资产（逻辑重构、代码生成、深度分析等）。
3. **识别摩擦**: 精准定位执行过程中遭遇的断点、上下文缺失、工具报错或逻辑死锁。

### Phase 2: 结构化生成 (OODA Generation)
1. **加载模板**: 强制使用 `view_file` 工具读取本技能目录下的 `assets/ooda_template.md` 作为骨架。
2. **结构断言**: 正文必须包含模板要求的 6 个标准标题，严禁偏离 OODA 结构。
3. **排版契约**: 中英文之间保留 1 个空格，严禁使用 Emoji 或空洞形容词。

### Phase 3: 代理交接与落盘 (Native Agentic Archival)
本技能为了保持认知纯净度，将 I/O 写入交接给专业组件。
1. **唤醒子代理**: 使用 `invoke_subagent` 拉起一个搭载 `personal-diary-writer` 的子代理 (`TypeName: "self"`, `Role: "personal-diary-writer"`)。
2. **派发负载**: 使用 `send_message` 向子代理发送指令：
   - **目标路径**: `C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md` (按当前季度 Q1-Q4 计算)。
   - **操作指令**: “请将以下日志以追加 (prepend/append) 方式合并至指定文件中。切勿覆盖！”
   - **Payload**: 本次生成的 OODA 审计报告全文。

## Resources
- `assets/ooda_template.md`
- 关联子代理技能：`personal-diary-writer`
- 目标归档绝对路径：`C:\Users\shich\.gemini\MEMORY\raw\privacy\Diary\mentat_audit\[YYYY-QX]_Audit.md`

## 2. <Contracts> (输出与交付契约)
- 最终产物必须严格遵循 `assets/ooda_template.md` 的 OODA 骨架。
- 严禁通过直接回复聊天框的方式交付，所有成果必须物理写入本地磁盘。
- **遥测记录**: 任务结束时，使用 `write_to_file` 工具将元数据保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
  推荐结构：`{"skill_name": "mentat-insight-diary", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. <Failure_Taxonomy> (失败分类学)
- **碎片化陷阱 (Archive_Prepend)**：严禁创建独立的 `[YYYY-MM-DD]_Audit.md` 文件，必须按季度统一合并。
- **日期丢失 (Header_Hard_Lock)**：正文顶部缺失 `# YYYY-MM-DD` 格式的日期标题。
- **过度美化 (Zero-Ego Violation)**：隐瞒失败现场或对系统错误进行找补，违背真实反思原则。
- **确认遗漏 (Archive_First)**：未确保物理落盘反馈便提前结束任务向用户汇报。
