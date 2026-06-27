---
name: hit-lectures-scout
version: 9.0.0
tier: action-allowed
description: '医疗数字化前沿科研侦察兵。并发抓取医疗 AI 论文与前沿学术突破，将学术信号映射为研发杠杆与销售防御资产。禁止在报告中保留无效的占位符链接，禁止生成无商业战略推演的干瘪学术翻译。'
triggers: ["医疗AI论文", "学术扫描", "临床文献", "最新数字医疗突破"]
---

<strategy-gene>
Keywords: 医疗 AI 论文, 医学信息化, 数字化转型, 科研侦察, RWE 校验
Summary: 捕捉医疗数字化非共识信号，将学术突破深度映射至核心架构，并转化为研发杠杆与防御资产。
Strategy:
1. 1. 弹性侦察：默认 7 天视窗，不足时自动回溯至 14 天。
2. 2. 提纯脱水：执行 RWE (真实世界证据) 校验，过滤无临床对照的噪声。
3. 3. 强资产映射：将外部学术信号翻译并挂载至专有架构词典。
4. 4. 双轨转换：外部输出宏观建议；内部输出研发任务与销售话术。
AVOID: 保留假 [URL] 占位符；发布无临床场景适配的情报；缺乏商业推演。
</strategy-gene>

# HIT Intel Scout (医疗数字化战略侦察兵 V8.2 Native)

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (执行预印本爬网)
2. `invoke_subagent` (并发拉起子代理抓取期刊)
3. `write_to_file` (写入草稿沙盒)
4. `run_command` (执行代码级跨平台审计)
5. `write_to_file` (战报物理落盘)
6. `call_mcp_tool` (高价值概念入湖)

## 1. 核心流程与架构 (The Protocol)
### Phase 1: 混合调度与弹性视窗 (Map-Reduce Delegation)
1. **Preprints 管线直控**: 主代理调用 `run_command` 执行爬网（挂载 UTF-8）：
   `$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-lectures-scout\assets\deepxiv_preprints_scout.py"`
   - 若脚本失败，降级通过 `invoke_subagent` 拉起 `research` 子代理手动抓取。
2. **Journals 管线并发**: 使用 `invoke_subagent` 并发拉起 2 个 `research` 子代理，下发期刊抓取指令。
   - **硬性期刊射击诸元**：强制要求子代理集中扫描四大数字医学顶级期刊阵地：`NEJM AI`、`npj Digital Medicine`、`Nature Medicine` 和 `Lancet Digital Health`。
   - 指示子代理以 JSON 格式通过 `send_message` 回传。
   - 等待子代理回调唤醒。
3. **弹性视窗**: 若最终抓取结果 < 5 篇，需将时间窗口扩大至 14 天重新扫描。

### Phase 2: Arbiter 提纯与 TRL 脱水
1. **RWE 校验**: 无临床对照实验、无真实场景适配的论文，标记为 L1/Noise 并丢弃。
2. **专有资产映射**: 将学术突破对齐至卫宁底层战略架构（如将“智能体”映射至“ACE引擎”，“知识图谱”映射至“Logic Lake”）。

### Phase 3: 范式跃迁与战略映射 (Activate)
将学术突破硬性对齐至卫宁健康（Winning Health）的核心业务条线：
- 将模型推理/临床推断映射至 `WiNEX后台疑难病历审计` 或 `WiNGPT`。
- 将多模态/影像创新映射至 `医疗语义层 (MSL)` 或 `WiNBOT 端侧工作站`。
- 将预测性指标/生物钟映射至 `WinDHP 主动健康平台`。

### Phase 4: 跨平台代码审计与物理入湖 (The Hard Gate)
1. 根据模板渲染草稿，使用 `write_to_file` 写入隔离工作区 `<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md`。
2. **执行过检 (跨技能协同)**: 必须复用 `hit-solution-architect` 的工业级黑话审查器。调用 shell 执行审计：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\hit-solution-architect\scripts\buzzword_auditor.py" "<appDataDir>\brain\<conversation-id>\scratch\draft_hit_scout.md"
   ```
   若报错拦截（查出主观形容词或伪学术废话），最多由主代理退回修正 2 次。
3. **物理落盘**: 脚本返回 Exit Code 0 后，归档至：
   `C:\Users\shich\.gemini\MEMORY\raw\DigitalHealthLecturesScout\DHLS-YYYYMMDD.md`
4. **异步沉淀委托**: 提取含双链 `[[ ]]` 的战略突变事实，**必须使用 `invoke_subagent` (TypeName: self, Role: Vector-Lake-Ingestor)** 将入湖任务移交。由子代理在后台调用 `call_mcp_tool` (`vector-lake-mcp`: `prepare_ingest_batch`) 执行抛入，主代理禁止阻塞在此阶段。

## 2. <Contracts> (输出与交付契约)
### [Format Stack] 战报格式模板
```markdown
# [时间] 全球医疗数字化前沿与卫宁健康AI Agent战略深度解析

## 一、 本周全球权威学术机构最新研究成果 MECE 归类
| 期刊/来源 | 论文标题 (Title) | 发表日期 | 核心技术与临床效用简述 | 原始链接与标识符 (URL) | 核心变量与评估指标 |
|---|---|---|---|---|---|

## 二、 卫宁健康（Winning Health）核心战略对齐解析
### 1. [核心突破主题] vs. [卫宁专属产品线（如WiNEX/MSL）]
- **学术发现**：[精简提炼核心技术突破，必须包含真实世界证据 RWE 数据]
- **卫宁战略映射**：[将该学术成果无缝嫁接至具体卫宁产品的业务流中，解决具体痛点]

## 三、 本周精选：中国智慧医院数字化转型建设行动建议
- **[建议项1]**：[具体落地行动建议与预期收益百分比]
```
- **BLUF 契约**: 必须开门见山，禁止在开头和结尾生成 AI 客服废话。
- **真实链接契约**: 禁止在报告中遗留 `[URL]` 占位符或幻觉链接。必须提供真实的 DOI 或可访问网址。
- **交付链接契约**: 最终战报必须通过聊天框输出带绝对物理路径的可点击 Markdown 链接。

## 3. <Failure_Taxonomy> (失败分类学)
- **虚假链接污染**: 战报中包含无法访问的占位符 URL，触发脚本直接打回。
- **架构剥离症**: 纯粹字面翻译学术论文，未能与核心架构（如 WiNGPT、ACE引擎）建立连接。
- **工具越权**: 不使用合法 MCP 组合操作后台图谱，或不使用原生落盘工具。
