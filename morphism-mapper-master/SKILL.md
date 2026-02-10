---
name: morphism-mapper
description: Category Theory Morphism Mapper v2.6 - 将问题结构映射到异构领域（如热力学、生物学），生成非共识创新方案。
---

# Morphism Mapper (The Category Theorist)

基于范畴论的跨学科思维引擎。通过寻找异构领域的同构性，突破思维定势。

## Core Workflow

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

## Commands

### Problem Solving
*   **Auto**: 直接描述问题，Agent 自动执行 Phase 1-4。
*   **Manual**: `/morphism-map [Domain]` 强制映射。

### Knowledge Management
*   **List**: `python scripts/domain_manager.py list`
*   **Add**: `python scripts/domain_manager.py add "[Name]"`

## Advanced Modules
当遇到特殊情况时，挂载以下模块（详见 `references/modules.md`）：
*   **信息模糊** -> `yoneda_probe`
*   **环境巨变** -> `natural_transformation`
*   **风险评估** -> `monad_risk`

## Resources
*   **执行协议**: `references/protocols.md`
*   **高级模块**: `references/modules.md`

!!! Maintenance Protocol: 新增领域必须符合 V2 标准（100基石）。
