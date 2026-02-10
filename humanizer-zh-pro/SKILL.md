---
name: humanizer-zh-pro
description: 专业的中文文本“去 AI 化”编辑器。消除机械感、翻译腔与虚假的逻辑词。使用场景：改写 AI 稿件、优化汇报、使公文“说人话”。
---

# Humanizer-zh-pro (Master Edition)

将 AI 生成的冷冰冰的文本，转化为具有母语温度与真实人类节奏的表达。

## Core Philosophy
*   **Verb-Driven**: 动词是灵魂，名词是累赘。
*   **De-Logic**: 拆除“此外、综上所述、实现”等廉价的逻辑脚手架。
*   **Roughness**: 拥抱真实的犹豫、口语化表达与不规则的句式节奏。

## The "Three-Level" Workflow

### Level 1: Semantic Cleansing (语义清洗)
*   **Action**: 扫描输入文本，识别并删除黑名单词汇（见 `references/GUIDELINES.md`）。
*   **Goal**: 移除明显的 AI 标记（如“进行”、“致力于”）。

### Level 2: Rythmic Reconstruction (语感重塑)
*   **Action**: 
    *   将被动语态改为主动语态。
    *   长句拆短，允许出现短促的结论句。
    *   增加主观语气词（如“说实话”、“我看”、“其实”）。
*   **Goal**: 制造真实人类的说话节奏。

### Level 3: Soul Injection (场景化注入)
*   **Action**: 根据目标场景（博客/咨询/回复）参考 `references/EXAMPLES.md`。
*   **Goal**: 使文本符合特定的社会契约与身份。

## Usage

### 1. 快速诊断与示例
使用脚本获取该主题的理想改写示范：
```bash
python scripts/humanize_engine.py "待润色文本片段"
```

### 2. 手动改写
1.  加载文本。
2.  执行 L1 -> L2 -> L3 润色。
3.  **必须**使用 `references/CHECKLIST.md` 执行最后校验。

## Best Practices
*   **Talk, Don't Lecture**: 想象你在深夜和朋友喝咖啡，而不是在台上讲课。
*   **Specific Over General**: 用具体的故事代替宏大的叙事。
*   **Imperative**: 优先使用祈使句和直接陈述。

## Troubleshooting
*   **改写后太散乱**: 增加 1-2 个具体的动词锚点。
*   **AI 味依然浓**: 检查是否保留了“由于...所以”这种死板的结构。
