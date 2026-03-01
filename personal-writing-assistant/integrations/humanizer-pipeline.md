# Integration: Humanizer-zh-pro Pipeline

## 概述
使用 humanizer-zh-pro 对 personal-writing-assistant 生成的文章进行最终润色，消除"AI味"。

## 适用场景
- 文章已完成，需要最后的"去AI化"处理
- 目标受众对"翻译腔"敏感
- 需要更自然、有温度的表达

## 两阶段工作流

### 阶段1：使用 personal-writing-assistant 创作
聚焦于：
- 逻辑严密性
- 洞察深度
- 结构完整性

**此阶段不必过度纠结措辞**，因为 humanizer-zh-pro 会处理。

### 阶段2：使用 humanizer-zh-pro 润色
```bash
/humanizer-zh-pro --input article_draft.md
```

humanizer-zh-pro 会：
- 消除翻译腔
- 替换机械的逻辑连接词
- 增加自然的口语化表达
- 保持原有的逻辑和观点

## 分工明确

| 职责 | personal-writing-assistant | humanizer-zh-pro |
|------|---------------------------|------------------|
| 逻辑推演 | ✓✓✓ 核心职责 | ✗ 不改动 |
| 观点构建 | ✓✓✓ 核心职责 | ✗ 不改动 |
| 数据引用 | ✓✓✓ 核心职责 | ✗ 不改动 |
| 措辞自然度 | ✓ 基本要求 | ✓✓✓ 专项优化 |
| 消除AI腔 | ✓ 部分关注 | ✓✓✓ 核心职责 |

## 示例对比

### personal-writing-assistant 初稿
> 「然而，我们需要认识到，远程医疗的价值主张在很大程度上依赖于便利性这一单一维度。当我们对比疫情前后的数据时，可以清晰地看到，用户在拥有选择权的情况下，倾向于选择传统的面诊模式。因此，我们可以得出结论：远程医疗的增长是情境依赖的，而非趋势性的。」

**问题**：
- "然而"、"因此" 等连接词机械
- "在很大程度上"、"可以清晰地看到" 等冗余表达
- 句式过于规整，缺乏变化

### humanizer-zh-pro 润色后
> 「远程医疗的卖点，说白了就是方便。
>
> 看看数据：疫情结束后，患者重新回到医院。不是远程医疗不好，而是当你能去医院时，你还是更信任面对面的医生。
>
> 所以，远程医疗的爆发不是什么'大势所趋'，只是特殊时期的应急方案。」

**改进**：
- 删除机械连接词
- 短句增强节奏
- 口语化表达（"说白了"、"看看数据"）
- 保持原有逻辑和观点

## 最佳实践

### ✅ DO
- 让 personal-writing-assistant 先专注于逻辑和洞察
- 用 humanizer-zh-pro 处理最终稿
- 保留 humanizer-zh-pro 的修改，除非改变了原意

### ❌ DON'T
- 在写作阶段过度纠结措辞（效率低）
- 让 humanizer-zh-pro 改动逻辑结构（超出其职责）
- 跳过 personal-writing-assistant 的【分析师手记】（这部分可以不润色）

## 特殊注意

### 哪些部分需要润色？
- ✓ 正文全部内容
- ✓ 小标题
- ? 【分析师手记】（可选，看目标受众）
- ✗ 数据引用（保持原样）
- ✗ 专业术语（保持原样）

### 哪些风格更需要润色？
- **Narrative风格**：强烈需要（口语化很重要）
- **Provocative风格**：需要（力量感来自自然表达）
- **Default风格**：需要
- **Academic风格**：谨慎（可能过度口语化）
- **Balanced风格**：适度需要

## 工作流示例

```bash
# Step 1: 创作
python personal-writing-assistant/assistant.py \
  --topic "远程医疗的未来" \
  --mode Standard \
  --style narrative \
  > draft.md

# Step 2: 润色
/humanizer-zh-pro --input draft.md --output final.md

# Step 3: 审阅
# 人工检查 final.md，确保：
# - 逻辑未被改动
# - 关键数据未丢失
# - 语言更自然
```

## 未来增强

可能的自动化：
- [ ] 在 personal-writing-assistant 中增加 `--with-humanize` 参数
- [ ] 自动调用 humanizer-zh-pro 进行后处理
- [ ] 提供"润色前后对比"视图
