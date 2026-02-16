# Slide Deck: 叙事架构师

<!-- 
@Input: Structured Markdown, Style Templates, Rendering Models
@Output: Professional PPTX/PDF, Visual Prompts
@Pos: [ACE Layer: Output/Visual] | [MSL Segment: Visual Storytelling]
@Maintenance: Update visual-semantic mapping & style assets.
@Axioms: Semantic Mapping | Multi-Modal Rendering | Smart Resume
-->

> **核心内核**：将 Markdown 语义直接映射为具备商业穿透力的 PPTX/PDF。支持基于状态的“断点续传”渲染。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 幻灯片自动化编译引擎，负责将文本逻辑结构化并注入多模态视觉资产。
- **反向定义**: 它不是一个设计软件，而是一个逻辑到视觉的翻译机。
- **费曼比喻**: 就像是一个自动化的 PPT 制作机器人，你给他一份大纲，他就能自动找配图、排版并做成可以直接演示的文件。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“叙事大纲”、“视觉提示词”、“PPT 实体”等。
- **ACE 角色**: 作为 **Visual Worker (视觉执行者)**。

## 2. 逻辑机制 (Mechanism)
- [Semantic Analysis] -> [Outline Approval (HITL)] -> [Prompt Synthesis] -> [Visual Rendering] -> [Final Assembly]

## 3. 策略协议 (Strategic Protocols)
- **断点续传协议**：大规模渲染任务必须记录 status.json，支持失效后自动续传。
- **可编辑优先**：默认生成可编辑文本 Shape，严禁将所有文字硬编码进背景图。
