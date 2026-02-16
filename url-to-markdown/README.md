# Web Content Miner: 高保真语义矿工

<!-- 
@Input: Targeted URLs, Login States, Rendering Constraints
@Output: Clean Markdown (Layout Preserved), High-Fidelity DOM Snapshots
@Pos: [ACE Layer: Perception/Input] | [MSL Segment: Web Ingestion]
@Maintenance: Update CDP driver & ad-filtering rules.
@Axioms: Rendering First | Noise Filtering | Semantic Ingestion
-->

> **核心内核**：穿透网页噪音。基于 CDP 协议抓取深度渲染内容，将杂乱的 Web 数据转化为高纯度的语义资产。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 网页语义提取引擎，负责处理 JS 渲染、懒加载等复杂动态环境下的内容捕获。
- **反向定义**: 它不是一个简单的 HTML 下载器，而是一个具备渲染感知能力的挖掘机。
- **费曼比喻**: 它不仅把网页“拍照”存下来，还能识别出哪些是正文、哪些是干扰项，最后给你一份像笔记本一样干净的纯文字版。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“Web 文档结构”、“渲染状态”、“身份认证会话”等实体。
- **ACE 角色**: 作为系统的 **Input Sensor (输入感知器)**。

## 2. 逻辑机制 (Mechanism)
- [CDP Navigation] -> [DOM Rendering] -> [Heuristic Cleaning] -> [Markdown Conversion]

## 3. 策略协议 (Strategic Protocols)
- **渲染优先**：严禁直接抓取源码，必须通过 Chrome CDP 确保执行所有 JavaScript 后的真实状态。
- **智能去噪**：自动识别并剔除导航栏、侧边栏与广告，确保下游分析的上下文纯净。
