---
name: news-aggregator-skill
description: "Comprehensive news aggregator that fetches, filters, and deeply analyzes real-time content from 8 sources (HN, GitHub, 36Kr, etc.). Use for daily scans and trend analysis."
---

# News Aggregator (The Intelligence Hub V3.0)

全球新闻情报枢纽。通过数据与推理分离架构，实现高信噪比的战略动态获取。

## 核心架构 (Native Processing Architecture)
1. **数据端 (Data Provider)**: `scripts/fetch_news.py` 负责高并发、鲁棒性的多源数据采集，输出标准 JSON 数据包。
2. **推理端 (Reasoning Engine)**: Agent 调用 **`thought-refiner`** 对采集到的数据进行“二阶洞察”分析。
3. **归档端 (Archive Protocol)**: Agent 调用 **`writing-assistant`** 生成 Markdown 报告并保存。

## 交互流程 (Intelligence Hub SOP)

### 1. 采集原始物料 (默认配置)
Agent 默认执行以下“四核驱动”命令（HN + GitHub + PH + V2EX）：
```bash
python scripts/fetch_news.py --source all --limit 10
```
*注：`all` 已在脚本层优化为包含上述核心源。*

### 2. 执行“二阶洞察”审计 (Agent 内置能力)
Agent 必须对照 `memory.md` 中的“年度战役”对采集到的物料进行审计，并**严格筛选出 10 条**最具战略价值的条目。

**审计维度**:
*   **MSL 对齐**: 医疗语义层、T2A、互操作性。
*   **ACE 协同**: 多智能体编排、Logic Lake、ACI。
*   **防御性 UX**: HITL 2.0、自动化偏见防御。

### 3. 生成并归档报告
Agent 按照 `references/responses.md` 格式生成 Markdown 报告，精选数量固定为 10 条。**每条精选必须包含约 100 字的深度中文摘要**，要求涵盖核心问题、技术方案/逻辑路径及最终结论，并**强制保存**至：
`C:\Users\shich\.gemini\memory\news\intelligence_$(date +%Y%m%d_%H%M).md`

---

## 脚本目录
* `scripts/fetch_news.py`: 核心采集引擎（支持随机 UA、自动重试、JSON 状态提取）。

## 存档协议
> ⚠️ **Protocol**: 严禁仅在终端输出。所有情报必须归档至 `C:\Users\shich\.gemini\memory\news\` 以构建个人“逻辑湖”。
