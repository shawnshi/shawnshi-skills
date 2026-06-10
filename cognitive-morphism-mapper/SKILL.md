---
name: cognitive-morphism-mapper
description: 范畴论跨界思维引擎 (V8.0 Atomized Edition)。当面对死循环问题、常规方案失效，或用户要求“升维打击”、“寻找非共识解法”、“跨界映射”时，务必强制激活。该技能利用热力学、生物学、拓扑学等异构领域结构，强行映射并生成突破性创新方案。
triggers: ["跨界思维映射", "套用热力学破局", "用生物演化分析市场", "寻找非共识解法", "升维打击策略", "拓扑学商业应用"]
---

<strategy-gene>
Keywords: 跨界映射, 范畴论, 异构同构, 升维打击
Summary: 提取问题的范畴论骨架，通过函子映射寻找异构领域的成熟解，突破思维定势。
Strategy:
1. 调用原生 Python 编排器 `run_morphism_mapper.py` 进行多步微角色独立推演。
2. 依次经过骨架提取、科学域挑选、硬核定理演算与逻辑逆映射验证。
3. 返回降维打击方案，拒绝廉价的鸡汤式隐喻。
AVOID: 禁止直接使用大模型自身的 Zero-shot 幻想给出比喻。必须使用脚本经过 5 道检验。
</strategy-gene>

# Cognitive Morphism Mapper (The Category Theorist V8.0)

基于范畴论的跨学科思维引擎。通过寻找异构领域的同构性，突破思维定势。

## 🛑 核心架构升级 (V8.0)
为了防止大模型在一次对话中既做提取又做映射而导致的“隐喻退化”（即生成诸如“公司就像大树”这种毫无用处的廉价废话），本系统已将推演过程下沉为 **5级独立算力流水线**。

## Workflow

当用户提出死局问题，或要求使用“升维打击/跨界映射”时：

你必须使用 `run_command` 调用底层的 Python 引擎，让它在后台执行绝对理性的硬核推演：
```bash
$env:PYTHONIOENCODING="utf-8"; python "C:\Users\shich\.gemini\config\skills\cognitive-morphism-mapper\scripts\run_morphism_mapper.py" --problem "用户的具体问题或商业死局"
```
*如果用户指定了某个科学领域（如热力学），可附加 `--domain "热力学"` 参数。*

### 后台执行管线揭秘 (The Engine)
脚本将会在内存中依次拉起：
1. **`Skeleton_Extractor` (范畴论学者)**：剥离商业表象，只留 Object 与 Morphism。
2. **`Domain_Selector` (科学博学家)**：将该拓扑结构扔进硬核物理/生物学中寻找同构域。
3. **`Theorem_Prover` (理论物理学家)**：直接套用目标域的硬核定理（如热力学第二定律、竞争排斥原理）进行推演。
4. **`Commutativity_Checker` (逻辑学家)**：验证映射回现实世界后的逻辑闭环（Commutativity Check）。
5. **`Strategic_Architect` (战略架构师)**：输出最终的升维打击方案。

### 读取产物 (Archiving)
脚本运行完毕后，在临时目录读取输出的 Markdown 产物，将其核心结论（The Structural Trap, The Isomorphic Mapping, The Non-Consensus Solution）呈现给用户。

## Knowledge Management
*   **List**: `python scripts/domain_manager.py list`
*   **Add**: `python scripts/domain_manager.py add "[Name]"`
