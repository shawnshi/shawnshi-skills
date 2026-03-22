---
name: personal-intelligence-hub
version: 7.3.0
description: |
  战略情报作战中枢 (Native Agent Edition)。基于《龙虾教程》五层价值链，交付具备极致信噪比的智库资产。
  核心要求：必须读取 feeds.json 确定扫描范围，遵循 quality_standard.md 执行三段论审计，强制使用 briefing_template.md 输出报告。
  对抗性审计：L3/L4 级情报必须调用 logic-adversary 执行红队验证。
  物理去重：必须通过 pushed_history.json 拦截过去 7 天内已推送过的 Top 10 信号。
  Native tools integration: google_web_search, glob, write_file, read_file, ask_user.
benefits-from: [logic-adversary]
triggers: ["获取最新情报", "分析行业趋势", "扫描技术新闻", "生成每日简报", "提取Alpha级洞察", "战略情报汇总"]
---

# Personal Intelligence Hub V7.3 (Native Agent Edition)

> **Vision**: 消除过滤失败，通过“弱信号放大”与“物理去重”建立决策优势。将海量噪音降维为高管视角的抗幻觉决策资产。

## 0. 核心架构与质量准则 (Standards & Architecture)

### A. 情报质量准则 (Quality Standard - IQS)
必须遵循 `references/quality_standard.md` 对每一条情报执行审计：
1. **情报分级**: 标注 L1 (Signal) 到 L4 (Alpha)。重点提取 L3 (Insight) 和 L4 (Alpha)。
2. **“So What?” 审计**: 每一条情报必须包含：事实 (Fact)、联结 (Connection) 与 推演 (Deduction)。
3. **叙事纪律**: 禁止形容词，强制关联历史，反直觉优先。

### B. 五层价值链 (Value Chain)
1. **感知**: 结合 `references/feeds.json` 与 `google_web_search`。
2. **过滤**: 执行 5D 仲裁及物理去重拦截。
3. **关联**: 激活 Weaver (织者) 执行“二跳推理”。
4. **对抗**: 强制激活 `logic-adversary` 对高价值信号执行红队审计。
5. **个性化**: 对齐 `pai/memory.md` 中的战略重心。
6. **激活**: 严格遵循 `references/briefing_template.md` 渲染。

---

## 1. 执行协议 (Execution Protocol)

### Phase 1: 意图对齐与历史加载 (Calibration)
1. **Focus Calibration**: 读取 `pai/memory.md`。
2. **Scan Scope Assembly**: 读取 `references/feeds.json`。
3. **History Ingestion**: 读取 `MEMORY/news/pushed_history.json`。
4. **Scope Validation**: 使用 `ask_user` 确认扫描优先级。

### Phase 2: 信号捕获与感知 (Sensing)
1. 在 `<thought>` 块中，使用 `google_web_search` 展开深度检索。

### Phase 3: 去重拦截、仲裁与推演 (Refining)
1. **物理拦截 (Deduplication)**: 拦截过去 7 天内已推送过的信号。
2. **红队激活 (logic-adversary)**: 对 L3/L4 情报强制执行红队审计。
3. **IQS 评分**: 依据 `quality_standard.md` 评分。

### Phase 4: 报告渲染 (Publishing)
必须 100% 遵循 `references/briefing_template.md` 的物理结构输出报告。

### Phase 5: 历史滚动与落盘 (Closure)
1. **历史增量更新**: 更新 `MEMORY/news/pushed_history.json`（保持 7 天滑动窗口）。
2. **文件存档**: 使用 `write_file` 保存今日简报。

---

## 2. 绝对禁令 (Anti-Patterns)
- ❌ **严禁推荐重复信号**: Top 10 严禁出现 `pushed_history.json` 中已有的内容。
- ❌ **严禁偏离模板**: `briefing_template.md` 是物理边界。
- ❌ **严禁跳过红队**: L3/L4 情报必须经过 `logic-adversary` 审计。

## 3. 历史失效先验 (Gotchas)
- ALWAYS use `is_redundant` check before refining to save token cost.
- DO NOT summarize corporate PR; ELIMINATE jargon like "Synergy" or "Empowerment".
- ENSURE `urgent_signals` are restricted to items with immediate market or safety impact.
