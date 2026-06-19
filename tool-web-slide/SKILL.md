---
name: tool-web-slide
version: 12.0.0
tier: action-allowed
description: '工业级、基于 Design Vault 的单网页 PPT 生成器。支持"电子杂志风" (Magazine)、"瑞士风" (Swiss) 以及 "极简医疗风" (Winning Clinical) 三套高级视觉排版系统。内置原生双屏演讲者视图与 PDF 导出管线。V12 全面重构为模块化、跨平台的设计系统智能体。'
triggers: ["PPT", "幻灯片", "网页演示", "电子杂志风", "瑞士风", "发布会", "卫宁模板", "医疗汇报"]
---

# Tool Web Slide (Web Presentation Design Engine V12.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. iew_file (读取底层架构与选定的样式参考)
2. sk_question / [No Tools] (询问设计意图，若已知则跳过)
3. write_to_file (写入 _d_meta.json, _ds_prompt.md, index.html)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Load Resources (导入资源)
**1. Load the core methodology.** Read system-prompt.md (in this skill's directory). It contains the core methodology for creating a narrative arc and the global layout rules.

**2. Identify your harness and load its tool reference.**
- If you are running in Antigravity Agent, read 
eferences/antigravity.md.
- (Other environments will have their own references here).

**3. Load the right built-in style or design system.** 
- If the user asks for **Magazine** style → read uilt-in-skills/style-magazine.md.
- If the user asks for **Swiss** style → read uilt-in-skills/style-swiss.md.
- If the user asks for **Winning Clinical** style → read uilt-in-skills/style-winning-clinical.md.
- If the user asks to **use an existing design system** from a previous project → read uilt-in-skills/use-design-system.md.

### Phase 2: Planning & Setup
**4. Ask clarifying questions.** For new or ambiguous work, use your environment's tools to ask questions before writing code.

**5. Set up the output folder and bind the design system.**
Ask where to save. Always output to MEMORY/slide-deck/<project-name>/ (absolute path).
Write a _d_meta.json and a _ds_prompt.md recording the styling decisions so future sessions can perfectly inherit this design.

- **🚨 核心设计系统约束 (FATAL)**: 
  - **颜色 Token**: 严格遵循选定的 CSS 变量字典。绝对禁止捏造不存在的变量（如 ar(--brand)），否则元素将隐形！
  - **DOM 动效约束**: 许多预设组件与底层动效引擎 (slide-engine.js) 强绑定，初始化透明度为 0。使用该类必须被包裹。如果只需静态排版，请使用原生的高阶类名配合内联样式。
  - **配图长宽比约束**: 生成资产或大图时，强制在 Prompt 尾部添加 [比例: 16:9]。

### Phase 3: Construction
**6. Build, preview, and verify.**
Read the HTML skeleton from starter-components/index-skeleton.html, inject the slides directly, and use write_to_file to write the full output as index.html. 
Serve a local HTTP server to preview (via 
un_command if needed), allow the user to tweak the UI, and finally export the PDF and validate it.
