---
name: intelligence-hub
description: 战略情报作战中枢 (V5.0)。整合全球多源新闻抓取与二阶深度情报精炼，强制严格的三阶 GEB-Flow 落盘隔离与单步流转，新增红蓝对抗网关与认知蒸馏闭环，构建具备战略穿透力的统一"逻辑湖"。
language: py
triggers: ["获取最新情报", "分析行业趋势", "扫描技术新闻", "生成每日简报", "提取Alpha级洞察", "战略情报汇总"]
---

# SKILL.md: Intelligence Hub (战略情报作战中枢 V5.0)

> **Version**: 5.0 (The Strategic Intelligence Core)
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的"逻辑湖"。将海量的噪音降维打击，交付可以直接用于高管决策的 Alpha 级智库资产。
> **Mode**: 绝对服从 GEB-Flow 契约。引入状态变更通知、物理落盘强制隔离与单步硬阻断机制，彻底破除后台异步执行的“黑盒”不可控感。

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格依照 Phase 0 至 Phase 6 的顺序单步流转。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 探针进行显式声明。严禁擅自跨级跳跃或将长流程合并输出。

## 1. 触发逻辑 (Trigger)
- 当用户要求"获取最新情报"、"分析行业趋势"、"扫描技术新闻"或"生成每日简报"时激活。

## 2. 核心工作流 (Execution Protocol)

### Phase 0: 动态校准与战略核准 (Calibration & Alignment) [PLANNING Mode]
> **System Action**: 智能体**必须**通过 `task_boundary` 强制进入 `PLANNING` 模式。
1. **校准执行**：执行后台命令 `python scripts/calibrate_focus.py`。分析 `{root}/pai/memory.md` 中的关键词频率，动态调整 `references/strategic_focus.json` 中的战略权重。
2. **侦察目标确认 (Target Alignment)**：无论用户初始指令多么开放，你都【必须强制】调用 `ask_user` 工具，向用户复述你本次将覆盖的扫描域、权重偏好与预期产出物，确认“是否需要调整方向？”
3. **前置规划落盘 (Issue Tree)**：获得用户确认后，结合校准的焦点，**调用 `write_to_file` 工具**在工作区安全生成一份《情报战役实施纲领》 `implementation_plan.md`。详细描述本次的情报预期战果。
4. **硬性阻断 (Approval Gateway)**：规划保存完毕后，**必须调用 `notify_user` (BlockedOnUser: true) 挂起**，要求用户审阅并许可该计划扫描方案，未获明确放行严禁进入 Phase 1。

### Phase 1: 扫描矩阵展开 (Reconnaissance & Initialization) [EXECUTION Mode]
> **System Action**: 获得阶段 0 用户审批后，智能体**必须**通过 `task_boundary` 切换至 `EXECUTION` 模式，状态同步为 **`🟢 扫描收集`**。
1. **沙箱与计划落盘 (Manifest Initialization)**：
   - 物理生成该次任务的任务卡清点表：**调用 `write_to_file` 将 Phase 1-6 的推进节点落盘为 checklist 文件 `plan.md`**。**禁止在未建立物理节点追踪表的情况下进行爬虫。**
2. **采集引擎点火**：
   - 执行 `python scripts/fetch_news.py [--proxy URL]`。该组件支持增量排重并发与强容错。输出至 `tmp/latest_scan.json`。
3. **单步硬阻塞 (Single-step Halt)**：采集终了后，**必须首先通过文件操作工具更新 `plan.md` 进度**。接着**必须调用 `notify_user` 工具 (BlockedOnUser: true)**，向用户通报“信号矩阵抓取完毕”，询问是否推进深度精炼，阻断大语言模型长并发倾向。

### Phase 2: 高阶精炼与推演 (Refinement & Sense-Making) [EXECUTION Mode]
> **System Action**: 继续保持 `EXECUTION` 模式。
1. **精炼引擎驱动**：执行 `python scripts/refine.py`。该脚本进行权重过滤排序，并生成结构化 AI 提示词至 `tmp/refinement_prompt.txt`。提示词必须完全解耦于代码逻辑之外。
2. **AI 二阶推演 (The "So-What" Audit)**：Agent 物理读取该提示词文件，由语言模型本身基于内容执行深度推演与全量列表的中文化。
3. **物理成果写入**：推理结果**必须**严格遵循特定的结构要求，并由 Agent 调用工具显式覆写至 `{root}/MEMORY/news/intelligence_current_refined.json`。
   - **[硬要求]**：文件必须包含 `intel_grade` (基于 `references/quality_standard.md` 分配 L1-L4)、`top_10`、`translations`、`insights`、`punchline`、`digest`、`market` 等字段。
4. **同步更新进度**：覆写完成后，更新 `plan.md` 节点。

### Phase 3: 对抗性博弈网关 (Adversarial Audit Gateway) [EXECUTION Mode]
> **System Action**: 保持在 `EXECUTION` 模式。状态进入 **`🟡 综合起草`** 与强推演期。该阶段具备硬性分流器。
1. **阈值感应拦截**：读取 `intelligence_current_refined.json` 中情报的最高 `intel_grade` 等级。
2. **红方激活 (Red Team Activation)**：
   - **情况 A (当包含 L4 级别/Alpha 级情报时)**：**强制要求调用系统级命令 `activate_skill` 挂载 `name='logic-adversary'`。**获取红队策略后，必须在对话框内显式展开双角色视角的暴力逻辑辩证对抗，质疑该情报是真实拐点亦或是信息噪音。博弈产生的高价值矛盾点必须作为附录 `[Adversarial_Audit]` 落盘至工作目录 `.md` 中，并更新 `plan.md`。
   - **情况 B (仅包含 L1-L3 情报)**：跳过本博弈动作点，并更新 `plan.md` 表示免测。

### Phase 4: 战略简报铸造 (Strategic Briefing Forging) [EXECUTION Mode]
> **System Action**: 保持在 `EXECUTION` 模式。
1. **安全渲染**：执行 `python scripts/forge.py`，根据已解耦的 `references/briefing_template.md` 模板将 `intelligence_current_refined.json` 渲染成中文战略简报。若遭遇 JSON 格式损坏，触发脚本内置自愈逻辑降级渲染，确保终版交付物可用。
2. **文字手术洗稿**：必要时使用 `text-forger` 工具清洗行文风格，剔除不合时宜的模型套话“AI味”。
3. **同步更新进度**：更新 `plan.md` 进度。

### Phase 5: 物理归档与索引 (Archiving & Indexing) [EXECUTION Mode]
> **System Action**: 任务收尾进入 **`🔴 归档冻结`**。
1. **物理持久化**：执行 `python scripts/update_index.py`。清理过程沙箱态文件，并将终态战略报文持久化至 `{root}/MEMORY/news/intelligence_[YYYYMMDD]_briefing.md`，同步更新情报总谱架构 `_INDEX.md`。
2. **状态机闭环 (Final Review)**：完成全部归档后，更新 `plan.md`，随后在前端抛出一页纸核心提要，并**必须调用 `notify_user` 挂载该落盘简报绝对路径 (BlockedOnUser: true)**，移交至用户审阅端收口。

### Phase 6: 认知蒸馏闭环 (Cognitive Write-Back) [EXECUTION Mode]
> **System Action**: 本次技能运行的终审。
1. **智慧提取 (Knowledge Extraction)**：跳出资讯本身，提炼“因信息不对称导致的隐性机会”或“跨领域技术降维打击点”。
2. **全局存盘 (Memory Distillation)**：**必须显式使用 `write_to_file`或 `multi_replace_file_content` 工具** 把此 Alpha 级洞见或系统性推演反思追加写入至 `C:\Users\shich\.gemini\memory\MEMORY.md` 缓存，将其淬炼为个人战术外脑的资产复利。

## 3. Anti-Patterns (绝对禁令)

- ❌ **禁止黑盒长轮询 (No Silent Long-Polling)**：严禁无进度通知的静默爬取。哪怕是后台全自动执行，也必须前置声明正在执行的 🟢 扫描状态及进度通知。
- ❌ **禁止弱网关溢出 (Strict Thresholding)**：对低阶（L1-L2）公关水文启动大模型暴力穷举推演是对算力的极端浪费。严格遵循 Phase 3 的 `intel_grade` 分流阈值。
- ❌ **禁止全内存非落盘态传递 (No In-Memory Piping)**：从采集结果、推演 JSON、对抗性日志到最后定版 MD，**每一步都必须是基于落盘的物理文件流转。必须基于持久层的真实文件提取上下文再开启下一步骤。**
- ❌ **禁止散文式冗长汇报**：除了 `briefing` 的综述要求，中间生成的进度报告与洞见萃取必须坚持高强度信息密度，能表格化/模块化的一律结构化呈现。
- ❌ **禁止遗漏认知沉淀**：无论时间紧促与否，均不允许绕过 Phase 6 步骤。没有提取到 MEMORY 里的信息只是消耗品，只有固化进去的逻辑才是资产。
