# Intelligence Hub V4.0 (战略情报作战中枢)

## Vision
构建具备"战略嗅觉"的多源情报引擎。通过解耦采集（Sensor）、精炼（Refinement）与推演（Deduction），实现对全球泛技术趋势与垂直医疗 IT 信号的高密度、自动化捕获与"So What?"级精炼。V4.0 统一 Python 工具链，引入 AI 精炼脚本与频率权重校准。

## Index
- `SKILL.md`: 核心 SOP V4.0，含五阶段情报循环完整工作流。
- `scripts/calibrate_focus.py`: 基于 `memory.md` 词频分析动态校准情报关键词权重。
- `scripts/fetch_news.py`: 支持增量抓取、指数退避重试的多源并发采集引擎。
- `scripts/refine.py`: 评分排序 + 结构化提示词生成，桥接采集与简报锻造。
- `scripts/forge.py`: 整合 AI 精炼结果，按模板渲染最终战略简报。
- `scripts/update_index.py`: 同时维护 Markdown 总目与 JSON 检索索引。
- `references/quality_standard.md`: IQS 情报质量准则（L1-L4 分级）。
- `references/karpathy_feeds.json`: 98 个全球深度技术与医疗订阅源。
- `references/strategic_focus.json`: 动态战略关键词配置（含医疗垂直词库）。
- `references/briefing_template.md`: 咨询级简报 Markdown 模板。
- `requirements.txt`: Python 依赖清单。
