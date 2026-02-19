# _DIR_META.md - Logic Adversary

## 1. Vision (架构愿景)
本目录作为系统级的“智力摩擦中枢”，通过模拟多维专家博弈与饱和红队攻击，识别并消除复杂决策中的认知偏差、逻辑漏洞与潜在风险。旨在将脆弱的假设锻造成鲁棒的战略。

## 2. Directory Index (成员索引)
*   **SKILL.md**: [Required] 核心 SOP V3.1，定义博弈模式、触发协议与维护准则。
*   **Workflows/**: [Templates] 具体的对抗流程脚本。
    *   `ParallelAnalysis.md`: 饱和逻辑攻击路径。
    *   `Debate.md`: 多代理共识博弈框架。
    *   `AdversarialValidation.md`: 针对确定性断言的硬核验证。
*   **scripts/**: [Core Engines]
    *   `game_resolver.py`: [NEW] 智力博弈论解析器，用于计算多代理辩论后的“纳什均衡解”。
*   **references/**: [Knowledge Assets]
    *   `agents.md`: 专家代理的人格模板库。
    *   `philosophy.md`: 对抗公理（如：奥卡姆剃刀、逆火效应防御）。
    *   `output_format.md`: 审计报告的标准规格。
*   **agents/**: 环境配置文件。

## 3. Maintenance Trigger (维护触发器)
*   引入新的逻辑分析模型（如：博弈论模型）时，更新 `references/`。
*   博弈模式变更或代理职责调整时，同步更新 `SKILL.md` 与 `_DIR_META.md`。
