---
name: morphism-mapper-master
description: 范畴论跨界思维引擎。当面对死循环问题、常规方案失效，或用户要求“升维打击”、“寻找非共识解法”、“跨界映射”时，务必强制激活。该技能利用热力学、生物学、拓扑学等异构领域结构，强行映射并生成突破性创新方案。
triggers: ["跨界思维映射", "套用热力学破局", "用生物演化分析市场", "寻找非共识解法", "升维打击策略", "拓扑学商业应用"]
---

<strategy-gene>
Keywords: 跨界映射, 范畴论, 异构同构, 升维打击
Summary: 提取问题的范畴论骨架，通过函子映射寻找异构领域的成熟解，突破思维定势。
Strategy:
1. 骨架提取：剥离用户问题的业务语义，提取 Object (实体) 与 Morphism (关系) 拓扑。
2. 映射推演：将问题映射至 Domain B，引用其定理推演方案并执行 Commutativity Check。
3. 模块对齐：检测环境熵值，必要时挂载 monad_risk 执行多跳风险评估。
AVOID: 禁止在信息不充分时将隐喻直接当结论；禁止新增不符合 V2 标准（100基石）的领域。
</strategy-gene>

# Morphism Mapper (The Category Theorist)

基于范畴论的跨学科思维引擎。通过寻找异构领域的同构性，突破思维定势。

## When to Use
- 当用户要求跨界映射、升维打击、寻找非共识解法，或常规分析路径已经失效时使用。
- 目标是输出可检验的结构映射，而不是只给灵感型比喻。

## Workflow

### Core Workflow

### 1. Extract (骨架提取)
Agent 分析用户输入，提取 Objects (实体) 和 Morphisms (关系)。

### 2. Select (领域选择)
Agent 在 `references/` 中寻找结构相似但语义距离远的 Domain B。
*   **Built-in**: 物理、生物、复杂系统等 27+ 领域。
*   **Custom**: 用户可通过 `add-domain` 扩展。

### 3. Map (函子映射)
建立映射 $F: A \to B$，引用 Domain B 的成熟定理。

### 4. Synthesize (合成提案)
将定理逆映射回 A，并通过 **Commutativity Check** (逻辑验算) 确保方案可行。

### Commands

### Problem Solving
*   **Auto**: 直接描述问题，Agent 自动执行 Phase 1-4。
*   **Manual**: `/morphism-map [Domain]` 强制映射。

### Knowledge Management
*   **List**: `python scripts/domain_manager.py list`
*   **Add**: `python scripts/domain_manager.py add "[Name]"`

### Advanced Modules
当遇到特殊情况时，挂载以下模块（详见 `references/modules.md`）：
*   **信息模糊** -> `yoneda_probe`
*   **环境巨变** -> `natural_transformation`
*   **风险评估** -> `monad_risk`

## Resources
*   **执行协议**: `references/protocols.md`
*   **高级模块**: `references/modules.md`
*   **领域管理脚本**: `scripts/domain_manager.py`

## Failure Modes
- 新增领域必须符合 V2 标准（100 基石）。
- 在信息不充分时必须显式说明映射假设，不能把隐喻直接当结论。
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]

## Output Contract
- 最终输出至少包含：源域问题骨架、目标域映射、关键定理/机制、逆映射后的方案，以及一次 `Commutativity Check`。
- 若使用高级模块，必须说明触发条件与其对主方案的具体修正。

## Telemetry
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "morphism-mapper-master", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`
