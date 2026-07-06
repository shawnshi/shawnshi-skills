---
name: tool-web-slide
version: 14.0.0
tier: action-allowed
description: '工业级、基于 Design Vault 的单网页 PPT 生成器。V14.0 原生支持 Antigravity 隔离沙盒体系与多模态视觉验收网关。引入按需生图(JIT)与零碰撞安全防线，支持长文本、高信噪比的顶级医疗/商业幻灯片渲染。'
triggers: ["PPT", "幻灯片", "网页演示", "电子杂志风", "瑞士风", "发布会", "卫宁模板", "医疗汇报", "HIT大屏", "临床工作流"]
---

# Tool Web Slide (Web Presentation Design Engine V14.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流，严禁跨越阶段：
1. view_file (读取底层架构 system-prompt.md)
2. ask_question / [No Tools] (询问设计意图，获取足够的信息)
3. write_to_file (作为 Strategist 生成 `spec_lock.md` 设计契约)
4. invoke_subagent (将 HTML 渲染工作派发给名为 "Web Slide Executor" 的子代理)
5. [END TURN] (主代理挂起，让人退场、环自转)

## 1. 核心流程与架构 (The Protocol)
本工具采用了极为严格的 **双角色分离 (Strategist & Executor)** 与 **静态质量门禁 (Quality Gate)** 架构。你必须分别扮演这两个角色。

### Phase 1: Strategist (策略规划与资源锁定)
**1. 导入核心规范.** 读取 `system-prompt.md` 与对应的样式词典（例如 `built-in-skills/style-magazine.md`）和版式系统 (`references/layout-patterns.md`)。
**2. 询问澄清.** 对于模糊需求，向用户提问确定页数、受众、格式。
**3. 锁定契约 (`spec_lock.md`).**
你必须将所有的设计决策提前规划完毕，并强制写入到与当前对话绑定的沙盒空间中：`brain/<conversation-id>/scratch/spec_lock.md`。绝对禁止写入全局目录。
**4. 结构化规划**: 将所有必要的颜色变量与版式基准定义在 `spec_lock.md` 中。不强制要求提前生成所有图像资源。

### Phase 2: Executor (执行与防漂移 - 交由子代理)
主代理在此阶段必须通过 `invoke_subagent` 派发任务。子代理 Prompt 参考如下：
> "读取沙盒路径 `brain/<conversation-id>/scratch/spec_lock.md`。作为 Executor，严格遵照契约将 `index.html` 写入同样的 `scratch/` 目录下。排版期间遇到空白或需视效填充的地方，请直接调用 `generate_image` 按需生图。完成后进行门禁检查。"

- **防漂移 (Anti-Drift)**: 子代理对于超过 10 页的 PPT，需要在生成每 5-8 页分块时，重新阅读一次 `spec_lock.md` 以防止 CSS 变量和幻灯片版式的幻觉漂移。
- **坐标体系**: 必须使用基于 CSS Grid 的版式，禁止使用纯粹的文档流思维。骨架 (Primary) 与修饰层 (Modifier) 必须严格分离。
- **DOM 动效约束**: 许多预设组件与底层动效引擎 (slide-engine.js) 强绑定，初始化透明度为 0。使用该类必须被包裹。如果只需静态排版，请使用原生的高阶类名配合内联样式。

### Phase 3: Multimodal Quality Gate (双重验收门禁 - 子代理自治)
子代理 HTML 写入后，必须执行以下验收协议：
1. **静态筛查**: 使用 MCP 或本地 lint 工具扫描 DOM 是否封闭、变量是否合法。报错必须原地修正。
2. **视觉审计**: 通过 Chrome DevTools MCP (`chrome-devtools-mcp`) 打开生成的本地 `index.html`，调用 `take_screenshot` 捕获核心幻灯片的渲染截图，并结合自身视觉能力审计是否存在“文字溢出”、“背景穿透”或“元素不可见”等低级错误。
全部通过后，向主代理汇报完工，并等待最终确认落盘。
