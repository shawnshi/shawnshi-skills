---
name: strategic-reading
description: 带上极度功利的商业目的去榨取一篇长文、研报或分析。当用户要求“战略滤镜阅读”、“带上目的读”、“榨取这篇长文”或“战略拆解”时使用。
---

<strategy-gene>
Keywords: 战略滤镜, 榨取式阅读, 降维打击, 执行级剧本
Summary: 抛弃中立的全文总结，戴上特定战略滤镜去抽取文章中可直接应用的杠杆与破局点，输出冷酷的战术投射。
Strategy:
1. 强制要求用户锁定“战略滤镜”（必须带目的读）。
2. 过滤一切与目标无关的常识、情绪与冗长铺垫。
3. 强行执行“降维映射”，将外部的教训投射到我方的业务实体上。
AVOID: 严禁输出四平八稳的客观总结；严禁保留无干货的过度铺垫；如果用户不给目的，严禁盲目开工。
</strategy-gene>

# Strategic Reading (战略滤镜阅读器)

## Workflow

### Phase 1: Define the Lens (锁定战略滤镜)
1. 接收用户输入的长文（或链接/PDF）以及**核心战略目标**（例如：“从这篇 SaaS 发展史中，找出卫宁健康如何应对 AI 冲击的启示”、“透过这篇文章看协和医院下一步的动作倾向”）。
2. 如果用户没有给出明确的滤镜，必须**反问并逼迫**用户给出一个具体的业务难题或防御目标。

### Phase 2: Ruthless Extraction (冷酷榨取)
1. 全面扫描文本。
2. **过滤噪音**：无情地砍掉文章中所有的背景铺垫、通用常识、情绪抒发以及与“战略滤镜”无关的支线情节。
3. **降维打击**：针对保留下来的关键信息，执行降维映射。将别人身上的教训/经验，强行投射到用户的战略目标实体上。

### Phase 3: Playbook Output (生成可执行剧本)
使用极具密度的语言，输出一份战略简报（或直接作为 Compiled Truth 归档入 Wiki）：
1. **核心杠杆 (The Leverage)**：用一句话概括文章中可被我们直接挪用的核心力量/机制。
2. **战术投射 (Tactical Mapping)**：
   - 敌方/他人的做法 -> 我们对应的业务线该如何效仿或防范。
   - 列出 2-3 个极具落地性的 Action Items。
3. **致命盲区 (Blind Spots)**：文章中没说、但在我们的战场中一旦忽视就会致命的变量。
4. **图谱挂载**：在产出的报告中，务必对涉及的友军、敌军、产品使用 `[[ ]]` 进行图谱双链标记，遵守 `Entity Linking Contract`。

## Failure Modes
- **文章质量极低**：如果该文章满篇公关稿、无任何核心杠杆与执行细节，立即停止榨取，并向用户报告“此文无提纯价值（公关废料）”。
- **目标不匹配**：如果用户给定的战略目标与文章内容存在绝对鸿沟（例如要求从医疗报告中看游戏研发），必须指出“缺乏投影基点”，建议更换文章。

## Output Contract
输出一份包含四个模块的高密度战术投射剧本 (Playbook)：
- 核心杠杆
- 战术投射 (Action Items)
- 致命盲区
- 新抽取的图谱节点 `[[ ]]` 列表


##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "strategic-reading", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)