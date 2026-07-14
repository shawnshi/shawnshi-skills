---
name: tool-web-slide
description: 将演示文稿内容构建为可在浏览器运行的单页 HTML 幻灯片并进行视觉验证。当用户要求网页演示、单文件 PPT、电子杂志式幻灯片或需要可交互的医疗与商业汇报页面时使用。
---

# Web Slide Builder

## Scope

本技能生成 HTML 演示。用户需要原生 `.pptx` 时使用演示文稿能力；用户只需要故事线时使用 `tool-slide-architect`。

## Procedure

1. 确认受众、目标、页数、画布比例、品牌约束、交互需求和输出目录。内容和视觉方向足够明确时直接构建。
2. 选择样式并按需读取：
   - `built-in-skills/style-magazine.md`
   - `built-in-skills/style-swiss.md`
   - `built-in-skills/style-winning-clinical.md`
   - `references/layout-patterns.md`
3. 先定义颜色、字体、间距、页面模板和内容密度，再实现页面。复用 `starter-components/` 与 `assets/`，不要复制第三方依赖目录。
4. 将每页限制为一个主要结论，确保标题、证据、图表和讲稿层级清楚。涉及医疗或商业数据时标注来源和日期。
5. 生成 `index.html` 及必要资产。只有页面组可以独立实现且并行能力可用时，才并行构建；最终设计变量和导航由主线统一。
6. 运行：
   - `scripts/html_quality_checker.mjs`
   - `scripts/validate-deck.mjs`
7. 使用可用浏览器渲染代表性页面，检查文字溢出、遮挡、对比度、导航、动画和不同窗口尺寸。发现问题后修改并复验。
8. 用户要求 PDF 时，使用 `scripts/export-pdf.mjs` 导出并检查页数和裁切。
9. 将最终文件写入用户指定目录或当前工作区，提供可点击的本地链接。

## Dependencies

需要已安装的 Node 运行时和锁文件声明的依赖。不得提交 `node_modules`，也不得在未获授权时安装依赖。

## Boundaries

- 不把 HTML 演示冒充原生 PowerPoint。
- 不强制在设计稿阶段停下审批；只有缺失选择会实质改变结果时才询问。
- 不默认写入知识库或保存用户品牌偏好。
- 不从未知来源执行脚本，不把私有数据上传到外部服务。

## Output

交付 `index.html`、必要资产、质量检查结果，以及按需生成的 PDF。
