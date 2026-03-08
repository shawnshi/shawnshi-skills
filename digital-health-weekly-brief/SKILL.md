# SKILL.md: Digital Health Weekly Brief (数字健康周报) V3.0 (Assault Edition)

---
name: digital-health-weekly-brief
description: 医疗数字化战区周报 Orchestrator。采用 V3.0 Agentic Deterministic Workflow，结合 Evidence-Mesh 证据落盘与 Logic-Adversary 逻辑防腐机制。负责并行调度子侦察兵，执行 S-I-A 战略推演，并输出高管视角的抗幻觉研报。
triggers: ["生成数字健康周报", "检索医疗行业报告", "本周麦肯锡研报", "Digital Health Weekly Brief", "最新数字医疗白皮书", "扫描本周智库发文"]
---

## 1. 启动序列与边界 (Boot Sequence & Bounds)
- **触发指令**: 接收到检索医疗研报或生成数字健康周报的指令时触发。
- **时间锚点 (Time Anchor)**: 必须精确计算**本周一至周日**的日期区间 (YYYY-MM-DD)。LLM 必须交叉验证报告发布时间。非本周内容，**宁可留白也绝对禁止伪造**。
- **工作区隔离**: 所有的中间态产物（计划文档、侦察证据、初稿等）必须置于 `C:\Users\shich\.gemini\tmp\` (绿区)。

## 2. 核心工作流 (The V3.0 Deterministic Workflow)
严格按照以下顺序串行/并行执行，**每完成一步必须更新计划状态**。

### Phase 1: 战役锚定与确权 (Initialization & Planning)
在 `C:\Users\shich\.gemini\tmp\` 生成 `plan.md` (或 `task.md`)，确立本周三大军区（商业/技术/政策）的侦察命题及后续执行的 Checklist。

### Phase 2: 分层异步侦察与证据落盘 (Parallel Recon & Evidence-Mesh)
利用 Gemini 并行函数调用机制，**同时触发**以下 3 个 Subagents 进行侦察，将本周时间窗传入。
**强制落盘**: 每个子 Agent 返回后，主 Agent 必须将清洗后的真实 Top 情报（含源 URL 与摘要）写入物理文件，形成 Evidence-Mesh 证据链。
- `C:\Users\shich\.gemini\tmp\recon_strategy.md` (调用 `strategy_consulting_scout`: McKinsey, BCG 等，聚焦 VBC, RCM 等商业模式)
- `C:\Users\shich\.gemini\tmp\recon_tech.md` (调用 `tech_advisory_scout`: Gartner, IDC 等，聚焦 Agentic AI, EHR)
- `C:\Users\shich\.gemini\tmp\recon_policy.md` (调用 `macro_policy_scout`: WHO, 国家卫健委等，聚焦互联互通, 医保)

### Phase 3: S-I-A 推演与初稿锻造 (Generation & Cognitive Friction)
读取上述 `recon_*.md` 证据链文件，甄选 3-5 篇最具颠覆性的研报，代入 **"卫宁健康战略咨询总经理"** 视角，在 `C:\Users\shich\.gemini\tmp\DHWB_YYYYMMDD_draft.md` 中生成初稿。
遵循 S-I-A 战略推演框架：
1. **Signal (核心信号去水)**: (约300字) 剥离公关修饰，精炼提取底层业务/技术逻辑。
2. **Impact (护城河冲击)**: 该趋势如何降维打击现有 HIT 厂商？如何重塑医院 IT 预算分配逻辑？
3. **Action (应对指令) + Red Team (红队推演)**: (Impact+Action约800字)
   - 针对卫宁 (MSL, ACE, WiNEX)，给出防御、孵化或并购等行动指令。
   - **[新增] 红队推演 (Red Team)**: 强制指出上述 Action 落地时的 **1 个致命执行风险或 SPOF (单点故障)**，开启认知摩擦。

### Phase 4: 非对称审计与逻辑防腐 (The Logic-Adversary Gate)
- 切换至 `/audit` 模式。必须引入 `logic-adversary` 视角（或自我质询机制），对 `DHWB_YYYYMMDD_draft.md` 进行苛刻审查。
- 寻找并指出目前推演中的 **3个潜在逻辑漏洞**（例如：URL幻觉、技术影响夸大、与卫健委政策冲突、S-I-A逻辑断层）。
- 修复这些漏洞后，生成最终制品 `C:\Users\shich\.gemini\tmp\DHWB_YYYYMMDD_final.md`。

### Phase 5: 物理归档与宏观记忆同步 (Archiving & State Alignment)
1. **交付归档**: 将最终成品移动至红区目录 `C:\Users\shich\.gemini\MEMORY\DigitalHealthWeeklyBrief\DHWB-YYYYMMDD.md` (并清理 tmp 下的临时文件)。
2. **战略捕捉**: 审视本周情报是否触发《GEMINI.md》定义的"战略雷达" (Semantic Assets, Compliance, Tech)。若发现了改变医疗版图的重大拐点信号，触发 `/warroom` 协议，将核心洞察高度压缩并回写至全局 `C:\Users\shich\.gemini\MEMORY.md` 知识库。

## 3. 输出排版与格式要求 (Formatting & Integration)
1. **调用专属模板**: 必须读取并严格遵循 `resources/template.md`，保持 GitHub Alerts 块（`> [!IMPORTANT]`, `> [!NOTE]` 等）的视觉穿透力与完好无损。
2. **对齐实战样例**: 开始推演前，**强制读取** `examples/DHWB-Reference.md` 进行 Few-Shot 学习。保持高管口吻：冷峻、直击业务痛点、商业模型拆解清晰，绝对禁止生成虚无缥缈的公关废话。

---
*SYS_CHECK: Digital Health Weekly Brief Subsystem (V3.0 Assault Architecture) - Ready.*
