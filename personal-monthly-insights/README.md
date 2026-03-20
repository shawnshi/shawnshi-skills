# 本月交互剖析仪 (monthly-personal-insights v6.0)

周期性战略元分析引擎 — 解码协作中的摩擦基因、追踪情感韧性并自动同步洞察至记忆系统。

## 核心能力
- **架构解耦高内聚**：核心分析引擎 (`core/engine.py`) 与可视化表现层 (`assets/template.html`) 物理隔离
- **多源数据融合**：聚合 Gemini CLI 日志 + Antigravity 会话日志 + 文件系统活动快照
- **八维因子分析**：Goal / Satisfaction / Friction / Intent / CogFric / Archetype / EmotionalTone / TopicTags
- **六维雷达综合画像**：完成率 / 满意度 / 低摩擦 / 架构深度 / 情感韧性 / 意图精度
- **交互式暗色仪表板**：Dark Mode + 响应式布局 + Chart.js 可视化
- **自动记忆闭环**：审计洞察自动同步至 `memory.md`，含防重复机制
- **双格式导出**：HTML 交互报告 + Markdown 纯文本版本
- **灵活时间窗口**：支持 `--period 7d|30d|90d|year`
- **工程韧性**：规则引擎 Fallback + 批量缓存 + 超时保护

## 使用
```bash
python analyze_insights_v4.py --period 30d
```

## 使用场景
定期盘点 AI 协作状态、复盘交互模式、追踪情感倦怠风险、或寻求流程精益优化时激活。
