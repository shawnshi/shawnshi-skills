name: hit-lectures-scout
description: 医疗数字化前沿科研侦察兵。当用户要求“检索医疗AI论文”、“扫描本周前沿探索”、“分析 Nature/JAMA 医疗前沿”或“追踪医疗大模型突破”时激活。用于跨数据库检索临床AI文献、执行真实世界证据(RWE)过滤，并输出带商业防御策略的结构化科研战报。
---

# SKILL.md: HIT Intel Scout V5.0 (医疗数字化战略侦察兵)

> **Vision**: 捕捉学术界的非共识信号，通过结构化补偿消除“学术灌水”与“幻觉”，将学术突破转化为卫宁研发部的具体任务与销售线的防御武器。

## 1. 触发逻辑与侦察视窗 (Trigger & Recon Window)
- **默认视窗**: **过去 7 天 (滑动窗口)**。
- **弹性降维 (Rolling Window)**: 若 7 天内核心突破数 < 5 篇，则**必须自动将检索视窗扩大至 14 天**。

## 2. 核心工作流 (Blackboard Protocol)

### Phase 1: 物理沙盒切分与子代理并发 (Map-Reduce Delegation) [Mode: PLANNING]
1. **集群并发调度**: 并发调用 3 次 `generalist` (或 `academic-deep-research`) 子代理。将本技能 `assets/` 目录下的 `task_journals_en.md`, `task_journals_cn.md`, `task_preprints.md` 的内容分别作为 Payload 指令传入。
2. **要求子代理**: 强制子代理在其独立的物理沙盒中完成“检索 -> 过滤 -> 提纯”闭环，并将结果分别写回 `tmp/playgrounds/Response_EN.md`, `Response_CN.md`, `Response_Preprints.md`。
3. **时序与逻辑补位**: 必须等待所有子代理任务彻底完成（设置 `wait_for_previous=true` 或分轮并发）后，主代理才能读取三个 `Response` 文件。若顶级正刊论文不足，必须提取热点趋势补齐信息密度。
4. **资产回收与 SemHash 拦截**: 扫描物理目录执行 SemHash 去重。若某篇论文已在过去 14 天内被扫描过且无重大二阶评论，强制拦截。将合并后的高纯度信息推入数字黑板，随后立即清扫 `tmp/` 下的中间产物。

### Phase 2: Arbiter 提纯与 TRL 脱水 [Mode: EXECUTION]
1. **战略分流**: 筛选 Top 5-10 篇文献进入数字黑板。
2. **Arbiter 审计**: 强制执行“真实世界证据 (RWE)”校验。无临床对照实验、无真实场景适配的论文标记为 L1/Noise。
3. **TRL 评估**: 依据 S-T-C 框架（信号-威胁-对策）进行成熟度脱水。
4. **"So What" 框架激活**: 每一项 L4 级信号必须输出：`1个具体的研发预研任务（含建议技术栈）` 和 `1条针对竞对的销售防御话术`。

### Phase 3: Weaver 关联与多跳路由审计 [Mode: EXECUTION]
1. **Weaver 织网**: 寻找黑板上论文与卫宁核心产品或本周竞对动态的联结。
2. **Memory Interleave (MSA 增强)**: 若发现“技术落地可行性”存在证据断层，**强制**通过 `run_shell_command` 调用 `~/.gemini/extensions/vector-lake/cli.py query ... --interleave` (Windows 下请解析为绝对路径后执行)。跨文档调取冷库文档补齐“二跳推理”。
3. **激活 Reviewer**: 调用 `activate_skill(name='personal-logic-adversary')`。针对核心论文展开“商业化伪证”，推演其在 DRG 环境下的成本黑洞。

### Phase 4: 战略推演与杠杆锻造 (Activate) [Mode: EXECUTION]
1. **杠杆转换**: 将成果翻译为研发任务与销售话术。
2. **内容洗练**: 直接应用高管视角的冷酷风格优化内容，剔除学术冗余。

### Phase 5: 结构化生成与元数据审计 (Self-Healing & Persistence) [Mode: EXECUTION]
1. **强制模板**: 必须读取 `assets/report_template.md` 作为输出骨架。
2. **知识入湖**: 通过 `run_shell_command` 调用 `~/.gemini/extensions/vector-lake/cli.py sync` (Windows 下请解析为绝对路径后执行) 同步至逻辑湖。
3. **元数据完整性审计**: **[HARD LOCK]** 严禁在最终报告中使用 `[Link]`、`[URL]` 或占位符。必须逐一校验 DOI 和源地址。若缺失则使用 `google_web_search` 二次精准爬取。
4. **逻辑断层审计**: 确保每一项推理均挂载了精确的 `[Ref: Evidence_Node_ID]`。
5. **物理归档**: **[MANDATORY]** 调用 `write_file` 将最终报告保存在 `.\