# _DIR_META.md - Logic Adversary

## 1. Vision (架构愿景)
本目录作为系统级的"智力摩擦中枢"，通过模拟多维专家博弈与饱和红队攻击，识别并消除复杂决策中的认知偏差、逻辑漏洞与潜在风险。旨在将脆弱的假设锻造成鲁棒的战略。

## 2. Directory Index (成员索引)
*   **SKILL.md**: [Required] 核心 SOP V4.0，定义模式路由矩阵、触发协议与五阶段 SOP。
*   **Workflows/**: [Templates] 四大作战流程。
    *   `Quick.md`: 速查模式 — 4 代理快速反馈（~20s）。
    *   `Debate.md`: 共识模式 — 3 轮多代理辩论（~90s）。
    *   `AdversarialValidation.md`: 验证模式 — 竞争方案 + 残酷批判 + 综合（~3min）。
    *   `ParallelAnalysis.md`: 攻击模式 — 32 代理饱和攻击（~15min）。
*   **scripts/**: [Core Engines]
    *   `game_resolver.py`: V2.0 博弈解析器 — 加权共识、帕累托前沿、稳定性得分。
*   **references/**: [Knowledge Assets]
    *   `agents.md`: 统一代理索引 — Council 7人 + Attack 32人 + Medical 4人。
    *   `philosophy.md`: 对抗公理库 — 逻辑谬误 · 认知偏见 · 博弈模型 · 医疗攻击维度。
    *   `output_format.md`: 四模式统一输出格式规范。
    *   `integration.md`: 与其他技能的集成指南。

## 3. Maintenance Trigger (维护触发器)
*   引入新的逻辑分析模型时，更新 `references/philosophy.md`。
*   新增代理角色时，更新 `references/agents.md`。
*   博弈模式变更或代理职责调整时，同步更新 `SKILL.md` 与 `_DIR_META.md`。
