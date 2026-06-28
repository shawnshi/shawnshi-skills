---
name: tool-web-slide
version: 13.1.0
tier: action-allowed
description: '工业级、基于 Design Vault 的单网页 PPT 生成器。V13.1 引入了顶尖医疗数字化 (HIT) 领域的原生支持（架构图层、临床工作流、对标矩阵），以及 Strategist/Executor 角色分离与 spec_lock 防漂移机制，原生支持 AST 质量门禁与主次版式系统，实现完美的长文本、高信噪比幻灯片生成。'
triggers: ["PPT", "幻灯片", "网页演示", "电子杂志风", "瑞士风", "发布会", "卫宁模板", "医疗汇报", "HIT大屏", "临床工作流"]
---

# Tool Web Slide (Web Presentation Design Engine V13.0 Native)

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
你必须将所有的设计决策提前规划完毕，并写入到绝对路径 `MEMORY/slide-deck/<project-name>/spec_lock.md` 中。
这替代了旧版的 `_ds_prompt.md`，它是一份机器可读的强制契约。
- **🚨 核心设计系统约束 (FATAL)**: 
  - **颜色 Token**: 严格遵循选定的 CSS 变量字典。绝对禁止捏造不存在的变量（如 `var(--brand)`），否则元素将隐形！
  - **配图长宽比约束**: 生成资产或大图时，强制在 Prompt 尾部添加 `[比例: 16:9]`。
**4. 图像资产解耦**: 所有的生图 (调用 `image-nano-gen`) 和搜图，必须在此阶段完成。Executor 写 HTML 时，只能直接使用 `spec_lock.md` 中已经准备好的图片路径。禁止在写 HTML 时当场去生图，防止严重上下文挤兑。

### Phase 2: Executor (执行与防漂移 - 交由子代理)
主代理在此阶段必须通过 `invoke_subagent` 派发任务。子代理 Prompt 参考如下：
> "读取 `MEMORY/slide-deck/<project-name>/spec_lock.md`。作为 Executor，严格遵照契约写入 `index.html` (基于 `starter-components/index-skeleton.html`)。完成后运行 `html_quality_checker.mjs`，如有报错必须自行重写。全部通过后向我报告。"

- **防漂移 (Anti-Drift)**: 子代理对于超过 10 页的 PPT，需要在生成每 5-8 页分块时，重新阅读一次 `spec_lock.md` 以防止 CSS 变量和幻灯片版式的幻觉漂移。
- **坐标体系**: 必须使用基于 CSS Grid 的版式，禁止使用纯粹的文档流思维。骨架 (Primary) 与修饰层 (Modifier) 必须严格分离。
- **DOM 动效约束**: 许多预设组件与底层动效引擎 (slide-engine.js) 强绑定，初始化透明度为 0。使用该类必须被包裹。如果只需静态排版，请使用原生的高阶类名配合内联样式。

### Phase 3: Quality Gate (强制门禁 - 子代理自治)
子代理 HTML 写入后，必须使用 `run_command` 运行 `node scripts/html_quality_checker.mjs MEMORY/slide-deck/<project-name>/index.html`。
如果脚本报错，子代理**必须原地重写报错的幻灯片并重新执行检查**，禁止使用自动修复，禁止忽视报错直接报告。
通过后，子代理启动 HTTP Server 预览并告知主代理任务完成。
