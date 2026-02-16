# Tuanbiao Downloader: 标准收割机

<!-- 
@Input: Tuanbiao IDs, Target Search Terms, URLs
@Output: Merged PDF Standard Documents, Download Logs
@Pos: [ACE Layer: Action/Input] | [MSL Segment: Regulatory Knowledge]
@Maintenance: Monitor target website DOM changes & PDF merge logic.
@Axioms: Batch Efficiency | Automated Merging | Compliance Ingestion
-->

> **核心内核**：行业标准自动化采集工具。解决碎片化获取痛点，实现从 Path 解析到 PDF 合并的完整链路。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 垂直领域文档采集器，专注于自动化下载并重组分布式的行业标准资产。
- **反向定义**: 它不是一个通用的下载器，而是一个针对特定合规文档库的“搬运工”。
- **费曼比喻**: 就像是一个专门收集各种“说明书”的小助手，你只要告诉他你需要哪个标准，他就能帮你找齐所有零散的页面并装订成册。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“行业标准实体”、“PDF 元数据”、“文档拓扑结构”。
- **ACE 角色**: 作为 **Specialized Scout (专项侦察员)**。

## 2. 逻辑机制 (Mechanism)
- [ID Extraction] -> [Batch Asset Fetching] -> [Image Processing] -> [PDF Synthesis]

## 3. 策略协议 (Strategic Protocols)
- **物理合并原子性**：下载过程必须包含自动合并逻辑，产出即是可用的完整 PDF，严禁交付碎片化图片。
- **失败重试闭环**：针对反爬导致的下载中断，必须执行分片级重试。
