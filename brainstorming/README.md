# Brainstorming: 技术实施前的“架构防火墙”

<!-- 
@Input: Abstract Ideas, Project Constraints, Project Structure
@Output: Structured Design Docs (Markdown), Trade-off Analysis
@Pos: [ACE Layer: Coordinator] | [MSL Segment: Design Engineering]
@Maintenance: Review design patterns & framework compatibility.
@Axioms: Ask before Act | Trade-off First | YAGNI (You Ain't Gonna Need It)
-->

> **核心内核**：基于第一性原理，对所有项目想法进行硬性准入审查，通过强制性权衡分析杜绝盲目编码。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 规划层过滤器，负责将模糊的需求转化为清晰、鲁棒的工程设计规范。
- **反向定义**: 它不是一个简单的头脑风暴工具，而是一个设计验证引擎。
- **费曼比喻**: 就像是在动工盖房子前，建筑师和结构工程师进行的最后一次图纸审核，在这个阶段改错最便宜。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 负责处理“设计模式”、“约束条件”、“架构方案”等实体。
- **ACE 角色**: 扮演 **Coordinator (协调者)**，在开发前对齐所有意图。

## 2. 逻辑机制 (Mechanism)
- [Clarification Loop] -> [Framework Application] -> [Option Generation] -> [Design Synthesis] -> [Handoff]

## 3. 策略协议 (Strategic Protocols)
- **强制权衡矩阵**：必须提供至少 2 种备选路径，并基于成本、复杂度进行量化的 Trade-off 分析。
- **YAGNI Check**：无情地剔除任何未被证明必要的非核心功能。
