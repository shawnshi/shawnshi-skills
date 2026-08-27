# 图像任务与提示词结构

在生成图片、编写配图计划或输出提示词前读取。该结构用于内部控制，不要求把所有字段展示给用户。

## 任务对象

```yaml
job:
  workflow: direct | review-first | plan-only | prompt-only | revise
  scope: single | series
  channel: website-hero | article-inline | slides | social-feed | story | print | custom
  count: 1
  aspect_ratio: "16:9"
  target_size: ""
  purpose: ""
  audience: ""
  text_policy: none | reserve-space | embedded-exact
  exact_text: ""
  user_requirements: []
  forbidden_elements: []

global_style:
  preset: editorial-watercolor | modern-editorial | brand-business | medical-concept | custom
  medium: ""
  palette: []
  texture: ""
  lighting: ""
  editorial_tone: ""
  recurring_motifs: []
  continuity_rules: []
  exclusions: []

frames:
  - id: "MI-01"
    article_anchor: ""
    core_message: ""
    visual_metaphor: ""
    subject_and_action: ""
    setting: ""
    composition: ""
    safe_area: ""
    mood: ""
    factual_locks: []
    forbidden_inventions: []
    status: planned | generating | passed | blocked
    version: 1
    retry_count: 0
```

## 路由规则

- `direct`：单图默认；系列图在用户要求直接完成时使用。
- `review-first`：只在用户明确要求先审大纲或样张时使用；最多暂停一次。
- `plan-only`：只输出配图计划，不调用图像工具。
- `prompt-only`：只输出可复制提示词，不调用图像工具。
- `revise`：只重新处理用户指定的资产。

## 单张提示词顺序

按以下顺序组成自然语言提示，不输出字段名堆砌：

1. **交付物**：一张独立图片、使用渠道和比例；明确不是长图、拼图、联系表或信息图。
2. **核心场景**：主体、动作、环境以及要表达的文章观点。
3. **构图**：视觉焦点、景别、层次、裁切余量和文字安全区。
4. **视觉风格**：媒介、色板、质感、光线和编辑语气。
5. **系列锚点**：固定色板、母题、人物特征和构图规则。
6. **文字策略**：无文字、仅保留安全区，或只出现引号中的准确原文。
7. **事实锁定**：必须准确呈现的内容和不得自行补充的内容。
8. **排除项**：只保留与当前任务相关的负向约束。

## 系列规则

- 所有图片共用同一份 `global_style`，每张只改变 `frame` 内容。
- 每个工具调用只生成一张独立图片，禁止把多张页面合成一张长图或拼图。
- 第一张通过质检后冻结媒介、色板、母题和人物特征；后续只修改页面级场景。
- 每批完成后更新状态，保留已通过图片；单张失败不得重做整套系列。
- 用户修改某一张时，只重开对应 `frame`，其他图片保持不变。
- 为防止视觉疲劳，系列图片保持同一视觉语法，但改变景别、空间关系和主次节奏。

## 医疗与事实字段

涉及医疗、解剖、器械、诊疗过程、临床界面、新闻事件或真实机构时填写：

- `factual_locks`：来自用户材料或可靠来源、必须准确的事实；
- `forbidden_inventions`：不得虚构的患者身份、检查结果、剂量、诊断、设备参数、Logo、人物或现场细节。

无法建立事实锁定时，改为明确的概念插画，不生成可能被误认为临床教学、新闻纪实或操作指导的画面。
