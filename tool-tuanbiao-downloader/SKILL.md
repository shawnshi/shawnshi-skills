---
name: tool-tuanbiao-downloader
version: 9.0.0
tier: action-allowed
description: '团体标准全自动下载器。当用户提到“批量下载团体标准”、“爬取特定国标”或提供标准编号时，务必强制挂载。该技能通过物理层全自动 ID 解析与 PDF 合并装订，确保 100% 的标准文件获取率。'
triggers: ["批量下载这组团体标准", "爬取特定编号的国标生成PDF"]
---

<strategy-gene>
Keywords: 团体标准, 标准下载, PDF 合并, 标准编号
Summary: 根据标准编号或批量任务解析并获取团体标准文档。
Strategy:
1. 解析标准编号、组织、版本和下载范围。
2. 使用脚本执行 ID 解析、下载、校验和合并。
3. 返回文件路径、成功清单和失败编号。
AVOID: 禁止把未下载成功的标准标为完成；禁止混淆标准版本。
</strategy-gene>

# Tool Tuanbiao Downloader (Strategic Edition V9.0 Native)

> **Vision**: 高效的标准文件采集工具，支持全自动化 ID 解析与 PDF 生成。本技能聚焦标准文件抓取和合并，不负责标准内容解读。

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. un_command (调用 downloader.py 抓取与合并)
2. write_to_file (落盘遥测数据)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Pre-flight Check (环境检查)
执行前请确认依赖：
`ash
$env:PYTHONIOENCODING="utf-8"; pip install -r "C:\Users\shich\.gemini\config\skills\tool-tuanbiao-downloader\scripts\requirements.txt"
`

### Phase 2: Execution (执行)
直接提供 **Path ID** 或 **预览 URL**，强制使用 un_command 运行并挂载编码锁：
`ash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-tuanbiao-downloader\scripts\downloader.py" <ID_OR_URL>
`
*   **示例 (ID)**: T_ISC_0095-2025
*   **示例 (URL)**: https://www.ttbz.org.cn/kkfileview/T_ISC_0095-2025/index.html

### Phase 3: Cross-Skill Synergy (跨技能协同)
下载并生成 PDF 后，建议执行以下后续操作：
*   **内容理解**: 激活并使用 	ool-document-summarizer 技能为生成的 PDF 生成战略摘要。
*   **战略审计**: 视情况通过 invoke_subagent 拉取专门的分析子代理，分析该标准在行业中的地位。

## 2. <Contracts> (输出与交付契约)
- **输入输出契约**: 输入必须是标准 ID 或有效预览 URL。输出必须是实际下载完成并合并后的 PDF 产物。
- **故障排查契约**: 若失败，必须指出是 ID 无效、依赖缺失还是下载链路中断。

## 3. <Failure_Taxonomy> (失败分类学)
- **路径与命令错误**: 不要在工作区手动复制代码，直接使用全路径调用脚本。
- **无效 ID**: 若下载立即终止，请检查 URL 是否包含 kkfileview。
- **未验证依赖**: 若依赖缺失，先修复环境再重试，不要改写协议绕过脚本。

## 4. Telemetry
- 任务完成后使用原生的 write_to_file 工具将本次执行的元数据以 JSON 格式保存至绝对路径：C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json。
