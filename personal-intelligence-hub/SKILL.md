name: personal-intelligence-hub
description: 战略情报作战中枢 (V6.0)。当用户询问“有什么新动态”、“分析行业趋势”或需要“每日简报”时，务必激活。该技能通过全球多源抓取、ADK 5-Patterns 缺陷补偿及二阶逻辑精炼，将噪音降维为 Alpha 级智库资产。
triggers: ["获取最新情报", "分析行业趋势", "扫描技术新闻", "生成每日简报", "提取Alpha级洞察", "战略情报汇总"]
---

# SKILL.md: Personal Intelligence Hub (个人情报作战中枢 V6.0)

> **Version**: 6.0 (ADK 5-Patterns x Cognitive Compounding)
> **Vision**: 捕捉非共识信号，构建具备战略穿透力的“逻辑湖”。将海量噪音降维打击，交付可以直接用于高管决策的 Alpha 级智库资产。

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格依照 Phase 0 至 Phase 6 的顺序单步流转。在跨越任何 Phase 前，必须在输出首行打印 `[System State: Moving to Phase X]` 探针。严禁跨级跳跃。

## 1. 触发逻辑 (Trigger)
- 当要求"获取最新情报"、"分析行业趋势"、"扫描技术新闻"或"生成每日简报"时激活。

## 2. 核心工作流 (Execution Protocol)

### Phase 0: 战略对齐与 Inversion 校准 [Mode: PLANNING]
- **Calibration (Inversion 门控)**：运行 `scripts/calibrate_focus.py`。
- **强制拦截**: 调用 `ask_user` 向用户复述扫描域（AI/医疗数字化/医疗 AI）与权重，确认“是否需要调整方向？”。
- **二元自检 (Binary Check)**：检查 `strategic_focus.json` 是否与当前 `memory.md` 的关注点 100% 匹配？ [Yes/No]。如果不匹配，强制重校准。
- **计划落盘**: 使用 `write_to_file` 生成 `implementation_plan.md`，调用 `notify_user` (BlockedOnUser: true) 审批。

### Phase 1: 扫描矩阵展开 (Tool Wrapper) [Mode: EXECUTION]
- **Initialize**: 物理生成 `plan.md` 进度表。
- **采集点火**: 执行 `scripts/fetch_news.py`。该组件作为 **Tool Wrapper** 隔离了实时知识获取的物理噪音。
- **单步硬阻塞**: 更新 `plan.md`，调用 `notify_user` 通报抓取完毕。

### Phase 2: 高阶精炼 (Generator 结构防御) [Mode: EXECUTION]
- **精炼驱动**: 执行 `scripts/refine.py`。
- **AI 二阶推演**: Agent 读取精炼提示词文件，执行深度洞察。
- **物理覆写 (Generator约束)**: 结果必须 100% 对齐 `intelligence_current_refined.json` 的 Schema。

### Phase 3: 对抗博弈网关 (Reviewer 对抗) [Mode: EXECUTION]
- **红方激活**: 若包含 L4/Alpha 情报，强制激活 `activate_skill(name='logic-adversary')`。
- **显式对抗**: 展开逻辑博弈，质疑情报是真实拐点还是噪音。记录 `[Adversarial_Audit]`。

### Phase 4: 战略简报铸造 (Generator) [Mode: EXECUTION]
- **安全渲染**: 执行 `scripts/forge.py`。
- **洗稿**: 调用 `text-forger` 剔除“AI 味”。

### Phase 5: 归档与索引 (Pipeline) [Mode: EXECUTION]
- **物理持久化**: 执行 `scripts/update_index.py`。将终态报文持久化至 `{root}/MEMORY/news/`。
- **结案验收**: 更新 `plan.md`，调用 `notify_user` 挂载路径。

### Phase 6: 认知蒸馏 (Memory Compounding) [Mode: EXECUTION]
- **智慧提取**: 提炼“反常识洞察”。
- **全局存盘**: 显式使用 `write_to_file` 追加写入至 `pai\MEMORY.md`。

## 3. Anti-Patterns (绝对禁令)
- ❌ **禁止黑盒静默执行**：每一步必须有 🟢 状态通知。
- ❌ **禁止全内存非落盘态传递**：每一步必须基于落盘的物理文件。
- ❌ **禁止遗漏认知沉淀**：不提取到 MEMORY 的信息只是消耗品。
