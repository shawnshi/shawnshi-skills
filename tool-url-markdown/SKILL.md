---
name: tool-url-markdown
version: 9.0.0
tier: action-allowed
description: '网页原质提取器。当用户提供 URL 链接并要求“总结网页”、“保存为 MD”或遇到“重度 JS 渲染页面”难以抓取时，务必调用。该技能直控 Chrome CDP 协议，强制清除网页噪音，交付极致干净的 Markdown 结构。'
triggers: ["将链接内容保存为MD格式", "清理网页", "抓取这个网页", "总结这篇报道"]
---

<strategy-gene>
Keywords: URL 转 Markdown, 网页抓取, JS 渲染, CDP 协议
Summary: 强制降维打击复杂的网页渲染，精准提纯出无噪音的高质量 Markdown 结构。
Strategy:
1. 1. 获取意图：确定目标 URL 及其内容类型（是否需要登录、是否为重度动态渲染）。
2. 2. 调用物理引擎：通过 CDP 协议执行无头浏览器抓取，必要时挂起进入人工登录断点。
3. 3. 纯净提取：清理导航、广告与杂乱元素，强制输出原生 MD 文件并返回文件路径。
AVOID: 禁止凭空瞎编网页总结；禁止抓取失败时强行返回乱码内容；禁止在命令中使用任何沙盒宏。
</strategy-gene>

# Web Content Miner (CDP 原质提取引擎 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. 
2. un_command (调用 main.ts 抓取网页并输出)
3. write_to_file (写入遥测数据)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Context & Mode Selection
- 评估用户提供的 URL 属性。若为公开新闻、博客、文档，使用 **Standard Capture**。若为推特、Substack 或内部 Dashboard，必须强行进入 **Login-Gated Capture (--wait)** 模式。

### Phase 2: Engine Execution (引擎激活)
- 必须使用 
un_command 调用底层提取器。必须使用带有盘符的绝对物理路径。严禁使用任何宏变量。

#### Mode A: Standard Capture (公开页面直取)
`powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>"
`

#### Mode B: Login-Gated Capture (登录态断点阻击)
`powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>" --wait
`
**断点阻击操作流 (Protocol)**:
1. 终端执行后将自动唤醒 Chrome 浏览器界面。
2. **此时大模型必须向用户汇报**：“浏览器已开启，请您在浏览器中人工完成登录。登录完成后切回终端按 Enter 键，我将继续抓取。”
3. 等待进程结束。

#### Mode C: Custom Output (指定物理落盘位置)
`powershell
npx -y bun "C:\Users\shich\.gemini\config\skills\tool-url-markdown\scripts\main.ts" "<URL>" -o "C:\Users\shich\.gemini\MEMORY\raw\article.md"
`

### Phase 3: Delivery & Telemetry
- 提取完毕后，读取命令的终端输出，若成功将返回物理 Markdown 文件的路径。
- 大模型必须将该物理路径作为成果物交付给用户。
- 使用 write_to_file 工具将执行遥测保存至：
  C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json

## 2. <Contracts> (输出与交付契约)
- **绝对原质契约 (Absolute Fidelity)**：抓取到的 Markdown 必须保留页面的核心信息熵。系统会自动剥离侧边栏广告和导航栏，但正文文本、标题层级和核心代码块必须 100% 被保留。
- **物理交付契约 (Physical Delivery)**：必须向用户交付最终实际生成的 Markdown 物理路径。如果在抓取阶段抛出异常，大模型必须阅读报错并选择更换参数重试，严禁自己瞎编一份网页内容骗用户。

## 3. <Failure_Taxonomy> (失败分类学 / 逻辑硬锁)
- **沙盒宏塌陷 (Macro Deadlock)**：严禁在调取脚本或声明输出路径时使用旧版伪变量。必须使用绝对物理地址。
- **登录态击穿防御 (Wait-Mode Violation)**：如果目标页面属于强登录墙隔离区，未加 --wait 发起盲攻将被阻断重试。
- **虚假总结幻觉 (Summarization Hallucination)**：若明确返回超时或 403 错误，禁止根据 URL 名字凭空捏造网页总结。
