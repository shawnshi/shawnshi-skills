---
name: mentat-collaboration-audit
description: 基于真实会话记录、日志、工具调用和遥测事件审计系统效率与人机协作摩擦，复算等待、技能载入、错误重试、子代理Token、上下文压缩和写入授权指标，并按需生成Markdown报告和HTML审计面板。用于复盘执行效率、排查系统绕路、核验连接器失败或权限阻塞、生成证据化协作报告；默认只读，不自动修改或持久化。
---

# 系统与协作审计

## 权限边界

- 默认执行只读审计。读取、分析和报告不授权修改任何配置、规则、代码、技能或外部系统。
- 用户明确要求实施范围内本地可逆修复后直接执行，不增加第二次确认；外部、不可逆和长期记忆写入仍按授权合同处理。
- 不自动保存报告、写入知识库或登记长期记忆。只有用户明确要求时才持久化。
- 日志可能包含私人内容、凭据或业务数据。只读取任务所需范围，输出前脱敏，禁止回显秘密和完整个人内容。

## 分支选择

- **一般证据化复盘（默认）**：只分析授权范围内的既有记录，不因读取技能而运行 Token 计量或写新遥测。缺少既有计量证据时报告缺口／不可计算；本轮补写回执不得充当历史事实。
- **显式技能载入计量实验**：只有任务明确要求计量或确需现场采样，且当前授权覆盖采样与临时写入时，按 [references/WORKFLOW.md](references/WORKFLOW.md) 的计量分支创建隔离回执；新样本与历史证据分开。
- **Codex hooks 适配**：只有该宿主实际提供对应 Hooks 能力且任务需要时，读取 [references/CODEX-HOOKS.md](references/CODEX-HOOKS.md)。Pi 不因存在脚本或安装记录而假设钩子生效，也不套用 Codex `/hooks`。

## 执行流程

1. 明确根任务、时间范围、授权来源、目标指标和数据缺口；区分能回答与不能回答的问题。
2. 收集真实证据并建立事件序列。事件级审计先读 [references/WORKFLOW.md](references/WORKFLOW.md)：遵守采集、活动 JSONL 冻结、Codex rollout 标准化和敏感数据约束；中间态写入须在当前授权的隔离 scratch 内，无写入授权则使用既有稳定证据或说明限制。
3. JSON/JSONL 输入按 [references/SCHEMA.md](references/SCHEMA.md) 核对字段，运行 `python generate_final_report.py --input <path> --strict`；不忽略部分覆盖。自然语言复盘不伪造结构化事件。
4. 证据检查通过后按 [references/ANALYSIS.md](references/ANALYSIS.md) 先看任务结局、用户介入／返工与上次整改后续，再展开八个分析视角。仅消费显式注释与已授权来源；缺证据就标记不可用，不从消息数推断动机。等待、载入、重试、子代理、授权和压缩恢复按 WORKFLOW 作为解释证据，不以统计图数量代替任务结果。
5. 每条发现区分事实、计算、用户陈述与推断，绑定证据位置、置信度、替代解释、影响和复现条件；不把相关性写成因果关系。
6. 按安全影响、收益、成本和可逆性排序，区分技能、编排、运行时和政策层修改。形成行动时读 [references/IMPROVEMENT.md](references/IMPROVEMENT.md)，分开 SYSTEM 修复与 USER 实践，只选下一项有护栏、比较条件和证伪标准的最小实验。只有证据面独立、宿主支持且并行确有收益时使用子代理，否则单代理完成；传最小任务包及结构化回包要求。
7. 在当前答复交付范围与覆盖、关键结论、发现、指标口径、建议优先级、未知项与残余风险。只有用户明确要求保存或整改时才执行对应写入；持久化 MD/HTML 必须先读 WORKFLOW 的归档、同源 manifest、成对提交与完成检查合同。

## 按需资源

- 证据检查后的八个分析视角、SYSTEM 维护与 USER 使用动作：[references/ANALYSIS.md](references/ANALYSIS.md)。
- 维护／使用动作卡、假设示例与可复制提示：[references/IMPROVEMENT.md](references/IMPROVEMENT.md)。
- 六个结果问题与支撑证据结构：[references/report-template.md](references/report-template.md)。
- 事件字段、错误信封、子代理回包与授权指纹：[references/SCHEMA.md](references/SCHEMA.md)。
- 快照冻结、Rollout 标准化、五类控制、上下文恢复与成对报告提交：[references/WORKFLOW.md](references/WORKFLOW.md)。
- 保存过的聚合 JSON 使用 `python scripts/validate_agent_audit.py <report.json>` 验证；用户要求交互式仪表盘时使用自包含的 `assets/template.html`。
- 脚本的输入、哈希、幂等、原子提交和失败语义以脚本帮助、Schema 与确定性测试为准，不在主技能重复实现细节。

## 输出结构

1. 六个结果问题：已完成／未解决任务、代价最高的已证实可避免摩擦、AI 转交用户的负担、应保留的人类决策、上次整改后续、下一项唯一实验与证伪条件。
2. 各结论旁列证据、来源声明／核验状态、任务／介入／返工／cohort 分母、覆盖与未知。
3. 八个视角的发现、稳定 F-xx／R-xx 连接、定性／计算边界与替代解释。
4. 运行指标作为支撑证据；SYSTEM／USER 动作、验证方法及残余风险。

## 完成检查

- 每条结论均有证据，披露分子、分母、样本量、缺失与跳过记录；不填造指标。
- 历史缺口未由本轮采样反填；候选载入不冒充正式回执，文本 Token 不冒充账单 Token。
- 事件级审计与持久化任务完成 WORKFLOW 对应验证；Codex hooks 状态按适配说明分层核验。
- 敏感信息已脱敏；未超出授权修复、采样、持久化或配置修改。
