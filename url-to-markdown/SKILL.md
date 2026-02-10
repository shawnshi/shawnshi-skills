---
name: url-to-markdown
description: Fetch any URL (including JS-heavy or login-gated pages) and convert to clean markdown. Uses Chrome CDP for high-fidelity rendering.
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
