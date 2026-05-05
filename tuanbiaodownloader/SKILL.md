---
name: tuanbiaodownloader
description: 团体标准全自动下载器。当用户提到“批量下载团体标准”、“爬取特定国标”或提供标准编号时，务必强制挂载。该技能通过物理层全自动 ID 解析与 PDF 合并装订，确保 100% 的标准文件获取率。
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

# Tuanbiao Downloader (Strategic Edition)

高效的标准文件采集工具，支持全自动化 ID 解析与 PDF 生成。

## When to Use
- 当用户需要批量下载团体标准、根据标准编号抓取内容或从预览页生成 PDF 时使用。
- 本技能聚焦标准文件抓取和合并，不负责标准内容解读。

## Core Capabilities
*   **Smart Resolution**: 自动从 URL（如 ttbz.org.cn 预览链接）中提取 Path ID。
*   **Resume Support**: 自动检测已下载页面，支持断点续传。
*   **PDF Auto-Merge**: 下载完成后自动合并为出版级 PDF。

## Workflow

### 1. Pre-flight Check (环境检查)
执行前请确认依赖：
```bash
# 若报错，请安装
pip install -r {root_dir}\.gemini\skills\tuanbiaodownloader\scripts\requirements.txt
```

### 2. Execution (执行)
直接提供 **Path ID** 或 **预览 URL**：
```bash
python {root_dir}\.gemini\skills\tuanbiaodownloader\scripts\downloader.py <ID_OR_URL>
```
*   **示例 (ID)**: `T_ISC_0095-2025`
*   **示例 (URL)**: `https://www.ttbz.org.cn/kkfileview/T_ISC_0095-2025/index.html`

### 3. Cross-Skill Synergy (跨技能协同)
下载并生成 PDF 后，建议执行以下后续操作：
*   **内容理解**: 调用 `${document-summarizer}` 为生成的 PDF 生成摘要。
*   **战略审计**: 调用 `${research-analyst}` 分析该标准在行业中的地位。

## Resources
- `scripts/downloader.py`
- `scripts/requirements.txt`
- `references/troubleshooting.md`

## Failure Modes
*   ❌ **禁止手动复制**: 不要在工作区手动复制代码，直接使用全路径调用脚本。
*   ❌ **无效 ID**: 若下载立即终止，请检查 URL 是否包含 `kkfileview`。
*   若依赖缺失，先修复环境再重试，不要改写协议绕过脚本。

## Output Contract
- 输入必须是标准 ID 或有效预览 URL。
- 输出必须是实际下载完成并合并后的 PDF 产物。
- 若失败，必须指出是 ID 无效、依赖缺失还是下载链路中断。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "tuanbiaodownloader", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
