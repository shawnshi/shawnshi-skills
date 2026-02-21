# Multi-Agent Writer — Anti-Patterns (禁令库)

> Agent 在 Phase 4 审计时必须对照以下反模式逐条扫描。命中任何一条即判定为 FAIL，必须物理修复。

---

## 🚫 Category A: AI 废话黑名单 (中英双语)

以下词汇/短语一经发现，必须 **物理删除或替换为具体的动词/名词**：

### 中文黑名单
| 废话 | 替换策略 |
|------|---------|
| 赋能 | 用具体动作替换：驱动、重构、接管、替代 |
| 底层逻辑 | 用具体机制描述：定价模型、利益分配规则、技术约束 |
| 抓手 | 用具体工具替换：杠杆、入口、控制点 |
| 闭环 | 描述具体的反馈回路或验证步骤 |
| 打通生态 | 描述具体的集成方式和数据流向 |
| 势能 | 用具体的量化指标替换 |
| 颗粒度 | 直接说明精细到什么层级 |
| 在当今快速发展的时代 | 直接删除，进入正题 |
| 众所周知 | 直接删除，用事实替代 |
| 综上所述 | 直接删除或替换为"这意味着" |
| 这不仅是…更是… | 拆分为两个独立判断句 |
| 不可否认的是 | 直接删除 |
| 我们不禁要问 | 直接提问，不要绕弯 |

### English Blacklist
| Platitude | Replacement Strategy |
|-----------|---------------------|
| delve | Use: examine, dissect, expose |
| tapestry | Use: system, network, structure |
| crucial / paramount | Use specific consequences: "failure here causes X" |
| landscape | Use: market, arena, battlefield |
| leverage (as verb) | Use: exploit, weaponize, deploy |
| holistic | Specify what dimensions are covered |
| synergy | Describe the specific compounding mechanism |
| game-changer | Quantify the magnitude of change |
| cutting-edge | Name the specific technology or method |
| robust | Specify what failure modes it survives |

---

## 🚫 Category B: 结构性反模式

### B1. 悬念式开头 (Suspenseful Opening)
❌ 以"让我们先来看一个问题…"或"你有没有想过…"开头。
✅ 直接以最具冲击力的结论或数据开头。

### B2. 连续列表轰炸 (Bullet-Point Dumping)
❌ 连续超过 3 个 Bullet Points 而没有散文段落衔接。
✅ 化为散文排比句，用递进连接词编织（"更残酷的现实是"、"然而，这套逻辑的底座正在崩塌"）。

### B3. 名词短语标题 (Noun-Phrase Headings)
❌ "市场竞争现状"、"技术发展趋势"、"客户需求分析"。
✅ Action Title: "存量价格战正在摧毁长尾厂商的利润池"。

### B4. 总结式结尾 (Summary Conclusion)
❌ "总而言之，以上三点构成了……" 式的机械重复。
✅ 以开放性隐喻、冷峻预测或行动质问结束。

### B5. 均匀句长 (Monotonous Sentence Length)
❌ 全篇句子长度高度一致，毫无节奏感。
✅ 短句如匕首（固定结论），长句如暗流（铺陈复杂博弈背景）。

### B6. 滥用加粗 (Bold Abuse)
❌ 全篇出现 4 处以上 `**加粗**`。
✅ Three-Bold Rule: 最多 3 处，必须是反共识的终极判词。

### B7. 图文割裂 (Decoupled Visuals)
❌ 插入图表但正文不解释图表内容，或图表与正文结论不对应。
✅ 正文必须围绕图表来写，图表是论证的视觉锚点。

### B8. 虚构数据 (Fabricated Data)
❌ 使用无来源的精确数字（如"效率提升73%"）。
✅ 所有数据必须通过搜索工具获取，或标注为"估算/推演"。

### B9. 公关体 (PR Tone)
❌ 使用推销式语言："我们的解决方案完美地…"、"行业领先的…"。
✅ 使用分析师视角：冷峻、客观、数据驱动。

### B10. 正确的废话 (Correct But Useless)
❌ 所有人都知道的常识被包装成深刻洞察，如"数据是新时代的石油"。
✅ 通过 Devil's Advocate 的 "So What" 测试——如果删掉这句话文章不受影响，则必须删除。
