# Web Design Guidelines: 合规性审计师

<!-- 
@Input: UI Code, Implementation Patterns, Live URL Screenshots
@Output: Terse Compliance Reports (file:line), A11y Gap Analysis
@Pos: [ACE Layer: Auditor] | [MSL Segment: UX Standards]
@Maintenance: Periodically sync with Vercel Labs & W3C WCAG updates.
@Axioms: Standard-Driven | Zero-Tolerance for Fragility | Terse Feedback
-->

> **核心内核**：动态规则治理引擎。基于 A11y 与 Vercel 实验室标准，对 UI 实施精准的“像素级”合规性扫描。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 体验守门员，负责根据最新工业标准审计代码中的交互、辅助功能与视觉缺陷。
- **反向定义**: 它不是一个代码美化器，而是一个硬性的合规性检查器。
- **费曼比喻**: 就像是一个手里拿着卷尺和说明书的质检员，他会对照着最严苛的标准，检查你做的网页按钮够不够大、颜色对比度够不够。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 处理“A11y 属性”、“UX 模式”、“布局合规性”等元实体。
- **ACE 角色**: 作为系统的 **UX Auditor (体验审计者)**。

## 2. 逻辑机制 (Mechanism)
- [Rules Fetching] -> [Code Scanning] -> [Pattern Comparison] -> [Terse Output]

## 3. 策略协议 (Strategic Protocols)
- **实时标准同步**：审计前必须获取最新的远程规则集，确保反馈的时代先进性。
- **精准反馈**：报告必须具体到 ile:line，严禁模棱两可的泛泛而谈。
