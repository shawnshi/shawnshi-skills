---
name: tool-url-markdown
version: 8.1.0
description: 网页原质提取器。当用户提供 URL 链接并要求“总结网页”、“保存为 MD”或遇到“重度 JS 渲染页面”难以抓取时，务必调用。该技能直控 Chrome CDP 协议，强制清除网页噪音，交付极致干净的 Markdown 结构。
triggers: ["将链接内容保存为MD格式", "清理网页", "抓取这个网页", "总结这篇报道"]
---

<strategy-gene>
Keywords: URL 转 Markdown, 网页抓取, JS 渲染, CDP 协议
Summary: 强制降维打击复杂的网页渲染，精准提纯出无噪音的高质量 Markdown 结构。
Strategy:
1. 获取意图：确定目标 URL 及其内容类型（是否需要登录、是否为重度动态渲染）。
2. 调用物理引擎：通过 CDP 协议执行无头浏览器抓取，必要时挂起进入人工登录断点。
3. 纯净提取：清理导航、广告与杂乱元素，强制输出原生 MD 文件并返回文件路径。
AVOID: 禁止凭空瞎编网页总结；禁止抓取失败时强行返回乱码内容；禁止在命令中使用任何沙盒宏（如 `{root_dir}`）。
</strategy-gene>

# Web Content Miner (CDP 原质提取引擎 V8.1 Native)

> **Vision**: High-fidelity web scraper. 绝不在未渲染完整的空壳 HTML 面前妥协。通过 Chrome DevTools Protocol 强制接管浏览器，暴力击破 JS 渲染障碍，交付极致干净的信息资产。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Context & Mode Selection [Mode: PLANNING]
- 评估用户提供的 URL 属性。若为公开新闻、博客、文档，使用 **Standard Capture**。若为推特、Substack 或内部 Dashboard，必须强行进入 **Login-Gated Capture (`--wait`)** 模式。

### Phase 2: Engine Execution (引擎激活) [Mode: EXECUTION]
- 必须使用 `run_command` 调用底层提取器。
- 必须使用带有盘符的绝对物理路径。严禁使用任何宏变量。

#### Mode A: Standard Capture (公开页面直取)
```powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>"
```

#### Mode B: Login-Gated Capture (登录态断点阻击)
```powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>" --wait
```
**断点阻击操作流 (Protocol)**:
1. 终端执行后将自动唤醒 Chrome 浏览器界面。
2. **此时大模型必须向用户汇报**：“浏览器已开启，请您在浏览器中人工完成登录。登录完成后切回终端按 Enter 键，我将继续抓取。”
3. 等待进程结束。

#### Mode C: Custom Output (指定物理落盘位置)
```powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>" -o "C:\Users\shich\.gemini\MEMORY\raw\article.md"
```

### Phase 3: Delivery & Telemetry [Mode: EXECUTION]
- 提取完毕后，读取命令的终端输出，若成功将返回物理 Markdown 文件的路径。
- 大模型必须将该物理路径作为成果物交付给用户。
- 使用 `write_to_file` 工具将执行遥测保存至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 2. <Contracts> (输出与交付契约)
- **绝对原质契约 (Absolute Fidelity)**：抓取到的 Markdown 必须保留页面的核心信息熵。系统会自动剥离侧边栏广告和导航栏，但正文文本、标题层级和核心代码块必须 100% 被保留。
- **物理交付契约 (Physical Delivery)**：必须向用户交付最终实际生成的 Markdown 物理路径。如果在抓取阶段抛出异常，大模型必须阅读报错并选择更换参数重试，严禁自己瞎编一份网页内容骗用户“已经总结好了”。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **沙盒宏塌陷 (Macro Deadlock)**：严禁在调取脚本或声明输出路径时使用旧版伪变量（如 `{root_dir}` 或 `{root}`）。若被探测到使用伪变量拼接路径，系统将直接判处越权并阻断终端执行。必须使用 `C:\Users\shich\.gemini\...` 绝对物理地址。
- **登录态击穿防御 (Wait-Mode Violation)**：如果目标页面属于强登录墙隔离区（例如内网或推特），但大模型并未加上 `--wait` 参数就发起了盲目强攻，将会直接抓回来一堆报错代码。此行为将被视为重大战略失误并强制打回重试。
- **虚假总结幻觉 (Summarization Hallucination)**：如果抓取引擎明确返回了超时或 403 Forbidden 错误，绝对禁止大模型根据 URL 的名字去“凭空捏造”一份网页总结。
- **工具伪造 (Tool Forgery)**：记录遥测日志必须且只能使用 Native 强规范的 `write_to_file` 工具，严禁使用旧版 `write_file` 导致 I/O 死锁。
