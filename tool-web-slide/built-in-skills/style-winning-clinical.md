# Winning Clinical Style（极简医疗风）

仅在任务明确涉及卫宁健康／WiNEX，或用户明确指定该品牌／选用本主题时启用。医院、医疗或临床题材本身不触发品牌套用；其他任务遵循自身设计体系或用户模板，不暗示公司背书。机器可读契约以 `references/components.json` 和 `references/layouts.json` 为准。

## 启用方式

1. 按顺序加载 `assets/core.css`、`assets/winning.css`。
2. 在 `<body>` 设置 `data-theme="winning-clinical"`，不得使用内容关键词或 CSS 类猜测主题。
3. 每页 `<section class="slide">` 必须设置一个合法 `data-layout`；其 `.canvas-card` 使用对应 `layout-*` 类。

```html
<body class="canvas-mode" data-theme="winning-clinical" data-aspect="16:9">
```

## 品牌与可读性

- 主蓝：`--primary-600: #005EB8`，蓝底文字固定 `--primary-on: #FFFFFF`。
- AI青：`--secondary: #00B5E2` 仅用于填充；白底小字使用对比度更高的 `--secondary-700: #007A99`。
- 警示金：`--warning: #F2A900`，金底文字固定 `--warning-on: #1A232C`，禁止白字。
- 正文：`--gray-900: #1A232C`；辅助文字最低使用 `--gray-600: #536577`，不以低透明度浅灰承载关键信息。
- 章节页使用主蓝背景与白色文字；深色页面使用独立的反色文字与表面令牌。
- 普通改造前后对比使用中性色，红色仅用于真实不可逆失败或 L4 拦截，并须提供非颜色说明。
- 每页最多三种装饰强调色；数据系列按实际类别提供标签或形状。不用3D、卡通、液态形状和无业务含义的装饰。

## 通用决策组件

| 组件 | 类 |
|---|---|
| 页眉与结论标题 | `.c-header`、`.c-tracker`、`.c-action-title` |
| MECE支柱 | `.c-pillars`、`.c-pillar`、`.highlight`、`.c-pillar-title`、`.c-pillar-body` |
| 核心主张 | `.c-statement`、`.c-statement-text`、`.c-statement-sub` |
| KPI | `.c-kpi-group`、`.c-kpi`、`.c-kpi-value`、`.c-kpi-label` |
| 路线图 | `.c-timeline`、`.c-timeline-step`、`.c-timeline-marker`、`.c-timeline-year`、`.c-timeline-title`、`.c-timeline-desc` |
| 来源 | `.c-footnote` |

## 医疗数字化组件

| 场景 | 主类及必要子类 | 对应布局 ID |
|---|---|---|
| 企业架构 | `.c-architecture-stack`、`.c-layer`、`.core`、`.c-layer-title`、`.c-layer-items`、`.c-module-box` | `architecture` |
| 临床路径 | `.c-clinical-pathway`、`.c-pathway-node`、`.c-pathway-arrow` | `pathway` |
| 改造前后对比 | `.c-comparison-matrix`、`.c-matrix-col-bad`、`.c-matrix-col-good` | `comparison` |
| CDSS干预矩阵 | `.cdss-workflow-matrix` | `cdss-matrix` |
| 电子病历能力雷达 | `.emr-level5-radar` | `emr-radar` |
| 数据湖提纯 | `.data-lake-funnel`、`.data-source`、`.data-cleansing`、`.data-asset` | `data-lake-funnel` |
| 政策指标映射 | `.policy-compliance-grid` | `policy-grid` |
| 一院多区 | `.multi-campus-topology`、`.hub-center`、`.edge-node` | `multi-campus` |
| 医护患三端 | `.tri-terminal-view`、`.role-doctor`、`.role-nurse`、`.role-patient` | `tri-terminal` |
| RAG证据链 | `.rag-traceability-flow`、`.rag-query`、`.rag-boundary`、`.rag-output` | `rag-traceability` |
| DRG/DIP价值成本 | `.drg-cost-matrix` | `drg-matrix` |
| HL7/ESB总线 | `.hl7-integration-bus`、`.hl7-bus-nodes`、`.hl7-bus-node`、`.hl7-bus-line` | `hl7-bus` |
| 单病种PDCA | `.pdca-quality-loop`、`.pdca-step` | `pdca-loop` |
| 全生命周期旅程 | `.patient-journey-timeline`、`.journey-stage` | `patient-journey` |

上述组件提供布局和视觉框架。雷达默认只显示坐标示意及“非评分”标识，不生成固定评分多边形；真实能力评分必须由已提供的数据生成 SVG，并注明维度、刻度、图例、来源和日期。不得把示意框架、固定形状或颜色面积作为真实测量结果。矩阵和拓扑可承载静态 HTML/SVG；涉及精确数据时同样需要数据与证据。

## 兼容组件

既有页面可继续使用 `.s-arch*`、`.s-era*`、`.stacked-ledger`、`.ledger-*` 和 `.c-matrix*`。新页面优先使用上表的语义组件。共享的 `slide`、`canvas-card`、`layout-*`、`t-meta`、`frame-img` 等由 `core.css` 提供。

## 最小示例

```html
<section class="slide" data-slide-id="platform-architecture" data-layout="architecture" data-evidence="required" data-animate="hero">
  <div class="canvas-card layout-architecture">
    <header class="c-header" data-anim="hero-text">
      <div class="c-tracker">总体架构 <span class="sep">/</span> <span class="active">01</span></div>
      <h2 class="c-action-title">把分散系统收敛为<strong>可治理的平台中枢</strong></h2>
    </header>
    <div class="c-architecture-stack">
      <section class="c-layer core">
        <h3 class="c-layer-title">临床智能中枢</h3>
        <div class="c-layer-items"><span class="c-module-box">CDR</span><span class="c-module-box">AI Gateway</span></div>
      </section>
      <section class="c-layer">
        <h3 class="c-layer-title">业务应用</h3>
        <div class="c-layer-items"><span class="c-module-box">EMR</span><span class="c-module-box">PACS</span></div>
      </section>
    </div>
    <p class="c-footnote source-note" data-source="项目范围说明" data-source-date="2026-08"><strong>来源：</strong>项目范围说明，2026-08</p>
  </div>
</section>
```
