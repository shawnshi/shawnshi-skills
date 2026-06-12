---
name: cognitive-morphism-mapper
version: 8.1.0
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

# Cognitive Morphism Mapper (范畴论跨界引擎 V8.1 Native)

基于范畴论的跨学科思维引擎。通过寻找异构领域的同构性，突破思维定势。目标是输出可检验的结构映射，而不是只给灵感型比喻。

## 1. 核心流程与架构 (The Protocol)

### Phase 1: Extract (骨架提取) [Mode: PLANNING]
主代理分析用户输入，剥离表层业务语义，提取底层的 Objects (实体) 和 Morphisms (关系)，建立问题的初始拓扑图。

### Phase 2: Select (领域选择) [Mode: PLANNING]
主代理在 `references/` 中寻找结构相似但语义距离极远的 Domain B。
- **Built-in**: 内置物理、生物、复杂系统等 27+ 领域。
- **Knowledge Management**: 若需扩展或查询领域库，主代理应使用原生的 `run_command` 工具执行以下命令：
  - 查询：`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper\scripts\domain_manager.py" list`
  - 新增：`$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper\scripts\domain_manager.py" add "[Name]"`

### Phase 3: Map (函子映射) [Mode: EXECUTION]
建立映射关系 $F: A \to B$，引用 Domain B 中的成熟定理与运转机制。当遇到特殊情况时，主代理须自主挂载高级模块（详见 `references/modules.md`）：
- **信息模糊** -> `yoneda_probe`
- **环境巨变** -> `natural_transformation`
- **风险评估** -> `monad_risk`

### Phase 4: Synthesize (合成提案) [Mode: EXECUTION]
将 Domain B 的解法定理逆映射回源域 A，并通过 **Commutativity Check** (逻辑验算) 确保映射在物理与商业现实中均可行。

## 2. <Contracts> (输出与交付契约)
- **交付门槛**：最终输出至少包含：源域问题骨架、目标域映射、关键定理/机制、逆映射后的可执行方案，以及一次完整的 `Commutativity Check`。若使用了高级模块，必须说明触发条件与其对主方案的具体修正。
- **Telemetry 记录**: 任务执行完成后，必须使用原生的 `write_to_file` 工具将本次执行的元数据以 JSON 格式绝对物理落盘至：
  `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`
  JSON 结构示例：`{"skill_name": "cognitive-morphism-mapper", "status": "success", "duration_sec": 0, "input_tokens": 0, "output_tokens": 0}`

## 3. <Failure_Taxonomy> (失败分类学)
- **隐喻陷阱 (Metaphor Fallacy)**：严禁在信息不充分时，将感性的修辞隐喻直接等同于逻辑结论。映射必须具备结构上的同构性（Isomorphism）。
- **劣质领域扩张 (Garbage Domain)**：如果执行 `domain_manager.py add` 新增领域，该领域必须符合内置的 V2 标准（拥有至少 100 块可验证的基石定理），严禁添加入伪科学或结构松散的领域。
- **路径与编码崩溃 (Execution Deadlock)**：调用本地 Python 脚本管理领域时，严禁使用相对路径，必须使用写死的 `C:\Users\shich\.gemini\config\...` 绝对地址，并强制附加 `$env:PYTHONIOENCODING="utf-8"`。
- **假工具幻觉**：保存日志必须使用原生的 `write_to_file`，执行命令必须使用 `run_command`。
