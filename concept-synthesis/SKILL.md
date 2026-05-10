---
name: concept-synthesis
description: 跨越孤立实体的战略宏观分析。当用户要求“概念裂变”、“全景缝合”、“跨界联系”或“绘制这张全景图”时使用。
---

<strategy-gene>
Keywords: 跨实体缝合, 宏观拓扑, 暗线联系, 战略洞察长文
Summary: 将几十个碎片化的实体页面，通过多意图并行检索，炼金重组为一篇极具战略深度的宏观长文。
Strategy:
1. 强制执行 `SOUL.md` 的 Multi-Query Expansion，切忌只用原句单次搜索。
2. 在虚拟黑板上寻找多个实体之间的“化学反应”（因果、演化、竞争），必须论证它们为何发生关联。
3. 反向提纯出一篇新的体系长文，并在其中铺满 `[[ ]]` 图谱链接。
AVOID: 严禁仅仅进行词汇的罗列与堆砌；严禁得出不具执行力的大话空话。
</strategy-gene>

# Concept Synthesis (宏观缝合与体系全景图)

## Workflow

### Phase 1: Macro-Query Expansion (宏观检索网络)
1. 接收用户的宏观议题（如“医疗大模型的破局点”、“卫宁健康去年的打法规律”）。
2. 强制执行 `SOUL.md` 规定的 **Multi-Query Expansion**。将议题拆解成 5-6 个截然不同的关键词组合，分别对本地知识库进行穷尽式检索。

### Phase 2: Topology Mapping (拓扑映射)
1. 将检索出来的各个独立实体 `[[Entity A]]`、`[[Entity B]]` 罗列在虚拟黑板上。
2. 计算化学反应：寻找它们之间的隐性联系、矛盾点或演化脉络。**绝不仅仅是列举，必须论证它们为何发生关联**。

### Phase 3: Canon Output (体系构建)
输出一篇大维度的战略洞察报告。
1. 必须使用 `pai/USER.md` 规定的极冷酷、极具密度的语言风格。
2. 将最终的宏观规律反向提纯（Compiled Truth）并建立一个新的顶层体系页面（如 `wiki/战略洞察_XXX.md`）。
3. 新页面内必须大量使用 `[[ ]]` 链接回底层的子实体，形成一张网。

## Failure Modes
- **检索召回率极低**：如果拆解展开后的检索依然命中间极少，拒绝强行缝合长文，向用户反馈知识库在当前议题下厚度不足，建议先转入情报收集。
- **关联逻辑牵强**：如果发现几个实体之间仅有时间重叠而无业务逻辑关联，必须在报告中诚实指出“表面相关实则独立”，不得强行造词。

## Output Contract
执行完毕后，向用户输出：
1. 体系全景页面的生成路径（如 `MEMORY/wiki/XXX.md`）。
2. 一段高度密集的宏观结论（The Canon），其中必须用 `[[ ]]` 标出起支撑作用的下级实体。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "concept-synthesis", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)