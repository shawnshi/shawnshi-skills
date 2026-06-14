---
name: tool-web-slide
version: 10.0.0
description: '工业级、基于 Design Vault 的单网页 PPT 生成器。支持"电子杂志风" (Magazine)、"瑞士风" (Swiss) 以及 "极简医疗风" (Winning Clinical) 三套高级视觉排版系统。内置原生双屏演讲者视图与 PDF 导出管线。'
triggers: ["PPT", "幻灯片", "网页演示", "电子杂志风", "瑞士风", "发布会", "卫宁模板", "医疗汇报"]
---

<strategy-gene>
Keywords: 网页 PPT, 电子杂志, 瑞士风, 演讲者视图, Design Vault, 物理装配, 医疗极简
Summary: 通过强类型校验与高级排版认知模型，生成高品质单文件 HTML PPT。V10.0 引入 Winning Health 原生医疗引擎。
Strategy:
1. 需求澄清：执行 7 问清单对齐，建立叙事弧 (Hook->Context->Core->Shift->Takeaway)。
2. 知识装配：调用 `scripts/assemble-context.mjs` 获取当前流派的版式组件。
3. 物理克隆与解耦：禁止使用 `replace_file_content` 直接操作 template。大模型必须将 PPT 片段写入独立的沙盒中间文件。
4. AST 级组装：使用内置的 `build_deck.py` 进行 DOM 级安全装配。
5. 质量门检：必须通过 `scripts/validate-deck.mjs` 物理检查。
</strategy-gene>

## 这个 Skill 做什么

生成一份**高工业标准、强一致性**的单文件 HTML 演示文稿。
本智能体不仅是排版工，更是 **Art Director (艺术总监)**。支持三套完全隔离的美学风格：
*   **风格 A · 电子杂志风 (Magazine)**：WebGL 流体背景、衬线大标题、图片网格、人文感。
*   **风格 B · 瑞士国际主义 (Swiss)**：极致字号对比、绝对无衬线、12列严格网格、高反差色块。
*   **风格 C · 极简医疗风 (Winning Clinical)**：专属 `DESIGN.md` 映射，原生 `#005EB8` 医疗蓝，禁用 3D/卡通，强网格护城河。

---

## Workflow (Art Director 模式)

### 1. Clarification (7问清单与叙事弧设计) [Mode: PLANNING]
如果用户只给了一个模糊想法，**动手前先用普通对话对齐以下核心要素**：
1. 选风格 A (杂志风)、B (瑞士风) 还是 C (极简医疗风)？
2. 受众是谁？分享场景？
3. 时长与页数规划？
4. 有无原始语料/数据？
5. 图片/截图如何处理？
6. 主题色选哪套？(执行时在 template 开头替换对应的 `:root` 变量)
7. 有无不可更改的硬约束？

**构建叙事弧 (The Narrative Arc)**：
不要平铺直叙，先写一份骨架草稿（可由 `tool-slide-architect` 承接）：
- `钩子(Hook)`: 抛反差 / 扔数据 (1页)
- `定调(Context)`: 为什么讲这个 (1-2页)
- `主体(Core)`: 核心论点结构展开 (3-5页)
- `转折(Shift)`: 打破预期 / 提出新视角 (1页)
- `收束(Takeaway)`: 金句或行动号召 (1-2页)

### 2. Context Assembly (上下文装配) [Mode: EXECUTION]
使用 `run_command` 运行知识装配器，获取指定风格的 CSS 类名词典与布局版式：
`$env:PYTHONIOENCODING="utf-8"; node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\assemble-context.mjs <A|B|C>`
*(仔细阅读返回的终端日志，里面包含你可用的所有 Grid 骨架和卡片类名)*

### 3. 解耦式物理沙盒装配 (V9.0 核心)
为了防止 108KB 模板触发 Token 熔断以及正则注入导致 DOM 结构被毁（如丢失 `<nav>`），**严禁直接使用 replace_file_content 读写目标 HTML**。

必须遵循“写中间层 -> 脚本装配”管线：

**第一步：写中间件片段 (Chunking Generation)**
使用原生的 `write_to_file` 工具，将你要生成的 HTML slide 节点（即纯粹的 `<section class="slide">...` 列表）写入当前会话的安全沙盒隔离区 `<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\slides_part1.html`，防止并发生成时的全局污染。
> ⚠️ **微批次防衰减 (Minibatch Enforcement)**：当幻灯片总数 > 10 页时，严禁在一个块中全量输出。必须分批次写入多个分件（如 `part1.html`, `part2.html`），以确保排版质量与指令遵循（如 Swiss 的 `data-layout` 属性）不被注意力衰减破坏。

**排版铁律 (Design Vault Hard Rules)**：
1. **类名预检**：所有用到的 class 必须在 `assemble-context` 中有定义！禁止凭空发明。
2. **主题节奏**：连续 3 页同主题会产生疲劳。交替使用 `light` / `dark` / `hero light` / `hero dark`。
3. **字重阶梯 (Swiss Style)**：大标题用 ExtraLight (200)，正文用 Medium (500)。
4. **全局强制卡片容器 (Canvas Card Mandatory)**：如果使用 Swiss 或 Winning 风格，所有 `<section class="slide">` 内部必须直接且仅嵌套一层 `<div class="canvas-card">` 以承载排版，严禁直接在 section 内堆砌内容（否则底色和边距将全部失效，文字丢失）。
5. **图片命名法**：同级 `images/` 目录下，采用 `{页号}-{语义}.ext`。

**第二步：引擎组装 (Compiler Assembling)**
大模型写完所有片段后，如果有多份，使用 `run_command` 合并片段，并触发装配器：
```powershell
New-Item -ItemType Directory -Force -Path "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name"
# 假设大模型已合并写入 slides_merged.html
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\build_deck.py" "C:\Users\shich\.gemini\config\skills\tool-web-slide\design-vault\<style>\template.html" "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\slides_merged.html" "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\index.html"
```
*此脚本会在物理层绝对安全地将片段注入 `<!-- SLIDES_HERE -->` 锚点，保护底层 JS 引擎不断链。*

### 4. Quality Gate (物理门检)
强制使用 `run_command` 运行 AST 级校验器：
`$env:PYTHONIOENCODING="utf-8"; node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\validate-deck.mjs "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\index.html"`
报错即返工，直到输出 Exit 0。

### 5. Delivery (交付与无头导出)
**交付链接契约**：生成完毕后，主代理必须通过聊天框向用户输出可点击的 Markdown 链接（例如：`[交互式网页 PPT (按 S 键开启演讲者视图)](file:///<appDataDir>/brain/<conversation-id>/scratch/slide-deck/project_name/index.html)`）。
如需导出 PDF，先执行无头渲染，然后同样交付 PDF 链接：
```powershell
cd C:\Users\shich\.gemini\config\skills\tool-web-slide; npm install; node scripts\export-pdf.mjs "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\index.html" "<appDataDir>\brain\<conversation-id>\scratch\slide-deck\project_name\output.pdf"
```
