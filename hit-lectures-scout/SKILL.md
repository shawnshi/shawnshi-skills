name: hit-lectures-scout
description: 医疗数字化前沿侦察兵 (V5.0)。当用户询问“医疗AI最新论文”、“Nature/JAMA研究动态”或“科研前沿趋势”时，务必激活。该技能基于《龙虾教程》五层价值链重构，集成 SemHash 物理去重、RWE 硬核过滤、Weaver 跨界关联与黑板协作，输出具备实战杠杆价值的科研战报。
triggers: ["检索医疗AI论文", "扫描本周前沿探索", "Nature最新数字化研究", "JAMA医疗前沿", "科研哨兵扫描", "分析医疗大模型突破", "医疗AI论文", "Nature/JAMA研究", "医疗前沿创新"]
---

# SKILL.md: HIT Intel Scout V5.0 (医疗数字化战略侦察兵)

> **Version**: 5.0 (Lobster Architecture x Blackboard Pattern)
> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除“学术灌水”与“幻觉”，将学术突破转化为卫宁研发部的具体任务与销售线的防御武器。

## 0. 核心架构约束 (The 5-Layer Value Chain)

### 0.1 ADK 五维缺陷补偿 (ADK 5-Patterns)
- **Tool Wrapper (知识物理隔离)**: Phase 1 强制并发调度搜索工具，禁止直接依赖模型内置陈旧知识。
- **Inversion (窗口自适应)**: Phase 1 具备弹性视窗机制，确保有效样本量。
- **Generator (Schema 绝对防御)**: 生成结果强制读取模板文件，输出严格对齐 S-T-C 格式。
- **Pipeline (时序流转)**: Phase 1-5 顺序流转，禁止跳过审计环节。
- **Reviewer (红队压测)**: Phase 3 引入 `personal-logic-adversary` 对科研趋势进行商业化伪证。

### 0.2 龙虾架构增强
1.  **感知层 (Sense)**: 优先扫描物理目录进行 **SemHash (语义去重)**。若某篇论文已在过去 14 天内被扫描过，除非有重大二阶评论，否则强制拦截。
2.  **过滤层 (Filter)**: 实装 **Arbiter (仲裁者)**。执行 RWE (Real-World Evidence) 硬核过滤。**严禁**推荐仅在公开数据集上刷榜（SOTA）但无临床前瞻性研究的论文；无临床价值的算法论文直接标定为噪音。
3.  **关联层 (Connect)**: 激活 **Weaver (织者)**。寻找论文突破点与本周行业动态（如 Epic/Oracle 异动）的逻辑串联。生成“二跳推理”洞察。
4.  **激活层 (Activate)**: 强化 "So What" 框架。每一项 L4 级信号必须输出：`1个具体的研发预研任务（含建议技术栈）` 和 `1条针对竞对的销售防御话术`。

## 1. 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **默认视窗**: **过去 7 天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7 天内核心突破数 < 5 篇，则**必须自动将检索视窗扩大至 14 天**。

## 2. 核心工作流 (Blackboard Protocol)

### Phase 1: 物理沙盒切分与子代理并发 (Map-Reduce Delegation) [Mode: PLANNING]
 1. **构建物理任务包 (Task Packetization)**: 必须通过 `write_file` 在 `tmp/playgrounds/` 下生成三个独立的结构化指令包：
 - `Task_Journals_EN.md`: 目标锚定 Nature / JAMA / NEJM / Lancet / BMJ。要求提取近 14 天的临床数字化与 AI 突破。
 - `Task_Journals_CN.md`: 目标锚定《中华医学杂志》等国内顶级核心期刊。要求提取本土真实的 AI 落地场景与政策风向。
 - `Task_Preprints.md`: 目标锚定 Arxiv (CS.AI / CS.LG / Q-Bio)。要求提取极具潜力的底层架构突破。
 2. **集群并发调度 (Concurrent Dispatch)**: 并发调用 3 次 `generalist` (或 `academic-deep-research`) 子代理。将对应的 Task 文件路径作为 Payload 传入。强制子代理在其独立沙盒中完成“检索 -> 过滤 -> 提纯”闭环，并将结果分别写入`tmp/playgrounds/Response_EN.md`, `Response_CN.md`, `Response_Preprints.md`。
- *指令硬锁*：“禁止输出多余废话，仅交付包含 DOI、核心事实与初步 TRL 评级的硬核数据。”
3. **逻辑补位**: 若顶级正刊论文不足，必须提取热点趋势补齐信息密度。
4. **资产回收与 SemHash 拦截 (Harvest & Intercept)**: 主代理读取三个 `Response` 文件。扫描物理目录执行 SemHash 重，确认未与过去 14 天的历史报告重复后，将合并后的高纯度信息推入数字黑板，随后立即清扫 `tmp/` 下的中间产物。



### Phase 2: Arbiter 提纯与 TRL 脱水 [Mode: EXECUTION]
1. **战略分流**: 筛选 Top 5-10 篇文献进入数字黑板。
2. **Arbiter 审计**: 强制执行“真实世界证据 (RWE)”校验。无临床对照实验、无真实场景适配的论文标记为 L1/Noise。
3. **TRL 评估**: 依据 S-T-C 框架（信号-威胁-对策）进行成熟度脱水。

### Phase 3: Weaver 关联与多跳路由审计 [Mode: EXECUTION]
1. **Weaver 织网**: 寻找黑板上论文与卫宁核心产品或本周竞对动态的联结。
2. **Memory Interleave (MSA 增强)**: 若发现“技术落地可行性”存在证据断层，**强制**通过 `run_shell_command` 调用 `python {root}\.gemini\extensions\vector-lake\cli.py query ... --interleave`。跨文档调取冷库文档补齐“二跳推理”。
3. **激活 Reviewer**: 调用 `activate_skill(name='personal-logic-adversary')`。针对核心论文展开“商业化伪证”，推演其在 DRG 环境下的成本黑洞。

### Phase 4: 战略推演与杠杆锻造 (Activate) [Mode: EXECUTION]
1. **杠杆转换**: 将成果翻译为研发任务与销售话术。
2. **内容洗练**: 直接应用高管视角的冷酷风格优化内容，剔除学术冗余。

### Phase 5: 结构化生成与元数据审计 (Self-Healing & Persistence) [Mode: EXECUTION]
1. **强制模板**: 必须读取 `assets/report_template.md` 作为输出骨架。
2. **知识入湖**: 通过 `run_shell_command` 调用 `python {root}\.gemini\extensions\vector-lake\cli.py sync` 同步至逻辑湖。
3. **元数据完整性审计**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]`、`[URL]` 或占位符。必须逐一校验 DOI 和源地址。若缺失则使用 `google_web_search` 二次精准爬取。
4. **逻辑断层审计**: 确保每一项推理均挂载了精确的 `[Ref: Evidence_Node_ID]`。
5. **物理归档**: **[MANDATORY]** 调用 `write_file` 将最终报告保存在 `.\MEMORY\DigitalHealthLecturesScout\`，文件名格式为 `Weekly_DigitalHealth_YYYYMMDD.md`。

##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "hit-lectures-scout", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]
- DO NOT report pure algorithmic improvements without clinical context.
- **[CRITICAL]** INTERCEPT any paper that claims success solely on the MIMIC-III/IV or other public datasets without prospective validation.
- **[CRITICAL]** MANDATORY "Action Levers" for all L4 signals. NO LEVER = NO PUSH.
- **[CRITICAL]** ABSOLUTELY FORBIDDEN to use placeholders like `[Link]` or `[URL]` in the final report. Missing a verified DOI/URL is considered a System Fault. If toolchains fail, you MUST perform a secondary manual search via `google_web_search` to find the direct PDF or Journal link.
- ELIMINATE "Game-changing" labels; USE "Incremental" or "Disruptive" with evidence.
