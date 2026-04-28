---
name: hit-digital-strategy-partner
description: 顶级医疗数字化战略专家 (V18.0)。用于医疗IT深度咨询、ROI测算、重构商业模式、MBB框架分析、行业研究报告、董事会备忘录与高规格战略验证。通过黑板状态机、五层价值链、二跳推理、悲观 ROI 压测、结果型质量门与可装配脚本后端，交付可验证、可降级、可装配的战略资产。
---

<strategy-gene>
Keywords: 医疗 IT 战略, 深度咨询, ROI 测算, 商业模式重构
Summary: 利用黑板状态机执行五层价值链分析，交付可验证、抗压测的战略资产。
Strategy:
1. 黑板优先：所有核心判断必须先写入 strategy_blackboard.json。
2. 执行二跳推理：从政策信号推演至具体架构变化与实施后果。
3. 悲观 ROI 压测：在预算削减 30% 的极端场景下验证方案成立性。
AVOID: 严禁绕过黑板直接起草；禁止只写趋势不写行动杠杆；禁止未通过结果门校验即交付。
</strategy-gene>

# HIT Digital Strategy Partner (V18.0: The Blackboard Foundry)

工业级医疗数字化战略决策支持系统。目标不是一次性写出漂亮长文，而是把战略判断锻造成有状态、有证据、有结果门的固态资产。

## 0. 核心契约 (System Contract)
1. **黑板状态机优先**: 所有核心判断必须先写入 `C:\Users\shich\.gemini\tmp\strategy_blackboard.json`。禁止绕过黑板直接起草正文。
2. **模式分流**:
   - `brief`: 1500-2500 字，快速高密度战略简报。
   - `deep-dive`: 8000+ 字，分章节深度研究。
   - `board-memo`: 1000-1800 字，董事会/高管备忘录。
3. **资产闭环**: 每个项目必须维护 `working_memory.json`、`hypothesis_matrix.json`、`evidence_matrix.csv`、`outline.md`、`implementation_plan.md`、`chapter_*.md`、`final_report.md`。
4. **结果门优先于文风门**: 终稿必须通过 `strategy_gate.py`，核心检查是中心判断、悲观 ROI、二跳推理、行动杠杆、残酷风险，而不是“看起来像不像咨询公司”。

## 1. 能力契约 (Capability Contract)
1. **Vector Lake**:
   - 可用时执行语义去重与历史报告拦截。
   - 不可用时，显式输出“待核事实清单”并继续。
2. **子代理**:
   - 可用时并行调用政策研究与商业竞争研究。
   - 不可用时，主代理必须串行完成同等职责，禁止跳过。
3. **Red Team / Humanizer**:
   - `personal-logic-adversary` 可用时用于 Phase 3。
   - `personal-write-humanizer` 可用时用于 Phase 5。
   - 不可用时，主代理执行本地对抗清单与结果门审计。
4. **脚本后端**:
   - 黑板: `C:\Users\shich\.codex\skills\hit-digital-strategy-partner\scripts\blackboard.py`
   - 黑板校验: `C:\Users\shich\.codex\skills\hit-digital-strategy-partner\scripts\blackboard_validate.py`
   - 项目资产初始化: `C:\Users\shich\.codex\skills\hit-digital-strategy-partner\scripts\memory_manager.py`
   - 报告装配: `C:\Users\shich\.codex\skills\hit-digital-strategy-partner\scripts\assembler.py`
   - 终稿结果门: `C:\Users\shich\.codex\skills\hit-digital-strategy-partner\scripts\strategy_gate.py`

## 2. 五层价值链 (5-Layer Value Chain)
- **Sense**: 检索政策、厂商、支付改革、实施案例，并做语义去重。
- **Filter**: 剔除无来源支撑的液态辞令。
- **Connect**: 形成至少 1 条政策红线到技术债/商业模式的二跳推理。
- **Personalize**: 把判断压到具体客户、具体产品或具体医院信息化处境。
- **Activate**: 用模式化交付和脚本后端形成可复核资产。

## 3. 执行协议 (Execution Protocol)

### Phase 0: Alignment & Boot [PLANNING]
1. 调用 `ask_user` 或等效方式确认：受众、预算、对抗焦点、目标模式、目标篇幅。
2. 运行 `memory_manager.py init --path <project_path> --topic <topic> --mode <mode>` 初始化项目资产。
3. 运行 `blackboard.py init --topic <topic> --mode <mode>` 初始化黑板状态机。
4. 把对齐信息写入黑板 `alignment`，至少包括：`audience`、`budget`、`attack_focus`、`target_words`、`mode`。

### Phase 1: Recon & Evidence Capture [PLANNING]
1. 并行或串行执行政策研究与商业竞争研究。
2. 产出 3-5 条核心假设并写入 `hypothesis_matrix.json`。
3. 把每条证据写入 `evidence_matrix.csv`，字段至少包括：`id,source_type,claim,evidence,implication,status`。
4. 更新 `working_memory.json` 的 `insights`、`fact_sheet` 与 `entities`。
5. 把证据摘要写入黑板 `evidence.policy`、`evidence.market`、`evidence.competitor`、`evidence.clinical`。

### Phase 2: Logic Collision [PLANNING]
1. 形成 1 个中心判断，写入黑板 `logic_mesh.core_judgment`。
2. 形成至少 1 条二跳推理，写入黑板 `logic_mesh.second_hop_inferences`。
3. 产出 `outline.md` 与 `implementation_plan.md`，标题必须是完整判断句，不允许名词堆砌。
4. 在放行前运行 `blackboard_validate.py --strict`。未通过时，禁止进入正文。

### Phase 3: Adversarial Validation [EXECUTION]
1. 执行悲观 ROI 压测，结果写入黑板 `decisions.pessimistic_roi`。
2. 执行红队审计，识别单点故障、落地阻力和叙事漏洞。
3. 形成 `action_levers` 与 `residual_risks`，分别写入黑板与 `working_memory.json`。
4. 若可用，调用 `personal-logic-adversary`；不可用时，至少完成以下本地对抗清单：
   - 这个判断在预算被砍 30% 时是否仍成立？
   - 这个判断是否真的形成“政策 -> 架构/流程 -> ROI”的闭环？
   - 这个判断最终落实成了什么人类动作？

### Phase 4: Drafting by Mode [EXECUTION]
1. **deep-dive**:
   - 必须逐章起草。
   - 每次对话仅允许 1 章，每章建议 >= 1200 字。
2. **brief**:
   - 允许一次性完成 3-5 个高密度章节。
   - 强制保留 `中心判断`、`悲观 ROI`、`行动杠杆`、`残酷风险` 四块。
3. **board-memo**:
   - 允许一次性完成完整备忘录。
   - 开头直接写 `紧急预警` 与 `董事会动作建议`。
4. 所有模式都必须让每个章节服务于同一个中心判断，禁止平行拼贴。

### Phase 5: Activate & Gate [EXECUTION]
1. 如可用，调用 `personal-write-humanizer` 精修；否则只做压缩与去重，不做空泛美化。
2. 运行 `assembler.py --path <project_path> --mode <mode> --output <final_file>` 合并终稿。
3. 运行 `strategy_gate.py --path <final_file> --mode <mode> --blackboard <blackboard_path> --strict` 审计终稿。
4. 只有结果门通过，才允许最终交付。

## 4. 结果型质量门 (Outcome Gate)
终稿必须同时满足以下 5 条：
1. **中心判断**: 全文只能服务 1 个中心判断。
2. **悲观 ROI**: 必须出现悲观场景下的 ROI 或资源压力测试。
3. **二跳推理**: 必须明确展示至少 1 条“政策/市场信号 -> 架构/流程变化 -> 商业或实施后果”的推理链。
4. **行动杠杆**: 必须给出人类可执行的动作，不允许停留在口号层。
5. **残酷风险**: 必须披露至少 1 个会伤害方案成立性的真实风险。

## 5. 绝对禁令 (Anti-Patterns)
- ❌ 未经过黑板校验就开始正文。
- ❌ 只写“趋势判断”，不写证据与行动杠杆。
- ❌ 把多模式任务都强行塞成万字报告。
- ❌ 终稿未通过 `strategy_gate.py` 仍直接交付。

## 6. Telemetry & Metadata
- 使用 `write_file` 或等效能力将本次任务元数据保存到 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- 元数据至少包含：`skill_name`, `mode`, `topic`, `status`, `result_gate`, `project_path`。

## 7. 历史失效先验 (NLAH Gotchas)
- `IF [Action == "Draft"] THEN [Halt if Blackboard.ready == false]`
- `IF [Mode == "deep-dive"] THEN [Require Single-Chapter Generation]`
- `IF [Action == "Final Delivery"] THEN [Require StrategyGate == pass]`
- `IF [Asset Missing IN (hypothesis_matrix.json, evidence_matrix.csv, working_memory.json)] THEN [Halt and Repair Assets]`
