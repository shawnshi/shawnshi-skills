# Layout library

在 `[Layout]` 中使用下列 ID。确需自定义时使用 `custom:<slug>`，例如 `custom:evidence-ledger`；`slug` 只使用小写英文字母、数字和连字符。布局是信息关系，不是装饰模板。

## Core layouts

| ID | 结构 | 适用页面 |
|---|---|---|
| `title-hero` | 大标题、短副标题、单一视觉焦点 | Cover、Section |
| `executive-summary` | 结论、证据、影响、行动四区 | Executive-Summary |
| `key-stat` | 关键数字、基准、解释和来源 | Data、Content |
| `two-columns` | 两个等权内容区 | Content、Comparison |
| `binary-comparison` | 统一维度的 A/B 对比 | Comparison |
| `comparison-matrix` | 多选项×多维度矩阵 | Comparison、Decision |
| `chart-plus-insight` | 主图表与结论注释区 | Data |
| `dashboard` | 少量 KPI、趋势和状态 | Data、Status |
| `linear-roadmap` | 阶段、里程碑、结果和责任 | Roadmap |
| `swimlane` | 角色或系统分泳道的流程 | Content、Roadmap |
| `layered-architecture` | 分层能力、系统或治理结构 | Content |
| `hub-spoke` | 中心能力与外围协同 | Content |
| `decision-card` | 请求、理由、影响、时间和责任人 | Decision |
| `risk-matrix` | 概率×影响与缓解动作 | Risk |
| `risk-register` | 风险、等级、触发、缓解和责任 | Risk |
| `quote-callout` | 引文、来源和解释 | Content、Closing |
| `reference-list` | 编号来源、定位信息和范围 | References |
| `appendix-detail` | 高密度表格、定义或方法 | Appendix |

## Selection rules

- 比较页必须使用统一维度，不能把两个不对称清单并排。
- Roadmap 展示业务结果和依赖，不只列系统名称。
- Dashboard 控制指标数量；无法行动的指标不应进入主体。
- 架构图按真实责任、数据或依赖关系分层，不把产品模块堆成“能力架构”。
- 风险页显示缓解动作和责任边界，不能只展示红黄绿状态。
- 引用页保留 locator；仅列机构名称不算可复核来源。
- 自定义布局仍须在 `[Visual Description]` 中完整定义阅读顺序、区块关系和必要标注；`custom:` 不是跳过设计说明的通行证。

## Layout description

`[Visual Description]` 至少说明：

1. 阅读顺序和主焦点。
2. 区块、网格或图形关系。
3. 哪些文字、数字和证据必须可见。
4. 图表标注、单位、图例或风险颜色规则。
5. 必要资产及其授权/脱敏状态。

不要写“做得高级一些”“参考上一页”等依赖隐式上下文的描述。
