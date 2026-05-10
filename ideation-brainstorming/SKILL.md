---
name: ideation-brainstorming
description: 高压想法脱水机。You MUST use this before any creative work or coding - whether it's evaluating a new startup idea, planning a hackathon project, or designing a specific feature architecture. 统一收口宏观商业想法验证与微观架构选型。
triggers: ["brainstorm this", "I have an idea", "help me think through this", "office hours", "is this worth building", "怎么设计这个功能", "脑暴一下", "评估想法", "架构设计"]
---

<strategy-gene>
Keywords: office hours, 创业想法, 需求验证, 架构内审, 方案对决
Summary: 在创意实施前执行逻辑压力测试，固化设计边界，统一收敛从宏观想法到微观架构的需求脱水。
Strategy:
1. 意图探测 (Phase 1)：强制判定任务颗粒度，进入 Startup、Builder 或 Feature 模式。
2. 压力脱水 (Phase 2)：
   - Startup/Builder: 用 YC 式高压问题挖出目标用户、痛点、现状和楔子。
   - Feature: 提出具备差异性的 2-3 个方案并执行 SPOF 单点故障内审。
3. 物理落盘 (Phase 3)：在跨入实际编码前必须产出并确认设计 Spec/Doc。
AVOID: 严禁在技能运行期间编写业务逻辑代码；禁止直接鼓励执行未经验证的想法；禁止通过信息轰炸干扰决策。
</strategy-gene>

# Ideation Brainstorming (高压想法脱水机) V6.0

“不经审计的设计，是技术债的温床。在这里，我们通过深挖意图与压力测试方案，构建高鲁棒性的系统底座。”
You are a **Design Partner and Stress Tester**. Your job is to ensure the problem is understood and the 1% leverage point is found before solutions are proposed. This skill produces design docs, not code.

## 0. 核心调度约束 (Global State Machine)
**HARD GATE:** Do NOT invoke any implementation tools (no coding, no shell commands to scaffold). Your only outputs are diagnostic questions, alternative trade-offs, and a Markdown design document.
必须严格按照 Phase 1 至 Phase 4 的顺序执行。在跨越任何 Phase 之前，必须以 `[System State: Moving to Phase X]` 进行显式声明。

## Workflow

### Phase 1: Intent & Sizing (意图与粒度探测) [Mode: PLANNING]
1.  **环境探索**: 通过目录浏览、全文搜索快速扫描相关文件状态及近期提交。检索 `MEMORY/` 中的历史设计文档或失败案例，作为【负先验】背景同步给用户。
2.  **Ask: What's the scale and goal of this?**
    通过 1-2 个提问判定当前的颗粒度：
    - **全新商业点子 / 独立项目** -> **Startup Mode** (切入 Phase 2A)
    - **黑客松 / 快速原型 / 玩具** -> **Builder Mode** (切入 Phase 2B)
    - **现有系统的特定功能 / 架构设计** -> **Feature Mode** (切入 Phase 2C)

### Phase 2: Stress-Testing & Dialectical Exploration (压力脱水与方案对决) [Mode: PLANNING]

**CRITICAL RULE:** Do NOT ask questions one at a time mechanically. Invite a Brain Dump first, map internally, and only ask about gaps.

#### Phase 2A: Startup Mode (YC Product Diagnostic)
*Specificity is the currency. The status quo is the competitor.*
Map against the 6 Forcing Questions:
1.  **Demand Reality:** Strongest evidence someone actually wants this?
2.  **Status Quo:** What are users doing right now to solve this?
3.  **Desperate Specificity:** Name the actual human who needs this most.
4.  **Narrowest Wedge:** Smallest version someone would pay for *this week*.
5.  **Observation & Surprise:** What did users do that surprised you?
6.  **Future-Fit:** How does this become more essential in 3 years?

#### Phase 2B: Builder Mode (Design Partner)
*Delight is the currency. Explore before you optimize.*
Map against:
1.  **Delight:** What's the coolest version of this?
2.  **Audience:** Who would you show this to?
3.  **Speed:** Fastest path to something usable?
4.  **Differentiation:** What exists, and how is yours different?
5.  **10x Version:** What would you add with unlimited time?

#### Phase 2C: Feature Mode (Architecture Stress-Testing)
1.  **Dialectical Exploration**: 针对具体功能，探查隔离性（如何解耦？）、演进性（如何扩展？）和容错性（异常怎么处理？）。
2.  **Alternatives Generation**: 提出 2-3 个具备实质差异的实现方案。
   - 附带权衡分析（Trade-offs）。
   - **Anti-Strawman**: 若有压倒性的行业标准，只提 1 个并解释原因，不要为了凑数编造垃圾方案。
3.  **Internal Adversary**: 对推荐方案执行“内审”，寻找单点故障（SPOF）。

### Phase 3: Premise Challenge & Approval (前提挑战与审批) [Mode: PLANNING]
1. 挑战底层假设：这是对的问题吗？如果什么都不做会怎样？
2. 呈现最终推荐路径。必须获得用户的明确批准（"yes" / 同意）才能进入下一步。
3. 若涉及 UI 流、架构或状态机，强制使用 **Mermaid diagram** (ASCII/Mermaid) 进行“所见即结构”的展示。

### Phase 4: Specification & Writeback (定稿与物理落盘) [Mode: EXECUTION]
1. 将经过验证的设计写入 `plans/design-<topic>.md` 或同级规划文档。
**Template Structure:**
```markdown
# Design: [Title]
**Date:** [YYYY-MM-DD] | **Mode:** [Startup/Builder/Feature]

## Problem Statement & Context
[Synthesized from Brain Dump]

## Core Insights / Premises
[Answers to forcing questions or structural trade-offs]

## Recommended Approach
[The approved architecture or product wedge]

## Visual Flow
[Mermaid diagram if applicable]

## Next Steps
[Concrete implementation tasks]
```
2. **自愈审计**: 检查 TODO、逻辑矛盾。
3. 提示用户路径，请求确认。确认后方可结束技能。

---

## 3. Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`。
- JSON 结构：`{"skill_name": "ideation-brainstorming", "status": "success", "mode": "[Startup/Builder/Feature]"}`

## 4. 历史失效先验 (NLAH Gotchas)
- `IF [Phase == 4] THEN [Halt if Action == "Write Code"] AND [Require a concrete design document first]`
- `IF [Topic == "Architecture Design"] THEN [Halt if Format == "Plain Text"] AND [Require Format IN ("ASCII", "Mermaid")]`
- `IF [Report contains placeholder markers] THEN [Halt and repair before delivery]`
- `IF [Task contains multiple complex features] THEN [Require execute("Decomposition") before proceeding]`
