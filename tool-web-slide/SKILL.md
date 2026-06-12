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
3. 初始化物理基座：使用原生的文件工具将模板物理拷贝至标准存放路径，拒绝脆弱的 shell 复制。
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

## Workflow
1. **Clarification (需求对齐)**：强制与用户确认主题风格（A：电子杂志风；B：瑞士风）以及具体的图文内容与大纲。
2. **Context Assembly (上下文装配)**：使用 `run_command` 在终端运行知识装配器：
   - `node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\assemble-context.mjs <A|B>`
   运行后，必须仔细阅读输出的上下文文本，其中包含所有允许使用的 CSS 类名和版式规则。
3. **Template Cloning (初始化物理基座)**：使用原生的 `view_file` 和 `write_to_file` 工具，将 `C:\Users\shich\.gemini\config\skills\tool-web-slide\design-vault\<style>\template.html` 的内容原封不动地物理拷贝到标准输出目录：**强制存放于 `C:\Users\shich\.gemini\slide-deck\<项目名称>\index.html`**。不要使用容易失败的 shell `cp` 命令。
4. **Strict Implementation (严格编码)**：
   - 严禁臆造 CSS 类名，所有排版必须组合 Design Vault 提供的基础组件。
   - **⚠️ 品牌契约覆盖 (Brand Identity Injection)**：如果是为“卫宁健康”或医疗数字化议题生成 PPT，**必须优先读取系统的 `pai/DESIGN.md`**。将其中的核心色（如 `#005EB8`）覆盖至生成模板 `:root` 的 `--accent`、`--ink-rgb` 等变量，并强制将字体栈覆盖为 `DESIGN.md` 中的要求。
   - 所有软件截图、图表必须根据规范使用 `.mockup-window` 或 `.shadow-float` 封装。
   - 每一页如果有口播文案，强制写入 `<aside class="notes">您的逐字稿</aside>` 供演讲者模式读取。
5. **Quality Gate (物理门检)**：强制使用 `run_command` 运行校验器：
   - `node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\validate-deck.mjs C:\Users\shich\.gemini\slide-deck\<项目名称>\index.html`
   - 报错即返工，仔细核对未定义的 Class 并修改 HTML，直到输出 Exit 0。
6. **Delivery (交付)**：输出本地文件路径，并提示用户：双击直接查看，按 `S` 键唤起原生双屏演讲者视图。如果需要 PDF，调用 `node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\export-pdf.mjs <html-path> <pdf-path>` 生成静态文件。

## Resources
- `design-vault/magazine/*`：杂志风核心资产（强调空间感、衬线体、流体）。
- `design-vault/swiss/*`：瑞士风核心资产（强调 12 列网格、高反差、无衬线大字重）。
- `design-vault/shared/*`：全局通用的图像封装规范与 Checklist。
- `scripts/validate-deck.mjs`：强制 AST 级别的类名白名单验证器。
- `scripts/export-pdf.mjs`：本地无头浏览器 PDF 导出器（自带排版重构）。

## Failure Modes
*   **Validation Failed (`validate-deck.mjs` 报错)**：说明你违背了 Design Vault 的硬性约束（如使用了未定义的 class）。仔细对比报错信息，不要尝试改动验证器，而是修改你生成的 HTML。
*   **图片破版溢出**：检查是否遗漏了固定比例图片槽位（如 `.frame-img.r-16x9`）或未使用封装框。
*   **演讲者模式失效**：检查是否误删了 `template.html` 结尾处原生的 MessageBus / 键盘监听脚本块。

## Output Contract
*   **Format**: 单一、独立的 HTML 文件 (无外挂 CSS，除了必要的动效引擎 CDN 外无依赖)。
*   **Responsiveness**: 幻灯片容器强制遵循 16:9 纵横比，由底层 CSS 处理屏幕自适应缩放 (`transform`)。
*   **Dual-Screen Sync**: 必须原生支持基于 `window.opener` & `window.postMessage` 的双屏翻页与逐字稿同步功能。
*   **Print-Ready**: 必须自带 `@media print` 媒体查询，在 PDF 导出时能够解构 Slider 为垂直文档流。

## Telemetry
执行状态挂载至本地 `MEMORY/task_state.json`，并通过 CLI 返回 Exit Codes 进行上报。
