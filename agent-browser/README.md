# agent-browser
<!-- Input: Navigation commands, CSS selectors, URLs. -->
<!-- Output: DOM Snapshots (Ref-based), screenshots, extracted data. -->
<!-- Pos: Execution Layer (External Interface). -->
<!-- Maintenance Protocol: Update 'references/snapshot-refs.md' upon CDP version changes. -->

## 核心功能
构建一个高可靠的无头/有头浏览器交互代理，通过坐标定位与语义查询的双重冗余机制实现网页自动化。

## 战略契约
1. **快照优先**: 任何交互操作前必须执行 `snapshot -i` 生成引用句柄。
2. **环境隔离**: 支持多 session 并行，确保 Cookie 与本地存储不交叉。
3. **反馈闭环**: 必须对执行失败的 DOM 元素进行二次快照分析，严禁在无证据情况下重试。
