# SKILL.md: Digital Health Weekly Brief (数字健康周报) V3.0 (Assault Edition)

---
name: digital-health-weekly-brief
description: 医疗数字化战区周报 Orchestrator。采用 V3.0 Agentic Deterministic Workflow，结合 Evidence-Mesh 证据落盘与 Logic-Adversary 逻辑防腐机制。负责并行调度子侦察兵，执行 S-I-A 战略推演，并输出高管视角的抗幻觉研报。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

## 1. 启动序列与边界 (Boot Sequence & Bounds)
- **触发指令**: 接收到检索医疗研报或生成数字健康周报的指令时触发。
- **时间锚点 (Time Anchor)**: 默认计算**过去 7 天 (滑动窗口)** 的日期区间 (YYYY-MM-DD)。若7 天内无核心智库/政务发文，则自动回溯至过去 14天，确保输出高信噪比的情报资产。
- **宁缺毋滥的平衡**: 优先保证时效性，但若核心资讯不足 5 条，必须启动“战略补位 (Strategic Backfill)”逻辑。

## 2. 核心工作流 (The V3.0 Deterministic Workflow)

### Phase 2: 分层异步侦察与横向扩展 (Parallel Recon & Lateral Sensing)
利用 Gemini 并行函数调用机制，同时触发以下 3 个 Subagents。要求其不仅搜索新发布的 PDF/报告，还要搜索正在进行的**政策咨询、智库观点文章及行业研讨会纪要**。
- `{root}\tmp\recon_strategy.md` (调用 `strategy_consulting_scout`)
- `{root}\tmp\recon_tech.md` (调用 `tech_advisory_scout`)
- `{root}\tmp\recon_policy.md` (调用 `macro_policy_scout`)

### Phase 3: S-I-A 推演与战略补位 (Generation & Backfill Logic)
读取上述证据链。若本周真实研报发布数少于 3 篇，Orchestrator 必须启动以下补位逻辑：
1. **态势感知补位**: 分析当前医疗 IT 市场的存量热点（如：DRG 2.0 落地进度、数据资产入表实务）在过去 7天内的舆论演进或技术细节微调。
2. **逻辑对齐**: 将上周未充分讨论的重磅资讯进行二阶拆解。
遵循 S-I-A 战略推演框架：
...
   - **[新增] 红队推演 (Red Team)**: 强制指出上述 Action 落地时的 **1 个致命执行风险或 SPOF (单点故障)**。

## 3. 输出排版与格式要求 (Formatting & Integration)
- **强约束**: 最终报告的“核心资讯清单”部分必须包含至少 **8 条** 经过脱水的研报/趋势信息。


### Phase 4: 非对称审计与逻辑防腐 (The Logic-Adversary Gate)
- 切换至 `/audit` 模式。必须引入 `logic-adversary` 视角（或自我质询机制），对 `DHWB_YYYYMMDD_draft.md` 进行苛刻审查。
- 寻找并指出目前推演中的 **3个潜在逻辑漏洞**（例如：URL幻觉、技术影响夸大、与卫健委政策冲突、S-I-A逻辑断层）。
- 修复这些漏洞后，生成最终制品 `{root}\tmp\DHWB_YYYYMMDD_final.md`。

### Phase 5: 物理归档与宏观记忆同步 (Archiving & State Alignment)
1. **交付归档**: 将最终成品移动至红区目录 `{root}\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md` (并清理 tmp 下的临时文件)。
2. **战略捕捉**: 审视本周情报是否触发《GEMINI.md》定义的"战略雷达" (Semantic Assets, Compliance, Tech)。若发现了改变医疗版图的重大拐点信号，触发 `/warroom` 协议，将核心洞察高度压缩并回写至全局 `{root}\MEMORY.md` 知识库。

## 3. 输出排版与格式要求 (Formatting & Integration)
1. **调用专属模板**: 必须读取并严格遵循 `resources/template.md`，保持 GitHub Alerts 块（`> [!IMPORTANT]`, `> [!NOTE]` 等）的视觉穿透力与完好无损。
2. **对齐实战样例**: 开始推演前，**强制读取** `examples/DHWB-Reference.md` 进行 Few-Shot 学习。保持高管口吻：冷峻、直击业务痛点、商业模型拆解清晰，绝对禁止生成虚无缥缈的公关废话。

---
*SYS_CHECK: Digital Health Weekly Brief Subsystem (V3.0 Assault Architecture) - Ready.*
