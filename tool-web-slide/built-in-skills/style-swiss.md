# Swiss Style（瑞士国际风）

适用于战略汇报、产品发布、数据叙事和极简高对比演示。机器可读契约以 `references/components.json` 和 `references/layouts.json` 为准。

## 启用方式

1. 加载 `assets/core.css`。
2. 在 `<body>` 设置 `data-theme="swiss"`，不得通过 `.grid-12`、`.card-ink` 或正文内容推断主题。
3. 每页必须设置一个合法 `data-layout`，并在 `.canvas-card` 上使用对应的 `layout-*` 类。

```html
<body class="canvas-mode" data-theme="swiss" data-aspect="16:9">
```

## 视觉约束

- 黑、白、灰加一个强调色；强调色默认 IKB `#002FA7`。
- 标题用 `var(--sans)` 的 200/300 字重，数字用 `var(--mono)` 或表格数字特性。
- 严格沿网格对齐，使用直角、发丝线和明确留白，不叠加装饰性圆角与阴影。
- `.canvas-card` 已含安全边距，不给其直接子容器重复添加整页边距。
- `t-meta`、`t-cat` 必须位于主标题上方。

## 已实现组件

| 组件族 | 可用类 |
|---|---|
| 标题与正文 | `.h-hero`、`.h-hero-zh`、`.h-xl`、`.h-xl-zh`、`.h-md`、`.lead`、`.t-cat`、`.t-meta`、`.t-body` |
| 网格 | `.grid-12`、`.span-2` 至 `.span-12`、`.grid-2-7-5`、`.grid-2-6-6`、`.grid-3`、`.grid-4`、`.grid-6` |
| KPI | `.kpi-hero`、`.kpi-thin`、`.kpi-row-4`、`.stat-card` |
| 时间线 | `.timeline-v` + `.tl-node`；`.timeline-h` + `.tl-row` + `.th-node` |
| 卡片与架构 | `.sub-grid-3-2`、`.sub-card`、`.stack-row`、`.stack-block`、`.bar-towers`、`.bar-tower` |
| 图表 | `.h-bar-chart`、`.v-bar-chart`、`.bar-chart` |
| 图文 | `.frame-img`、`.swiss-img-split`、`.swiss-img-grid`、`.swiss-img-caption` |
| 分屏 | `.split-half`、`.half`、`.b-accent`、`.b-grey`、`.b-ink` |
| 填充 | `.card-fill`、`.card-ink`、`.card-accent` |
| 修饰 | `.dot-mat`、`.ring-mat`、`.cross-mat`、`.hatch`、`mod-*` |

不要再使用未实现的 `cell-6`、`grid-2-9`、`matrix-fill`、`four-cards`、`kpi-tower-row` 或 P1/S01 布局编号。

## 推荐布局

通用布局 `hero`、`split`、`tri-grid`、`focus`、`kpi-scene`、`z-pattern`、`gallery`、`architecture`、`pathway`、`comparison` 均可使用。旧 `#Primary-*` 与 P1/P19 标识已废止。

## 最小示例

```html
<section class="slide" data-slide-id="core-claim" data-layout="hero" data-evidence="none" data-animate="statement-rise">
  <div class="canvas-card layout-hero">
    <div class="chrome-min">
      <div class="l">SECTION · TOPIC</div>
      <div class="r">04 / 12</div>
    </div>
    <p class="t-cat">CORE CLAIM</p>
    <h1 class="h-hero-zh">一次建设，持续运行。</h1>
    <p class="lead">用统一契约约束页面、主题和交付。</p>
  </div>
</section>
```
