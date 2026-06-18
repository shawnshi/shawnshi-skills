---
name: cognitive-morphism-mapper
version: 9.0.0
tier: action-allowed
description: '范畴论跨界思维引擎。利用热力学/生物学等异构结构映射生成破局方案。禁止将感性隐喻直接等同于逻辑结论，禁止添加缺乏基石定理的劣质领域。'
triggers: ["跨界思维映射", "套用热力学破局", "用生物演化分析市场", "寻找非共识解法", "升维打击策略", "拓扑学商业应用"]
---

<strategy-gene>
Keywords: 跨界映射, 范畴论, 异构同构, 升维打击
Summary: 提取问题的范畴论骨架，通过函子映射寻找异构领域的成熟解，突破思维定势。
Strategy:
1. 骨架提取：剥离业务语义，提取 Object (实体) 与 Morphism (关系) 拓扑。
2. 映射推演：映射至 Domain B，引用定理推演方案并执行 Commutativity Check。
3. 模块对齐：检测环境熵值，必要时挂载 monad_risk 评估风险。
AVOID: 将隐喻直接当结论；新增缺乏基石验证的劣质领域。
</strategy-gene>

# Cognitive Morphism Mapper (范畴论跨界引擎 V9.0)

基于范畴论的跨学科思维引擎。通过寻找异构领域的同构性，突破思维定势。目标是输出可检验的结构映射，而不是只给灵感型比喻。

## Tool Trajectory
**[IN_ORDER]** 执行需遵循以下轨迹流：
1. `run_command` (如有需要，调用 Python 脚本操作 Domain B 库)
2. `write_to_file` (输出包含 Commutativity Check 的最终跨界方案落地)

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Extract (骨架提取)
主代理分析用户输入，剥离表层业务语义，提取底层的 Objects (实体) 和 Morphisms (关系)，建立问题的初始拓扑图。

### Phase 2: Select (领域选择)
主代理在 `references/` 中寻找结构相似但语义距离极远的 Domain B。
- **Built-in**: 内置物理、生物、复杂系统等 27+ 领域。
- **Knowledge Management**: 若需扩展或查询领域库，主代理应使用 `run_command` 执行：
  - 查询：`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper\scripts\domain_manager.py" list`
  - 新增：`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper\scripts\domain_manager.py" add "[Name]"`

### Phase 3: Map (函子映射)
建立映射关系 $F: A \to B$，引用 Domain B 中的成熟定理与运转机制。当遇到特殊情况时，主代理自主挂载高级模块：
- **信息模糊** -> `yoneda_probe`
- **环境巨变** -> `natural_transformation`
- **风险评估** -> `monad_risk`

### Phase 4: Synthesize (合成提案)
将 Domain B 的解法定理逆映射回源域 A，并通过 **Commutativity Check** (逻辑验算) 确保映射在物理与商业现实中均可行。

## 2. <Contracts> (输出与交付契约)
- **交付门槛**：最终输出至少包含：源域问题骨架、目标域映射、关键定理/机制、逆映射后的可执行方案，以及完整的 `Commutativity Check`。
- **Telemetry 记录**: 任务执行完成后，使用 `write_to_file` 将元数据以 JSON 格式落地：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`

## 3. <Failure_Taxonomy> (失败分类学)
- **隐喻陷阱 (Metaphor Fallacy)**：在信息不充分时，将感性的修辞隐喻直接等同于逻辑结论。未执行同构性检验。
- **劣质领域扩张 (Garbage Domain)**：执行 `domain_manager.py add` 新增伪科学或结构松散的领域（不符合 100 块基石定理的标准）。
- **路径崩溃 (Execution Deadlock)**：调用本地 Python 脚本未附加 UTF-8 环境变量或使用相对路径。
- **假工具幻觉**：保存日志未使用 `write_to_file`，执行命令未使用 `run_command`。
