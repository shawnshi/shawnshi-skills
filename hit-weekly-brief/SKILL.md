---
name: hit-weekly-brief
version: 9.2.0
tier: action-allowed
description: '医疗行业战区研报中枢。聚合顶级智库研报并执行逆向对抗分析，识别被主流忽略的破坏性信号。禁止重复 14 天内的旧报，禁止保留无 ROI 支撑的公关废话或幻觉链接。'
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "扫描本周智库发文"]
---

<strategy-gene>
Keywords: 数字健康周报, 智库研报, 二跳推理, 跨界注入
Summary: 聚合顶级智库研报并执行逆向对抗分析，识别破坏性信号与共识幻觉。
Strategy:
1. 1. 四维扫描：并行调度策略、技术、政策、跨界（如FinTech）四条管线。
2. 2. 织者关联：将零散预测串联为系统级规律，并与医疗 IT 实景结合。
3. 3. 非共识对抗：寻找与主流研报相反的证据，识别“共识幻觉”。
4. 4. 强硬落地：严格遵守 Signal->Insight->Action 框架。
AVOID: 重复提取 14 天前的旧闻；丢失跨界启发模块；未经验证直接写入图谱。
</strategy-gene>

# HIT Weekly Brief (行业战区周报 V9.2 Native)

## 核心里程碑 (Milestone Protocol)
**[MILESTONES]** 放弃僵化的顺序调用，通过状态机推进以下关键节点，遇到异常自主容错：
- **M1: 并发扫描**：派发 4 个 `research` 侦察兵提取四大管线的 JSON 情报。
- **M2: 图谱去重**：通过 `vector-lake-mcp` 查询 14 天历史进行语义去重。
- **M3: 防爆审计**：生成草稿后通过沙盒 Python 脚本进行合规检验（必须动态解析真实物理路径）。
- **M4: 资产落盘**：周报终稿必须以 Artifact 制品形式留存在当前隔离会话。
- **M5: 异步入湖**：派发 `TypeName: self` (Role: Ingestor) 执行 STQM 张力边归档（绝对异步 Fire-and-forget）。

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 四路并发原生沙盒扫描 (Concurrent Map-Reduce)
1. **初始化调度**: 主代理调用 `invoke_subagent` 并发拉起 4 个 `research` 子代理。在分发 Prompt 时，**必须向每个子代理注入当前的系统日期**，并套用以下标准化的“集装箱” Prompt 模板，以彻底消除幻觉与解析崩溃：

> **[子代理通用 Prompt 注入模板]**
> "你是一个高级 `research` 侦察子代理。当前系统日期是 `[动态填入今天日期]`。
> 你的专属任务是：`[填入以下 A/B/C/D 四大管线之一的具体指令]`。
> 
> **硬性约束：**
> 1. **隐式沙盘与跨语种检索**：必须针对性构造英文 Query 检索顶级海外智库，过滤 14 天前的旧闻。返回数据前必须在 `<recon_workspace>` 标签内完成事实交叉验证。
> 2. **机器通信协议**：你必须且只能通过 `send_message` 回传数据。严禁输出任何 Markdown 散文，必须严格匹配以下 JSON Schema（若无合规数据，返回空数组）：
> ```json
> {
>   "pipeline_name": "strategy | policy | tech | serendipity",
>   "signals": [
>     {
>       "title": "[原文标题]",
>       "publish_date": "YYYY-MM-DD",
>       "core_insight": "[中文翻译后的深度洞察，至少50字]",
>       "source_url": "https://..."
>     }
>   ]
> }
> ```

2. **四大管线专属指令 (Task Payloads)**（请替换上述模板中的变量）：
   - **[A] 顶级智库战略**：强制检索 Rock Health, a16z Bio+Health, CB Insights, 或是近期的华尔街医疗做空报告（Short-seller reports）。
   - **[B] 公卫与合规政策**：检索国家卫健委、FDA 等最新医疗控费、院内管理或数据安全合规动向。
   - **[C] 医疗技术与架构**：采用逆向检索法则，强制搜索 `ROI Deficit`、`Post-mortem` (医疗AI项目死亡复盘) 或 `Pilot Purgatory` (试点地狱) 等惨痛教训。
   - **[D] 跨界启发 (Serendipity)**：检索 Fintech（金融科技）、物流或军工领域的最新系统架构落地案例，推演其在医疗 IT 场景下的同构降维打击潜力。

3. **图谱语义去重**: 回收数据后，调用 `call_mcp_tool` (`vector-lake-mcp`: `search_vector_lake`) 扫描 14 天历史进行去重。

### Phase 2: 概念化用与图谱回溯 (Semantic Translation)
1. **概念降维**: 解读非医疗报告时，将核心概念 1:1 翻译为医疗 IT 实景（如将“边缘计算”翻译为“床旁监护流式分析”）。必须剔除“生态”、“赋能”等空洞幻觉，紧贴控费或质量痛点。
2. **多跳关联**: 结合过往 HIS/EMR 架构案例，推演跨界逻辑在医疗业务线的可落地性。

### Phase 3: Contrarian 对抗审计
强制要求寻找一份与本周主推共识（如 McKinsey / Gartner 结论）完全相反的数据报告或专家评论，借此识别“共识幻觉”。

### Phase 4: 全局缝合与跨平台防爆审计
1. 将简报草稿写入当前会话的 `scratch/` 沙盒目录（必须在上下文中**动态解析绝对物理路径**）。
2. **防爆代码审查**: 调用内部审计脚本（挂载 UTF-8，强制 WaitMsBeforeAsync=3000 防死锁）：
   ```powershell
   # 警告：必须将 [Absolute_Draft_Path] 替换为你动态解析出的真实物理路径
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "[Absolute_Draft_Path]" --mode brief
   ```
3. 若审计不通过（如查出假链接、缺失非共识观点），自主修复重试最多 2 次。若脚本缺失，则启动自主内审机制后继续。

### Phase 5: Artifact 资产落盘与异步入湖
1. 质检通过后，严禁写入不可见的 `MEMORY/` 目录。必须使用 `write_to_file` 在当前会话空间生成 **Artifact 制品**（必须附带 `UserFacing: true` Metadata），交付给用户审查。
2. **实体入湖 (STQM & Payload MCP)**: 提取高价值实体，使用 `invoke_subagent` 拉起一个 `TypeName: self`，`Role: Vector Lake Ingestor` 的子代理。
   - 子代理负责将前置提取的 **Contrarian 观点** 严格编码为 STQM 格式的 `tension_edges` JSON 载荷，并物理存入其沙盒。
   - 子代理负责调用 `vector-lake-mcp:prepare_ingest_batch` 进行入湖。主代理在派发任务后立刻结束回合，**严禁同步轮询或等待**。

## 2. <Contracts> (输出与交付契约)

### [Format Stack] 战报格式模板
```markdown
# 医疗行业战略智库周报 - [YYYY-MM-DD]
> **全局非共识洞察 (BLUF)**: [一句话总结本周最大的认知张力或战略冲突]

## 一、 全球主流智库洞察全景矩阵
*(所有机构名称必须加上双链 `[[ ]]`，URL 必须是真实的 `https://`，日期必须是 YYYY-MM-DD)*
| 机构名称 | 报告/研究名称 | 发布日期 | 核心战略信号 (Signal) | 真实来源链接 |
|---|---|---|---|---|

## 二、 医疗数字化转型深度战略剖析 (S-I-A 框架)
### 1. [[核心概念]]：[子标题]
- **趋势背景 (Signal)**: ...
- **医疗映射 (Insight)**: ...
- **落地对策 (Action)**: ...

## 💥 三、 认知张力与冲突网 (STQM Tension Edges)
*(寻找与本周主推共识相反的证据，识别“共识幻觉”)*
- [必须提取为纯 JSON 代码块，包裹 `tension_edges` 数组，严格遵循 STQM 规范备用入湖]

## 🌌 四、 跨界注入 (Serendipity)
- **非医疗行业启发**: [FinTech/军工/物流等真实案例]
- **医疗架构迁移**: [跨界降维打击策略]
```

- **反客套话契约 (Anti-Fluff)**: 严禁在开头或结尾生成“您好”、“为您整理完毕”、“欢迎随时联系”等大模型客服语气。必须直入正题。
- **交付链接契约**: 战报生成后，必须向用户输出包含绝对物理路径的可点击 Markdown 链接。

## 3. <Failure_Taxonomy> (失败分类学)
- **幻觉与链接造假**: 终稿包含占位符 URL，未进行连通性验证。
- **共识狂热**: 全篇顺应主流报告，未找到任何相反或对抗性的证据 (Contrarian)。
- **工具越权**: 不使用合法 MCP 组合操作图谱，或写入错误的物理宏路径。
- **水词泛滥**: 留存公关废话、主观吹捧且无 ROI 支撑的文字。
