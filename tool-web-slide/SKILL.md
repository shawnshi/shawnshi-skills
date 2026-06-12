---
name: tool-web-slide
version: 8.5.0
description: 工业级、基于 Design Vault 的单网页 PPT 生成器。支持"电子杂志风" (Magazine) 和 "瑞士国际主义风" (Swiss) 两种高级视觉排版系统。内置原生双屏演讲者视图与 PDF 导出管线。
triggers: ["PPT", "幻灯片", "网页演示", "电子杂志风", "瑞士风", "发布会"]
---

<strategy-gene>
Keywords: 网页 PPT, 电子杂志, 瑞士风, 演讲者视图, Design Vault
Summary: 通过强类型校验与高级排版认知模型，生成高品质单文件 HTML PPT。
Strategy:
1. 需求澄清：执行 7 问清单对齐，建立叙事弧 (Hook->Context->Core->Shift->Takeaway)。
2. 知识装配：调用 `scripts/assemble-context.mjs` 获取当前流派的版式组件。
3. 物理克隆：使用 `run_command` 的 `Copy-Item` 毫秒级克隆 `template.html` 至 `MEMORY/slide-deck`。
4. 锚点注入：使用 `replace_file_content` 精准替换 `<!-- SLIDES_HERE -->` 锚点，禁止大模型全量读写 108KB 文件。
5. 质量门检：必须通过 `scripts/validate-deck.mjs` 物理检查。
</strategy-gene>

## 这个 Skill 做什么

生成一份**高工业标准、强一致性**的单文件 HTML 演示文稿。
本智能体不仅是排版工，更是 **Art Director (艺术总监)**。支持两套完全隔离的美学风格：
*   **风格 A · 电子杂志风 (Magazine)**：WebGL 流体背景、衬线大标题、图片网格、人文感。
*   **风格 B · 瑞士国际主义 (Swiss)**：极致字号对比、绝对无衬线、12列严格网格、高反差色块。

---

## Workflow (Art Director 模式)

### 1. Clarification (7问清单与叙事弧设计) [Mode: PLANNING]
如果用户只给了一个模糊想法，**动手前先用普通对话对齐以下核心要素**：
1. 选风格 A (杂志风) 还是 B (瑞士风)？
2. 受众是谁？分享场景？
3. 时长与页数规划？
4. 有无原始语料/数据？
5. 图片/截图如何处理？
6. 主题色选哪套？(执行时在 template 开头替换对应的 `:root` 变量)
7. 有无不可更改的硬约束？

**构建叙事弧 (The Narrative Arc)**：
不要平铺直叙，先写一份骨架草稿：
- `钩子(Hook)`: 抛反差 / 扔数据 (1页)
- `定调(Context)`: 为什么讲这个 (1-2页)
- `主体(Core)`: 核心论点结构展开 (3-5页)
- `转折(Shift)`: 打破预期 / 提出新视角 (1页)
- `收束(Takeaway)`: 金句或行动号召 (1-2页)

### 2. Context Assembly (上下文装配) [Mode: EXECUTION]
使用 `run_command` 运行知识装配器，获取指定风格的 CSS 类名词典与布局版式：
`node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\assemble-context.mjs <A|B>`
*(仔细阅读返回的终端日志，里面包含你可用的所有 Grid 骨架和卡片类名)*

### 3. Template Cloning (毫秒级物理克隆)
`template.html` 高达 108KB，**绝对禁止使用 `view_file` 读取**，会导致 Token 熔断！
直接使用 `run_command` 将其克隆至防爆沙盒：
```powershell
New-Item -ItemType Directory -Force -Path "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name"; Copy-Item -Path "C:\Users\shich\.gemini\config\skills\tool-web-slide\design-vault\<style>\template.html" -Destination "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html" -Force
```

### 4. Precision Injection (排版与注入)
使用 `replace_file_content` 工具，瞄准 `C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html` 中的 `<!-- SLIDES_HERE -->` 锚点，将你写的 `<section class="slide">` 代码段注入进去。

**排版铁律 (Design Vault Hard Rules)**：
1. **类名预检**：所有用到的 class 必须在刚才 `assemble-context` 返回的日志里有定义！禁止凭空发明诸如 `.my-card`, `.text-bold` 等类名。
2. **主题节奏 (Theme Rhythm)**：连续 3 页同主题会产生视觉疲劳。必须交替使用 `light` / `dark` / `hero light` / `hero dark`。
3. **字重阶梯 (Swiss Style 核心)**：越大越细，越小越粗。大标题用 ExtraLight (200)，小字正文用 Medium (500)。
4. **品牌契约**：如果是医疗数字化议题，优先读取系统 `pai/DESIGN.md`，将核心色强行内联覆盖到 `:root` 变量中。
5. **图片命名法**：所有插图放在同级 `images/` 目录下，命名采用 `{页号}-{语义}.ext`，如 `01-cover.jpg`。

### 5. Quality Gate (物理门检)
强制使用 `run_command` 运行 AST 级校验器：
`node C:\Users\shich\.gemini\config\skills\tool-web-slide\scripts\validate-deck.mjs C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html`
报错即返工，直到输出 Exit 0。

### 6. Delivery (交付与无头导出)
输出路径提示用户，并告知按 `S` 键唤起原生双屏演讲者视图。
如需导出 PDF，先安装依赖再执行无头渲染：
```powershell
cd C:\Users\shich\.gemini\config\skills\tool-web-slide; npm install; node scripts\export-pdf.mjs "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\index.html" "C:\Users\shich\.gemini\MEMORY\slide-deck\project_name\output.pdf"
```
