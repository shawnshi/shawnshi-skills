---
name: tuanbiaodownloader
description: Batch downloads images from standard repositories (tuanbiao) and automatically merges them into a PDF. Supports ID extraction from URLs. Use when downloading "团体标准" (tuanbiao) or standards from ttbz.org.cn.
---

# Tuanbiao Downloader (Strategic Edition)

高效的标准文件采集工具，支持全自动化 ID 解析与 PDF 生成。

## Core Capabilities
*   **Smart Resolution**: 自动从 URL（如 ttbz.org.cn 预览链接）中提取 Path ID。
*   **Resume Support**: 自动检测已下载页面，支持断点续传。
*   **PDF Auto-Merge**: 下载完成后自动合并为出版级 PDF。

## Workflow

### 1. Pre-flight Check (环境检查)
执行前请确认依赖：
```bash
# 若报错，请安装
pip install -r C:\Users\shich\.gemini\skills\tuanbiaodownloader\scripts\requirements.txt
```

### 2. Execution (执行)
直接提供 **Path ID** 或 **预览 URL**：
```bash
python C:\Users\shich\.gemini\skills\tuanbiaodownloader\scripts\downloader.py <ID_OR_URL>
```
*   **示例 (ID)**: `T_ISC_0095-2025`
*   **示例 (URL)**: `https://www.ttbz.org.cn/kkfileview/T_ISC_0095-2025/index.html`

### 3. Cross-Skill Synergy (跨技能协同)
下载并生成 PDF 后，建议执行以下后续操作：
*   **内容理解**: 调用 `${document-summarizer}` 为生成的 PDF 生成摘要。
*   **战略审计**: 调用 `${research-analyst}` 分析该标准在行业中的地位。

## Troubleshooting
详细调试指南见 `references/troubleshooting.md`。

## Anti-Patterns
*   ❌ **禁止手动复制**: 不要在工作区手动复制代码，直接使用全路径调用脚本。
*   ❌ **无效 ID**: 若下载立即终止，请检查 URL 是否包含 `kkfileview`。
