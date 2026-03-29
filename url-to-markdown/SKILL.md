---
name: url-to-markdown
description: 网页原质提取器。当用户提供 URL 链接并要求“总结网页”、“保存为 MD”或遇到“重度 JS 渲染页面”难以抓取时，务必调用。该技能直控 Chrome CDP 协议，强制清除网页噪音，交付极致干净的 Markdown 结构。
triggers: ["将链接内容保存为MD格式", "清理该网页的干扰项转为MD"]
---

# Web Content Miner (CDP Engine)

High-fidelity web scraper that converts HTML to Markdown. Supports JavaScript rendering, lazy loading, and login sessions.

## Core Capabilities
*   **CDP Rendering**: Uses Chrome DevTools Protocol to capture fully rendered DOM.
*   **Login Support**: `--wait` mode allows manual login before capture.
*   **Smart Parsing**: Auto-cleans navigation/ads, preserving main content.

## Workflow SOP

### 1. Standard Capture (Public Pages)
For news, blogs, or documentation:
```bash
npx -y bun {root_dir}\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>"
```

### 2. Login-Gated Capture (Private Pages)
For Twitter, Substack, or internal dashboards:
```bash
npx -y bun {root_dir}\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>" --wait
```
**Protocol**:
1.  Browser window will open.
2.  **Manually** log in or navigate to the target state.
3.  Return to terminal and press **Enter** to trigger capture.

### 3. Custom Output
Specify filename directly:
```bash
npx -y bun {root_dir}\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>" -o "docs/article.md"
```

## Troubleshooting
See `references/troubleshooting.md` for Chrome path configuration and timeout adjustments.

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "logic-adversary", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
