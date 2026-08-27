# Layout Patterns（统一版式契约）

`references/layouts.json` 是布局 ID 的唯一机器可读真源；本文件只解释用法。旧的 `#Primary-*`、P1/P19、S01–S22 编号全部废止。

## 强制结构

每页必须声明一个布局 ID，并在 `.canvas-card` 上使用 JSON 中对应的 `componentClass`：

```html
<section class="slide" data-slide-id="operating-model" data-layout="split" data-evidence="none">
  <div class="canvas-card layout-split">…</div>
</section>
```

主题只允许 `magazine`、`swiss`、`winning-clinical`，在 `<body data-theme="…">` 明确设置。布局与主题是两个独立字段，不允许根据页面内容推断。

## 通用布局

| ID | CSS 类 | 结构与适用场景 |
|---|---|---|
| `hero` | `.layout-hero` | 封面、章节页或单一主张；内容靠底或按需绝对定位 |
| `split` | `.layout-split` | 1:1左右分屏；图片与正文各占一列 |
| `tri-grid` | `.layout-tri-grid` | 三个同层级观点、案例或指标 |
| `focus` | `.layout-focus` | 1:2:1黄金分割；中心承载主要图表或产品截图 |
| `kpi-scene` | `.layout-kpi-scene` | 满版场景图加3–4个KPI；图片用 `.scene-media`，指标组用 `.scene-kpis` |
| `z-pattern` | `.layout-z-pattern` | 两列多行、图文交替的Z形阅读路径 |
| `gallery` | `.layout-gallery` | 四列同构图片、团队、产品或案例阵列 |
| `architecture` | `.layout-architecture` | 纵向分层架构；Winning主题配合 `.c-architecture-stack` |
| `pathway` | `.layout-pathway` | 横向流程；Winning主题配合 `.c-clinical-pathway` |
| `comparison` | `.layout-comparison` | 不对称前后对比、问题与方案、投入与收益 |

## 医疗专用布局

以下布局仅用于 `winning-clinical`：

| ID | CSS 类 | 推荐语义组件 |
|---|---|---|
| `cdss-matrix` | `.layout-cdss-matrix` | `.cdss-workflow-matrix` |
| `emr-radar` | `.layout-emr-radar` | `.emr-level5-radar` |
| `data-lake-funnel` | `.layout-data-lake-funnel` | `.data-lake-funnel` |
| `policy-grid` | `.layout-policy-grid` | `.policy-compliance-grid` |
| `multi-campus` | `.layout-multi-campus` | `.multi-campus-topology` |
| `tri-terminal` | `.layout-tri-terminal` | `.tri-terminal-view` |
| `rag-traceability` | `.layout-rag-traceability` | `.rag-traceability-flow` |
| `drg-matrix` | `.layout-drg-matrix` | `.drg-cost-matrix` |
| `hl7-bus` | `.layout-hl7-bus` | `.hl7-integration-bus` |
| `pdca-loop` | `.layout-pdca-loop` | `.pdca-quality-loop` |
| `patient-journey` | `.layout-patient-journey` | `.patient-journey-timeline` |

医疗专用类提供结构，不替代真实图表数据。雷达、矩阵和流程必须包含标签、刻度或节点，且标注数据来源、日期和口径。

## 修饰器

每页最多使用两个修饰器。修饰器 ID 写入 `data-modifiers`，多个值以空格分隔，同时在目标元素使用对应类：

| ID | CSS 类 | 用途 |
|---|---|---|
| `float-card` | `.mod-float-card` | 大图上的半透明注解卡 |
| `huge-quote` | `.mod-huge-quote` | 引号或数字底纹 |
| `data-badge` | `.mod-data-badge` | 单一关键数字徽章 |
| `duotone` | `.mod-duotone` | 图片双色调处理 |
| `scrim` | `.mod-scrim` | 大图文字的渐变遮罩 |

```html
<section class="slide" data-slide-id="service-outcomes" data-layout="kpi-scene" data-evidence="required" data-modifiers="scrim float-card">
  <div class="canvas-card layout-kpi-scene mod-scrim">
    <img class="scene-media" src="assets/hospital.webp" alt="医院主楼">
    <aside class="mod-float-card">
      <h2>服务成效</h2>
      <p class="source-note" data-source="医院运营月报" data-source-date="2026-08">来源：医院运营月报，2026-08</p>
    </aside>
  </div>
</section>
```

## 选择规则

1. 一页只有一个主要结论和一个布局 ID。
2. 同层级信息才使用等分网格；有主次关系时使用 `focus`、`comparison` 或 `split`。
3. 图片不是装饰：必须与标题结论直接相关，并有替代文本与来源。
4. 不用行内 `display:grid` 重造已经存在的布局；需要新增版式时先更新 `layouts.json`、CSS 和本文档。
