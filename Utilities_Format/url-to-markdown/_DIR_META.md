# _DIR_META.md

## Architecture Vision
基于 Chrome CDP 的高保真网页语义提取引擎。
支持动态渲染（JavaScript）、登录态保持和懒加载触发，将复杂的 HTML DOM 降维为干净的 Markdown 文档。

## Member Index
- `SKILL.md`: [Manifest] 核心指令与抓取模式 SOP。
- `scripts/`: [Engine] TypeScript 抓取逻辑 (main.ts, cdp.ts)。
- `references/`: [Knowledge] 故障排查与环境配置。
- `agents/`: [UI] Gemini 身份定义。

> ⚠️ **Protocol**: 脚本依赖 `bun` 运行环境。
