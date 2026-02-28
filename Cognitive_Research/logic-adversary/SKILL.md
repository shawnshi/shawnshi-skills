```
---
name: logic-adversary
description: 军工级逻辑对抗系统。集成多维专家博弈（共识模式）与饱和逻辑攻击（攻击模式），旨在通过智力摩擦识别并消除决策盲区。
language: py
---

# SKILL.md: Logic Adversary V4.0 (逻辑对抗与博弈系统)

> **Version**: 4.0 (Unified Command Edition) | **Last Updated**: 2026-02-21
> **Vision**: 将脆弱的假设锻造成鲁棒的战略。拒绝平庸的附和，追求极致的智力摩擦。

## 1. 触发逻辑 (Trigger)
- 当用户要求"审核方案"、"评估决策"、"寻找逻辑漏洞"、"模拟专家辩论"、"发起红队攻击"或"压力测试"时激活。

## 2. 模式路由矩阵 (Mode Router)

根据用户意图，选择最匹配的作战模式：

| 用户意图 | 推荐模式 | Workflow | 代理规模 | 耗时 |
|----------|---------|----------|---------|------|
| "快速看看这个方案有没有问题" | **Quick 速查** | `Workflows/Quick.md` | 4 代理 | ~20s |
| "帮我深入辩论这个决策" | **Consensus 共识** | `Workflows/Debate.md` | 4-7 代理 | ~90s |
| "帮我设计/选择最优方案" | **Validation 验证** | `Workflows/AdversarialValidation.md` | 3+1 代理 | ~3min |
| "红队攻击/彻底摧毁这个论点" | **Attack 攻击** | `Workflows/ParallelAnalysis.md` | 32 代理 | ~15min |

**模式选择决策树：**
```
用户需求
├─ 只需快速反馈？ → Quick 速查
├─ 需要多视角讨论？ → Consensus 共识
├─ 需要从多个方案中选最优？ → Validation 验证
└─ 需要极限压力测试？ → Attack 攻击
```

> [!TIP]
> 如不确定，先用 Quick 速查。若发现分歧严重，再升级至 Consensus 或 Attack。

## 3. 核心 SOP (The War Room Protocol)

### 第零阶段：威胁假设 (Threat Hypothesis)
1. 基于用户提供的背景，生成 **Initial Vulnerability Hypothesis (IVH)**。
2. 列出方案最可能导致失败的 3 个"致命单点" (SPOF)。
3. **选择作战模式** → 根据路由矩阵匹配 Workflow。

### 第一阶段：议题原子化 (Decomposition)
1. 将待审方案拆解为原子化断言 (Assertions)。
2. 标注断言间的依赖关系，识别逻辑上的"承重墙"。

### 第二阶段：部署与博弈 (Engagement)
1. 根据选定模式，执行对应 Workflow 文件中的完整流程。
2. 代理角色参见 `references/agents.md`（统一代理索引）。
3. **证据织网**：代理在质疑时须引用 `references/philosophy.md` 中的公理/谬误/偏见，严禁空对空辩论。

### 第三阶段：综合与重构 (Synthesis & Reconstruction)
1. **冲突存证**：记录所有无法达成共识的尖锐分歧点。
2. **博弈解析**（可选）：执行 `python scripts/game_resolver.py debate_results.json`，计算稳定性得分。
3. **钢人策略**：系统必须为最脆弱的论点构建一个在逻辑上更强大的防御性版本。

### 第四阶段：战略判词 (The Verdict)
输出结构须遵循 `references/output_format.md` 中的对应模式格式，核心包含：
- **核心漏洞库 (Vulnerability Vault)**: 按风险等级 (High/Med/Low) 排列。
- **钢人建议 (Steelmen Recommendations)**: 如何修补逻辑。
- **风险减缓矩阵 (Risk Mitigation Matrix)**: 具体的防御行动建议。

### 第五阶段：闭环审计 (Closure)
1. 将审计发现的盲点增量同步至项目上下文。

## 4. 核心约束 (Iron Rules)
- **禁止谄媚**：代理严禁赞美方案，必须保持"手术刀式"的冷峻。
- **防止自动化偏见**：对高度一致的结论，必须强制引入"魔鬼代言人 (Devil's Advocate)"。
- **逻辑脱水**：输出严禁使用形容词，必须基于因果逻辑。
- **证据织网**：所有质疑必须引用 `philosophy.md` 中的公理或外部事实。

## 5. 资源库 (War Room Assets)
- **统一代理索引**: [agents.md](file:///c:/Users/shich/.gemini/skills/logic-adversary/references/agents.md) — Council 角色 + 32 攻击代理
- **对抗公理库**: [philosophy.md](file:///c:/Users/shich/.gemini/skills/logic-adversary/references/philosophy.md) — 逻辑谬误 · 认知偏见 · 博弈模型
- **输出格式规范**: [output_format.md](file:///c:/Users/shich/.gemini/skills/logic-adversary/references/output_format.md)
- **集成指南**: [integration.md](file:///c:/Users/shich/.gemini/skills/logic-adversary/references/integration.md)
- **博弈解析器**: [game_resolver.py](file:///c:/Users/shich/.gemini/skills/logic-adversary/scripts/game_resolver.py)
- **作战流程**: `Workflows/` — Quick · Debate · AdversarialValidation · ParallelAnalysis
