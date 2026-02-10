---
name: news-aggregator-skill
description: "Comprehensive news aggregator that fetches, filters, and deeply analyzes real-time content from 8 sources (HN, GitHub, 36Kr, etc.). Use for daily scans and trend analysis."
---

# News Aggregator (The Intelligence Hub)

实时监测全球科技、金融与社会动态，产出具备“二阶洞察”的战略情报。

## Core Capabilities
*   **Multi-Source Fetch**: 覆盖 Hacker News, GitHub Trending, Weibo, 36Kr, WallStreetCN, V2EX 等。
*   **Deep Extraction**: 使用 `--deep` 模式提取正文，支持全文语义分析。
*   **Smart Filtering**: 自动扩展关键词（如：AI -> LLM, RAG, Agent）。

## Workflow SOP

### 1. Global Scan (全域扫描)
当用户要求“看看有什么大事”时：
```bash
python scripts/fetch_news.py --source all --limit 15 --deep
```
*   **Protocol**: 必须按照 `references/responses.md` 格式进行二阶深度解析。

### 2. Targeted Intelligence (定向情报)
当用户关注特定主题（如 DeepSeek）：
```bash
python scripts/fetch_news.py --source all --keyword "DeepSeek" --deep
```

### 3. Interactive Menu
当用户输入“如意如意”时，读取 `references/menu.md` 并展示导航。

## Artifacts
*   **Reports**: 所有的完整报告必须存档至 `reports/` 目录。

## Best Practices
1.  **Markdown Links**: 所有的标题必须带上原文链接。
2.  **Time Filling**: 若用户指定时间窗口内结果太少，需引入“补充高热度新闻”并明确标注。
3.  **Synthesis**: 在末尾提供 2-3 句话的跨领域趋势总结。

## Resources
*   **输出规范**: `references/responses.md`
*   **快捷菜单**: `references/menu.md`

!!! Maintenance Protocol: 若采集源失败（403/404），请在报告中记录状态并建议后续手动检查。
