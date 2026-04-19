---
name: url-to-markdown
description: 网页原质提取器。当用户提供 URL 链接并要求“总结网页”、“保存为 MD”或遇到“重度 JS 渲染页面”难以抓取时，务必调用。该技能直控 Chrome CDP 协议，强制清除网页噪音，交付极致干净的 Markdown 结构。
triggers: ["将链接内容保存为MD格式", "清理该网页的干扰项转为MD"]
---

# Web Content Miner (CDP Engine)

High-fidelity web scraper that converts HTML to Markdown. Supports JavaScript rendering, lazy loading, and login sessions.

## When to Use
- 当用户提供 URL，希望抽取网页正文、保存为 Markdown，或页面依赖重度 JS 渲染时使用。
- 本技能聚焦网页提取与去噪，不负责通用网页总结。

## Core Capabilities
*   **CDP Rendering**: Uses Chrome DevTools Protocol to capture fully rendered DOM.
*   **Login Support**: `--wait` mode allows manual login before capture.
*   **Smart Parsing**: Auto-cleans navigation/ads, preserving main content.

## Workflow

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

## Resources
- `scripts/main.ts`
- `references/troubleshooting.md`
- Chrome CDP 环境

## Failure Modes
- 登录态页面必须显式走 `--wait`，不能假设已登录。
- 页面抓取失败时要区分是 Chrome 路径、超时还是页面状态问题。
- 不要把网页噪音清理成空文档。

## Output Contract
- 输出必须是实际提取出来的 Markdown 文件。
- 登录态页面必须遵循人工登录再回终端触发抓取的顺序。
- 若指定输出文件名，必须使用用户提供的目标路径。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "url-to-markdown", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
