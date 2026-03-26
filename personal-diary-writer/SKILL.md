---
name: personal-diary-writer
version: 1.0.0
description: |
  个人日志原子写入器。当用户需要日常记录、简单的状态录入，或被其他高级系统（如 cognitive-auditor）调用落盘时激活。提供极度鲁棒的物理写入 I/O 组件。
---

# SKILL: Personal Diary Writer (Atomic I/O)

核心职责：高频、轻量级的日常状态录入与原子化文件操作。本系统只负责将内容写入文件，不涉及深度的战术复盘和健康审计。

## 1. 核心约束 (Core Mandates)
- **物理操作债防守**: 必须强绑定 `scripts/diary_ops.py` 进行 `prepend`。严禁直接使用 shell 重定向或常规写文件，以防止碎片文件或破坏原文件。
- **Win32 物理适配**: 永远使用 `--content_file` 传递要追加的复杂日志内容，防止命令行特殊字符转义崩溃。
- **语义本体**: 负责严格检查 `#tag` 的本体格式。必须确保所有标签采用 `#tag` 形式。

## 2. 执行协议 (Execution Protocol)
1. 接收用户的输入文本或由其他 Agent 传来的审计报告文本。
2. 规范化所有 `#tag` 标签。
3. 将内容写入临时文件 `tmp/log_entry.md`。
4. 调用 `scripts/diary_ops.py prepend --content_file tmp/log_entry.md` 执行安全写入。

## 3. 附属落盘协议 (Secondary Write-Backs)
### 3.1 Mentat Insight Archival (同步调用内观日记)
如果当前记录属于 Mentat Insight 的深度日志：
【强制要求】：必须同步生成一份符合 insight-diary 标准的 OODA 审计报告。
物理归档路径：`{root_dir}/memory/privacy/Diary/mentat_audit/[YYYY-QX]_Audit.md`。
归档策略：强制使用 `diary_ops.py` 执行季度级 prepend 操作。

### 3.2 Strategic Sync (记忆蒸馏)
如果从 `personal-cognitive-auditor` 接收到的数据中包含 `cognitive_depth_score >= 4` 的高价值产出：
【强制要求】：将核心认知结晶格式化为 JSON 写入 `tmp`，然后调用 `scripts/memory_sync.py` 同步至全局 `memory.md`。

## 4. Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "personal-diary-writer", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 5. 历史失效先验 (Gotchas)
- **[ARCHIVE_PREPEND]**: 必须使用 `diary_ops.py` 执行季度级 prepend，严禁创建碎片文件。
- ALWAYS use `--content_file` for multi-line log prepends.
- ENSURE all tags are wrapped in `#tag` format.
