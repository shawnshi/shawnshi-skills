# NotebookLM Master: 主权知识挂载点

<!-- 
@Input: Private Document Library (PDF/MD/Text), User Queries
@Output: Source-Grounded Answers, Evidence-Supported Insights
@Pos: [ACE Layer: Perception/Grounding] | [MSL Segment: Private Knowledge Base]
@Maintenance: Keep Google login state active & sync notebook metadata.
@Axioms: Anti-Hallucination | Source-Grounded Only | Library Governance
-->

> **核心内核**：物理隔离幻觉的知识堡垒。基于 Google NotebookLM 实现自有文档库的深度问答，确保所有输出具备证据支撑。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 主权知识检索器，负责将私有知识资产转化为实时可调用的证据网。
- **反向定义**: 它不是一个生成模型，而是一个基于既有文档的“事实提取机”。
- **费曼比喻**: 它就像是一个记忆力超群的图书管理员，他只根据书架上（你的文档）有的内容回答问题，绝不胡编乱造。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 管理“私有事实”、“文献证据”、“知识实体”等底层真实性实体。
- **ACE 角色**: 作为 **Knowledge Sensor (知识感知器)**，为推理引擎提供确定性的事实约束。

## 2. 逻辑机制 (Mechanism)
- [Auth Setup] -> [Library Discovery] -> [Grounded Querying] -> [Evidence Mapping]

## 3. 策略协议 (Strategic Protocols)
- **证据锚定**：严禁引入库外非验证信息；所有回答必须指向库内特定页码或段落。
- **闭环追问**：信息不足时严禁盲目猜测，必须立即发起补充追问以完善证据链。
