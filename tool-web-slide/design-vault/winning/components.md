# 咨询级专属积木组件 (Consulting Components)

这些是 Style C (Winning Clinical) 独有的高级结构组件。当内容涉及“技术架构”、“阶段演进”或“核心KPI群”时，不要使用基础的段落或列表，必须拼装以下专属组件。

> ⚠️ 注意：这些组件可以直接放在 `.slide` 容器内（如 `S01` 或 `S19` 的内容区），会自动适配阅读/演示双态模式。

## 1. 商业/技术架构分层 (Architecture Layers)

用于表达自下而上的技术栈或业务分层（例如：基础设施层 -> 数据层 -> 智能层 -> 应用层）。
- `.lyr-app`: 应用层/顶层（深蓝）
- `.lyr-agt`: 智能层/中间件（亮青）
- `.lyr-dat`: 数据层（灰蓝）
- `.lyr-sem`: 基础设施层（墨黑）

**代码范例**：
```html
<div class="s-arch">
  <!-- 第一层：应用层 -->
  <div class="s-arch-layer lyr-app">
    <div class="s-arch-lbl">Application<br/>场景应用层</div>
    <div class="s-arch-body">
      <span class="s-arch-chip">病历生成</span>
      <span class="s-arch-chip">临床辅诊</span>
      <span class="s-arch-chip">质控管理</span>
    </div>
  </div>
  <!-- 箭头连接 -->
  <div class="s-arch-arrow">↓</div>
  <!-- 第二层：智能层 -->
  <div class="s-arch-layer lyr-agt">
    <div class="s-arch-lbl">Intelligence<br/>Agent 引擎</div>
    <div class="s-arch-body">
      <span class="s-arch-chip">意图识别引擎</span>
      <span class="s-arch-chip">多智能体路由</span>
    </div>
  </div>
</div>
```

## 2. 三阶段演进 / 路线图 (Era Roadmap)

用于表达时间规划、战略三个阶段（如 Enable -> Embed -> Evolve）。
必须配合外层 `.s-era-grid` 使用。使用 `.highlight` 类可高亮当前阶段。

**代码范例**：
```html
<div class="s-era-grid">
  <!-- 阶段 1 -->
  <div class="s-era">
    <div class="s-era-period">Phase 1 · 2025-2026</div>
    <div class="s-era-zh">使能阶段 Enable</div>
    <div class="s-era-en">Digital Foundation</div>
    <span class="s-era-role">数据底座</span>
    <p class="body-sm" style="margin-top:12px;color:var(--text-secondary)">完成数据治理体系建设，打通各业务系统孤岛，建立统一的高质量数据集。</p>
  </div>
  <!-- 阶段 2 (当前高亮) -->
  <div class="s-era highlight">
    <div class="s-era-period">Phase 2 · 2026-2027</div>
    <div class="s-era-zh">嵌入阶段 Embed</div>
    <div class="s-era-en">AI Integration</div>
    <span class="s-era-role">当前窗口</span>
    <p class="body-sm" style="margin-top:12px;color:var(--text-secondary)">Agent 规模化部署，深度融入临床工作流，实现三类参与者协同。</p>
  </div>
  <!-- 阶段 3 -->
  <div class="s-era">
    <div class="s-era-period">Phase 3 · 2027+</div>
    <div class="s-era-zh">演进阶段 Evolve</div>
    <div class="s-era-en">Ecosystem Shift</div>
    <span class="s-era-role">生态赋能</span>
    <p class="body-sm" style="margin-top:12px;color:var(--text-secondary)">跨机构无缝价值传递，成为区域医疗网络的核心枢纽节点。</p>
  </div>
</div>
```

## 3. 统计指标账单 (Stacked Ledger)

用于展示多维度的量化成果（如降本增效指标）。这是从基础版式 P20 剥离出来的组件，可独立嵌入。

**代码范例**：
```html
<div class="stacked-ledger" style="margin-top:20px;border-top:1px solid var(--border-subtle)">
  <div class="ledger-row">
    <span class="ledger-num" style="font-size:min(8vw,10vh)">12<small>×</small></span>
    <span class="ledger-lbl">工作流效率提升倍数</span>
    <i data-lucide="trending-up"></i>
  </div>
  <div class="ledger-row">
    <span class="ledger-num" style="font-size:min(8vw,10vh);color:var(--accent)">100<small>%</small></span>
    <span class="ledger-lbl">全病程数据覆盖率</span>
    <i data-lucide="check-circle"></i>
  </div>
</div>
```


## 4. 顶尖咨询框架 (MBB Consulting Primitives)

用于承载标准的管理咨询方法论（如 MECE 分解、矩阵分析）。

### 4.1 强断言表头 (Action Header)
包含路径追踪（Tracker）和强断言标题（Action Title）。必须放在 `.canvas-card` 的顶部。

**代码范例**：
```html
<div class="c-header">
  <div class="c-tracker">
    <span>MARKET CONTEXT</span>
    <span class="sep">/</span>
    <span class="active">STRATEGY SHIFT</span>
  </div>
  <h2 class="c-action-title">
    Hospital IT spending is shifting from <strong>infrastructure to clinical AI</strong>, driving a 35% CAGR in agent-based solutions.
  </h2>
</div>
```

### 4.2 2x2 定位矩阵 (Positioning Matrix)
用于战略生态位分析、风险收益分析。外层需要 `c-matrix-wrapper` 留出坐标轴空间。

**代码范例**：
```html
<div class="c-matrix-wrapper">
  <div class="c-axis-y">Impact / Value</div>
  <div class="c-axis-x">Implementation Complexity</div>
  <div class="c-matrix">
    <div class="c-axis-arrow-y"></div>
    <div class="c-axis-arrow-x"></div>
    
    <!-- Q1 (Top Left) -->
    <div class="c-matrix-quad">
      <div class="c-matrix-lbl">Quick Wins</div>
      <div class="c-matrix-desc">High value, low barrier.</div>
    </div>
    <!-- Q2 (Top Right) - Sweet Spot -->
    <div class="c-matrix-quad sweet-spot">
      <div class="c-matrix-lbl">Strategic Bets</div>
      <div class="c-matrix-desc">Transformative ROI.</div>
      <div class="c-matrix-item" style="top:20%;right:30%">AI Copilot</div>
    </div>
    <!-- Q3 (Bottom Left) -->
    <div class="c-matrix-quad">
      <div class="c-matrix-lbl">Foundational</div>
      <div class="c-matrix-desc">Necessary but low diff.</div>
    </div>
    <!-- Q4 (Bottom Right) -->
    <div class="c-matrix-quad">
      <div class="c-matrix-lbl">Money Pits</div>
      <div class="c-matrix-desc">Avoid unless mandated.</div>
    </div>
  </div>
</div>
```

### 4.3 结构化支柱 (MECE Pillars)
用于对比分析、多项举措的并列展示（3-4 列）。

**代码范例**：
```html
<div class="c-pillars">
  <div class="c-pillar">
    <div class="c-pillar-title">01. Connect</div>
    <div class="c-pillar-body">Integrate siloed hospital data streams into a unified semantic lake.</div>
  </div>
  <div class="c-pillar highlight">
    <div class="c-pillar-title">02. Intelligence</div>
    <div class="c-pillar-body">Deploy specialized clinical agents to reduce physician cognitive load.</div>
  </div>
  <div class="c-pillar">
    <div class="c-pillar-title">03. Ecosystem</div>
    <div class="c-pillar-body">Expand capabilities to regional health networks and patient portals.</div>
  </div>
</div>
```

### 4.4 严谨数据注脚 (Footnote)
位于页面最底部，用于标明数据来源。

**代码范例**：
```html
<div class="c-footnote">
  <strong>Source:</strong> Gartner Hype Cycle for Healthcare Data (2024); McKinsey Global Institute.
</div>
```
