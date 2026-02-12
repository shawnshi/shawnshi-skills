# tuanbiaodownloader
<!-- Input: TTBZ Path IDs or preview URLs. -->
<!-- Output: Consolidated PDF standards, download logs. -->
<!-- Pos: Data Acquisition Layer (Standards Intelligence). -->
<!-- Maintenance Protocol: Update 'downloader.py' if TTBZ anti-scraping logic evolves. -->

## 核心功能
高效的行业标准（团体标准）采集工具。支持从 ttbz.org.cn 自动解析 Path ID，并执行全自动的图片抓取、断点续传与 PDF 合并。

## 战略契约
1. **完整性闭环**: 下载完成后必须自动执行 `${document-summarizer}`，为标准文件生成初步的战略摘要。
2. **断点保障**: 脚本必须维护下载状态位，在网络波动后支持物理续传，杜绝重复抓取造成的 IP 封禁。
3. **合规引用**: 所有下载的标准必须记录原始 URL 与采集时间戳，确保文件的权威性。
