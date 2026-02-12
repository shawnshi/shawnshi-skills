# url-to-markdown
<!-- Input: URLs (Public or Login-gated), capture specs. -->
<!-- Output: High-fidelity Markdown content. -->
<!-- Pos: Data Ingestion Layer (Web Content Miner). -->
<!-- Maintenance Protocol: Update 'main.ts' if Chrome CDP protocols change. -->

## 核心功能
高保真网页内容矿工。通过 Chrome DevTools Protocol (CDP) 捕获完整渲染后的 DOM，支持懒加载内容提取及登录后页面的交互式抓取。

## 战略契约
1. **高保真还原**: 转换过程必须剔除导航、广告等视觉噪音，同时完整保留表格、数学公式与多级列表。
2. **会话持久化**: 处理私有页面时必须启用 `--wait` 模式，确保在手动完成身份验证后执行语义提取。
3. **本地化存档**: 默认输出为 Markdown，且关键图片需支持本地化存储或 Base64 嵌入以防止链接失效。
