---
name: hit-weekly-brief
version: 9.0.0
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

# HIT Weekly Brief (行业战区周报 V8.2 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `invoke_subagent` (并发拉起子代理扫描四大管线)
2. `call_mcp_tool` (检索图谱执行 14 天去重)
3. `write_to_file` (写入草稿沙盒)
4. `run_command` (跨平台防爆审计)
5. `write_to_file` (战报终稿落盘)
6. `invoke_subagent` (高价值实体异步委派入湖)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 四路并发原生沙盒扫描 (Concurrent Map-Reduce)
3. **初始化调度**: 主代理调用 `invoke_subagent` 并发拉起 4 个 `research` 子代理，下发以下指令包：
   - 顶级智库战略 (`Task_strategy.md`)
   - 公卫与合规政策 (`Task_policy.md`)
   - 医疗技术与架构 (`Task_tech.md`)
   - 跨界技术架构注入 (`Task_serendipity.md`，寻找金融/物流/军工等同构启发)
   - 指示子代理：“你必须返回 JSON 格式结果，且必须包含 `source_url`（必须是真实可访问的 https:// 链接）和 `publish_date`（精确的 YYYY-MM-DD 格式）。严禁使用类似 `[Title](Title)` 的假链接或占位符。”
2. **图谱语义去重**: 回收数据后，调用 `call_mcp_tool` (`vector-lake-mcp`: `search_vector_lake`) 扫描 14 天历史进行去重。

### Phase 2: 概念化用与图谱回溯 (Semantic Translation)
1. **概念降维**: 解读非医疗报告时，将核心概念 1:1 翻译为医疗 IT 实景（如将“边缘计算”翻译为“床旁监护流式分析”）。必须剔除“生态”、“赋能”等空洞幻觉，紧贴控费或质量痛点。
2. **多跳关联**: 结合过往 HIS/EMR 架构案例，推演跨界逻辑在医疗业务线的可落地性。

### Phase 3: Contrarian 对抗审计
强制要求寻找一份与本周主推共识（如 McKinsey / Gartner 结论）完全相反的数据报告或专家评论，借此识别“共识幻觉”。

### Phase 4: 全局缝合与跨平台防爆审计
1. 渲染简报草稿，使用 `write_to_file` 写入隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\draft_hit_brief.md`。
2. **防爆代码审查**: 调用跨平台审计脚本（挂载 UTF-8，强制 WaitMsBeforeAsync=3000 防死锁）：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\scripts\hit_audit_gate.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_brief.md" --mode brief
   ```
3. 若审计不通过（如查出假链接、缺失非共识观点），退回修正重试。

### Phase 5: 物理落盘与异步入湖 (Activate & Ingestion)
1. 审计通过后，使用 `write_to_file` 落盘：
   `C:\Users\shich\.gemini\MEMORY\raw\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md`
2. **实体入湖 (STQM & Payload MCP)**: 强制通过 `invoke_subagent` 委派入湖子代理。
   - 子代理必须将前置提取的 **Contrarian 观点** 严格编码为 STQM 格式的 `tension_edges`。
   - 必须通过 `write_to_file` 生成本地 `.json` 载荷文件，然后调用 `vector-lake-mcp:prepare_ingest_batch` 进行物理入湖，严禁通过命令行直传长文本。

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
