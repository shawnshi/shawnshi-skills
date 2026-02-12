# web-design-guidelines
<!-- Input: UI Code files (.tsx, .vue, .html), specific patterns. -->
<!-- Output: Compliance findings (file:line), improvement suggestions. -->
<!-- Pos: Audit/Quality Layer (Compliance Auditor). -->
<!-- Maintenance Protocol: Fetch fresh rules from Vercel source before each audit. -->

## 核心功能
Web 界面规范合规性审计引擎。基于 Vercel 实验室的动态规则库，对 UI 代码进行可访问性 (A11y)、交互逻辑与视觉一致性的深度扫描。

## 战略契约
1. **动态同步**: 审计前必须执行 WebFetch 获取最新的 `command.md` 规则，确保审计标准与全球最佳实践同步。
2. **精准定位**: 发现的问题必须以 `file:line` 格式输出，并附带明确的修正建议（如：ARIA 缺失、对比度不足）。
3. **反馈驱动**: 审计结果应直接作为 `ui-ux-pro-max` 的输入，引导自动化的 UI 修复流程。
