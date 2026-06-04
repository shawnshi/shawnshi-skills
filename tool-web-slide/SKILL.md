---
name: tool-web-slide
description: 工业级、基于 Design Vault 的单网页 PPT 生成器。支持"电子杂志风" (Magazine) 和 "瑞士国际主义风" (Swiss) 两种高级视觉排版系统。内置原生双屏演讲者视图与 PDF 导出管线。
---

<strategy-gene>
Keywords: 网页 PPT, 电子杂志, 瑞士风, 演讲者视图, Design Vault
Summary: 通过 Design Vault 强力约束和强类型校验生成高质量 HTML PPT。
Strategy:
1. 需求澄清：确定主题、风格（A 或 B）、大纲。
2. 知识装配：强制调用 `scripts/assemble-context.mjs` 获取排版规范。
3. 复制模板：从 `design-vault/` 复制对应风格的 `template.html`。
4. 严格编写：遵守获取的 Design Vault 约束（CSS类、网格规则、图片比例等）进行内容填充。
5. 质量门检：必须通过 `scripts/validate-deck.mjs` 物理检查。
AVOID: 禁止在运行 assemble-context 之前凭借记忆猜测 CSS 类名；禁止绕过 validate-deck 校验直接交付。
</strategy-gene>

## 这个 Skill 做什么

生成一份**高工业标准、强一致性**的单文件 HTML 演示文稿。
本智能体不依赖随意的 Prompt 进行排版，而是基于 **Design Vault (设计金库)** 架构运行。

支持两套完全隔离的美学风格：
*   **风格 A · 电子杂志风 (Magazine)**：WebGL 流体背景、衬线大标题、图片网格、人文感。
*   **风格 B · 瑞士国际主义 (Swiss)**：极致字号对比、绝对无衬线、12列严格网格、高反差色块。

**交付物特性**：
*   原生支持**演讲者视图**：按 `S` 键呼出双屏同步控制台（含计时器与 `<aside class="notes">` 逐字稿）。
*   原生支持**静态导出**：自带无头浏览器 PDF 导出脚本。

---

## 核心工作流 (Workflow)

### Step 1 · 需求澄清 (Clarification)
如果用户没有提供明确的需求，请提问对齐：
1.  **风格选择**：A (杂志风) 还是 B (瑞士风)？（这是最核心的决策）
2.  **受众与时长**：给谁看？讲多久？
3.  **素材与图片**：有没有大纲？有没有配图或截图需要处理？

### Step 2 · 组装上下文 (Context Assembly) - 核心动作！
在明确风格后，**必须第一步在终端运行**对应的知识装配器：
*   风格 A：`node <SKILL_ROOT>/scripts/assemble-context.mjs A`
*   风格 B：`node <SKILL_ROOT>/scripts/assemble-context.mjs B`

**必须仔细阅读输出的 `CONTEXT.md` 文本。** 里面包含了你写代码所需的**所有**：
*   允许使用的 CSS 类名 (Layouts & Tokens)
*   主题颜色预设 (Themes)
*   避坑指南与常见错误 (Anti-patterns & Checklist)

### Step 3 · 拷贝种子模板
根据选择的风格，将对应的设计系统基座拷贝到项目目录：
*   风格 A: `cp <SKILL_ROOT>/design-vault/magazine/template.html 项目路径/ppt/index.html`
*   风格 B: `cp <SKILL_ROOT>/design-vault/swiss/template.html 项目路径/ppt/index.html`

*(记得将 `<title>[必填]...</title>` 替换为真实标题。)*

### Step 4 · 填充内容 (Implementation)
*   **完全遵照 Step 2 组装的知识编写 HTML。**
*   不要“发明”未定义的 class。不要凭记忆盲写。
*   如果遇到长篇复杂逻辑，请在 `<section>` 内部生成 `<aside class="notes">这里是演讲者逐字稿</aside>`，供双屏演讲者视图读取。

### Step 5 · 强制质量门 (Quality Gate)
生成完成后，**必须在终端运行**质量门校验：
`node <SKILL_ROOT>/scripts/validate-deck.mjs 项目路径/ppt/index.html`

*   **如果报错 (Exit 1)**：阅读报错信息，修正缺失的 CSS 类名、拼写错误或版式违规。重新验证直到通过。
*   **如果通过**：交付给用户，并提示可以按 `S` 键开启演讲者模式。

### 附加能力：PDF 导出
如果用户需要 PDF，直接调用内置工具：
`node <SKILL_ROOT>/scripts/export-pdf.mjs 项目路径/ppt/index.html 项目路径/ppt/deck.pdf`

---




## When to Use
TBD.

## Workflow
TBD.

## Resources
TBD.

## Failure Modes
*   如果在 `validate-deck.mjs` 中卡死报错，说明你违背了 Design Vault 的硬性约束。仔细对比模板里的 `<style>` 和你写出的 class。
*   如果图片撑破了屏幕，检查是否遗漏了固定比例图片槽位（如 `.frame-img.r-16x9`）。


## Output Contract
TBD.

## Telemetry
TBD.
