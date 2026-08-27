# Magazine Style（电子杂志风）

适用于“电子杂志、画册、社论、人物或案例长文”类演示。机器可读契约以 `references/components.json` 和 `references/layouts.json` 为准。

## 启用方式

1. 按顺序加载 `assets/core.css`、`assets/magazine.css`。
2. 在 `<body>` 设置 `data-theme="magazine"`，不得用内容或类名猜测主题。
3. 每页 `<section class="slide">` 必须设置一个合法 `data-layout`；其 `.canvas-card` 同时使用对应的 `layout-*` 类。

```html
<body class="canvas-mode" data-theme="magazine" data-aspect="16:9">
```

## 视觉约束

- 大标题用 `var(--serif)`，正文可用衬线，元数据和图注用 `var(--sans)`。
- 暖纸色、炭黑和一个酒红强调色；每页最多两个修饰器。
- 图片允许满版裁切，但必须提供来源或说明；数据页必须标注口径和日期。
- 不依赖在线字体即可正常显示，禁止把远程字体作为可读性的必要条件。

## 已实现组件

| 类 | 用途 |
|---|---|
| `.mag-canvas` | 杂志画布，必须与 `.canvas-card` 同时使用 |
| `.mag-header` | 标题与期号的编辑式页眉 |
| `.mag-title`、`.italic` | 大型衬线标题及斜体强调 |
| `.mag-lead` | 导语 |
| `.mag-article` | 默认双栏正文；`data-columns="3"` 为三栏 |
| `.mag-drop-cap` | 首字下沉 |
| `.mag-pull-quote` | 跨段引语 |
| `.mag-figure`、`.mag-caption` | 图片及图注 |
| `.mag-stat` | 大数字；单位放入 `<small>` |
| `.mag-list` | 破折号项目列表 |
| `.mag-folio`、`.mag-byline` | 页码、期号和作者信息 |
| `.mag-grid`、`.mag-divider` | 12列编辑网格及分隔线 |

可同时使用 `core.css` 中 `slide`、`canvas-card`、`layout-*`、`t-meta`、`frame-img`、`mod-*` 等共享类。不要使用未列入 `components.json` 的自造结构类。

## 推荐布局

优先使用 `hero`、`split`、`tri-grid`、`focus`、`kpi-scene`、`z-pattern`、`gallery`、`comparison`。布局 ID 不使用 P1、S01 或 `#Primary-*` 等旧编号。

## 最小示例

```html
<section class="slide" data-slide-id="editorial-future-care" data-layout="tri-grid" data-evidence="required" data-animate="fade">
  <div class="canvas-card mag-canvas layout-tri-grid">
    <header class="mag-header">
      <h1 class="mag-title">The <span class="italic">Future</span> of Care</h1>
      <div class="mag-folio"><span>ISSUE 04</span><span>01 / 12</span></div>
    </header>
    <article class="mag-article">
      <p><span class="mag-drop-cap">A</span>s care becomes predictive, evidence and workflow must stay connected.</p>
      <blockquote class="mag-pull-quote">Data is useful only when it changes a decision.</blockquote>
    </article>
    <figure class="mag-figure">
      <img src="assets/care-team.webp" alt="临床团队讨论">
      <figcaption class="mag-caption source-note" data-source="机构公开资料" data-source-date="2026-08">来源：机构公开资料，2026-08</figcaption>
    </figure>
  </div>
</section>
```
