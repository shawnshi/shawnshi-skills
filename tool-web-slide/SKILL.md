---
name: tool-web-slide
version: 8.4.0
description: 工业级、基于 Design Vault 的单网页 PPT 生成器。支持"电子杂志风" (Magazine) 和 "瑞士国际主义风" (Swiss) 两种高级视觉排版系统。内置原生双屏演讲者视图与 PDF 导出管线。
---

<strategy-gene>
Keywords: 网页 PPT, 电子杂志, 瑞士风, 演讲者视图, Design Vault
Summary: 通过 Design Vault 强力约束和强类型校验生成高质量 HTML PPT。
Strategy:
1. 需求澄清：确定主题、风格（A 或 B）、大纲。
2. 知识装配：强制调用 `scripts/assemble-context.mjs` 获取排版规范。
3. 物理克隆：使用 `run_command` 的 `Copy-Item` 将模板毫秒级复制至 `MEMORY` 沙盒，拒绝低效的 LLM read/write 全量读写。
4. 锚点注入：使用 `replace_file_content` 工具，精准狙击 `<!-- SLIDES_HERE -->` 注释锚点，仅替换幻灯片片段。
5. 质量门检：必须通过 `scripts/validate-deck.mjs` 物理检查。
AVOID: 绝对禁止大模型使用 view_file 去完整读取 108KB 的 HTML 模板！绝对禁止将生成物散落在非 MEMORY 目录！
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

### 1. Clarification (需求对齐)
强制与用户确认主题风格（A：电子杂志风；B：瑞士风）以及具体的图文内容与大纲。

### 2. Context Assembly (上下文装配)
使用 `run_command` 在终端运行知识装配器：
`node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\assemble-context.mjs <A|B>`
运行后，必须仔细阅读输出的上下文文本，其中包含所有允许使用的 CSS 类名和版式规则。

### 3. Template Cloning (毫秒级物理基座克隆)
因为 `template.html` 高达 108KB，**绝对禁止使用大模型去 view_file 读取它**！
直接使用 `run_command` 执行以下命令，将其克隆至防爆沙盒 `MEMORY` 目录下：
```powershell
New-Item -ItemType Directory -Force -Path "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name"; Copy-Item -Path "C:\Users\shich\.gemini\config\skills\tool-web-slide\design-vault\<style>\template.html" -Destination "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html" -Force
```
*(注意：将 `<style>` 替换为 `magazine` 或 `swiss`，`project_name` 替换为实际项目名)*

### 4. Injection (精准注入编码)
使用本地原子化修改工具 `replace_file_content`，精准锁定 `C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html` 中的 `<!-- SLIDES_HERE -->` 注释锚点。
将你构思好的 `<section class="slide">` 代码片段替换进去，**切勿复写整份文件**。
- 严禁臆造 CSS 类名，所有排版必须组合 Design Vault 提供的基础组件。
- **品牌契约覆盖 (Brand Identity)**：如果是医疗数字化议题，优先读取系统 `pai/DESIGN.md`，将核心色（如 `#005EB8`）强制内联覆盖到 `:root` 中。

### 5. Quality Gate (物理门检)
强制使用 `run_command` 运行校验器：
`node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\validate-deck.mjs C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html`
报错即返工，仔细核对未定义的 Class 并修改 HTML，直到输出 Exit 0。

### 6. Delivery (交付与导出)
输出本地文件路径 `MEMORY\slide-deck\project_name\index.html`，提示用户按 `S` 键唤起双屏模式。
如果需要导出 PDF，必须先安装环境依赖并执行无头渲染：
```powershell
cd C:\Users\shich\.gemini\config\skills\tool-web-slide; npm install; node scripts\export-pdf.mjs "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html" "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\output.pdf"
```

## Failure Modes
*   **Token 熔断崩溃**：你违背了纪律去 `view_file` 整个 HTML 模板，导致上下文爆满。坚决使用 `Copy-Item` 和 `replace_file_content`。
*   **Validation Failed (`validate-deck.mjs` 报错)**：使用了未定义的 class。仔细对比报错信息并局部修改 HTML。
*   **演讲者模式失效**：在 `replace_file_content` 注入幻灯片时，误删了 `template.html` 结尾处原生的 MessageBus / 键盘监听脚本块。仅替换 `<!-- SLIDES_HERE -->` 区域。
*   **PDF 导出失败**：未在执行前运行 `npm install` 安装 puppeteer 依赖。
