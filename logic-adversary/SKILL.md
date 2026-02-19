---
name: logic-adversary
description: 军工级逻辑对抗系统。集成多维专家博弈（共识模式）与饱和逻辑攻击（攻击模式），旨在通过智力摩擦识别并消除决策盲区。
language: py
---

# SKILL.md: Logic Adversary V3.1 (逻辑对抗与博弈系统)

> **Version**: 3.1 (Strategic War Room Edition) | **Last Updated**: 2026-02-19
> **Vision**: 将脆弱的假设锻造成鲁棒的战略。拒绝平庸的附和，追求极致的智力摩擦。

## 1. 触发逻辑 (Trigger)
- 当用户要求“审核方案”、“评估决策”、“寻找逻辑漏洞”、“模拟专家辩论”或“发起红队攻击”时激活。

## 2. 核心作战模式 (Modes)
- **共识模式 (Consensus Mode)**: Council 逻辑，侧重于多代理协同对抗，通过 3 轮辩论寻找异质专家间的“局部最优解”。
- **攻击模式 (Attack Mode)**: RedTeam 逻辑，侧重于单向饱和攻击，部署 32 名代理从各维度彻底摧毁脆弱假设。

## 3. 核心 SOP (The War Room Protocol)

### 第零阶段：威胁假设 (Threat Hypothesis Phase)
1. **任务**：在正式攻击前，基于 `memory.md`（项目背景）生成 **Initial Vulnerability Hypothesis (IVH)**。
2. **要求**：列出该方案最可能导致失败的 3 个“致命单点”(SPOF)。

### 第一阶段：议题原子化 (Decomposition)
1. **拆解**：将待审方案拆解为原子化断言（Assertions）。
2. **逻辑链映射**：标注断言间的依赖关系，识别出逻辑上的“承重墙”。

### 第二阶段：部署与博弈 (Engagement)
1. **模式选择**：
   - 需寻找鲁棒解 -> 启动 `Consensus` 流程。
   - 需压力测试 -> 启动 `Attack` 流程。
2. **代理唤醒**：从 `references/agents.md` 中调用特种代理。
3. **证据织网 (Evidence-Mesh)**：强制要求代理在质疑时引用 `references/philosophy.md` 中的公理或外部事实，严禁空对空辩论。

### 第三阶段：综合与重构 (Synthesis & Reconstruction)
1. **冲突存证**：记录所有无法达成共识的尖锐分歧点。
2. **博弈解析 (NEW)**：执行 `python scripts/game_resolver.py debate_results.json`，计算各选项的“稳定性得分”，确定纳什均衡解。
3. **钢人策略 (Steelmen)**：系统必须尝试为最脆弱的论点构建一个在逻辑上更强大的防御性版本。

### 第四阶段：战略判词 (The Verdict)
1. **输出结构**：
    - **核心漏洞库 (The Vulnerability Vault)**: 按风险等级（High/Med/Low）排列。
    - **钢人建议 (Steelmen Recommendations)**: 如何修补逻辑。
    - **风险减缓矩阵 (Risk Mitigation Matrix)**: 具体的防御行动建议。

### 第五阶段：闭环审计 (Closure)
1. **任务**：将审计发现的盲点增量同步至 `memory.md` 中的 `Lessons Learned`。

## 4. 核心约束 (Iron Rules)
- **禁止谄媚**：代理严禁赞美方案，必须保持“手术刀式”的冷峻。
- **防止自动化偏见**：对于高度一致的结论，必须强制引入一个“魔鬼代言人 (Devil's Advocate)”进行反向攻击。
- **逻辑脱水**：输出严禁使用形容词，必须基于因果逻辑。

## 5. 资源库 (War Room Assets)
- **专家库**: `references/agents.md`.
- **对抗公理**: `references/philosophy.md`.
- **流程规范**: `Workflows/`.
