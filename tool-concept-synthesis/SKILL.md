---
name: tool-concept-synthesis
version: 9.0.0
tier: action-allowed
description: '跨越孤立实体的战略宏观分析。当用户要求“概念裂变”、“全景缝合”、“跨界联系”或“绘制这张全景图”时使用。'
triggers: ["概念裂变", "全景缝合", "跨界联系", "绘制全景图"]
---

<strategy-gene>
Keywords: 跨实体缝合, 宏观拓扑, 暗线联系, 战略洞察长文
Summary: 将几十个碎片化的实体页面，通过底层 Vector Lake 图谱算力提取证据链，然后炼金重组为极具战略深度的宏观长文。
Strategy:
1. 1. 算力下沉：强制调用 vector-lake-mcp 获取底层的拓扑关联，严禁大模型自己盲搜文本。
2. 2. 拓扑映射：在虚拟黑板上寻找多个实体之间的“化学反应”（因果、演化、竞争），必须论证它们为何发生关联。
3. 3. 渲染出图：将底层的图谱数据反向渲染出一篇新的体系长文，并在其中铺满 [[ ]] 图谱链接。
AVOID: 严禁纯靠大模型记忆或纯文本全文检索硬凑关联；严禁得出不具执行力的大话空话。
</strategy-gene>

# Tool Concept Synthesis (宏观缝合与体系全景图 V9.0 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. call_mcp_tool (调用 vector-lake-mcp 提取图谱数据)
2. [No Tools] (内部进行逻辑推理)
3. write_to_file (写入全景长文并包含遥测)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: Topology Extraction (底层图谱提取)
1. 接收用户的宏观议题（如“医疗大模型的破局点”、“卫宁健康去年的打法规律”）。
2. **绝对禁令**：不要试图一次次用 grep_search 盲搜纯文本文件。必须将检索意图下沉给底层图谱。
3. **调用 Vector Lake**：通过原生 call_mcp_tool 调度 ector-lake 服务器的 search_vector_lake 或 query_logic_lake 工具，提取底层的实体拓扑、权重边以及带有来源出处的 Claims。

### Phase 2: Logic Collision (黑板碰撞)
1. 将 Vector Lake 吐出的关联实体 [[Entity A]]、[[Entity B]] 以及它们共享的 Claims 罗列在虚拟黑板上。
2. 计算化学反应：大模型接管业务逻辑推演。基于底层的 claim_graph，推理寻找它们之间的隐性联系、矛盾点或演化脉络。**必须论证它们为何发生关联**。

### Phase 3: Canon Output (体系构建)
输出一篇大维度的战略洞察报告。
1. 必须使用 pai/USER.md 规定的极冷酷、极具密度的语言风格。
2. 将最终的宏观规律反向提纯（Compiled Truth）并建立一个新的顶层体系页面。使用 write_to_file 将文件落盘到 C:\Users\shich\.gemini\MEMORY\wiki\战略洞察_{议题关键词}.md。
3. 新页面内必须大量使用 [[ ]] 链接回底层的子实体，形成一张网。

## 2. <Contracts> (输出与交付契约)
执行完毕后，向用户输出：
1. 体系全景页面的物理生成路径（如 C:\Users\shich\.gemini\MEMORY\wiki\战略洞察_XXX.md）。
2. 一段高度密集的宏观结论（The Canon），其中必须用 [[ ]] 标出起支撑作用的下级实体。
3. **Telemetry 记录**: 任务执行完成后，必须使用 write_to_file 将本次执行的元数据以 JSON 格式保存至：
   C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json
   结构示例：{"skill_name": "tool-concept-synthesis", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}

## 3. <Failure_Taxonomy> (失败分类学)
- **幻觉工具调用**：严禁在指令中混入类似 search_vector_lake(mode='claim') 这种伪造的 Python 语法。交互必须走标准的 call_mcp_tool。
- **检索召回率极低 (Data Starvation)**：如果拆解展开后的 MCP 检索依然命中极少，拒绝强行缝合长文。向用户反馈知识库在当前议题下厚度不足，建议先转入情报收集，严禁靠记忆强行造假。
- **关联逻辑牵强 (Forced Causality)**：如果发现几个实体之间仅有时间重叠而无业务逻辑关联，必须在报告中诚实指出“表面相关实则独立”，不得强行造词。
- **路径漂移**：记录遥测数据时严禁使用 {root} 等虚假变量，必须使用写死的物理绝对路径。
