---
name: url-to-markdown
description: 抓取任何 URL（包括重度 JS 或登录隔离网页）并转换为干净的 markdown。直控 Chrome CDP 协议。
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
npx -y bun C:\Users\shich\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>"
```

### 2. Login-Gated Capture (Private Pages)
For Twitter, Substack, or internal dashboards:
```bash
npx -y bun C:\Users\shich\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>" --wait
```
**Protocol**:
1.  Browser window will open.
2.  **Manually** log in or navigate to the target state.
3.  Return to terminal and press **Enter** to trigger capture.

### 3. Custom Output
Specify filename directly:
```bash
npx -y bun C:\Users\shich\.gemini\skills\url-to-markdown\scripts\main.ts "<URL>" -o "docs/article.md"
```

## Troubleshooting
See `references/troubleshooting.md` for Chrome path configuration and timeout adjustments.
