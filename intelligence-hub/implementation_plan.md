# 今日情报战役实施纲领 (Implementation Plan)

> **Date**: 2026-03-18
> **Status**: Waiting for Approval

## 1. 核心任务目标 (Tactical Goals)
- **扫描**: 识别医疗 IT 行业（特别是 Winning Health）关于“代码液态化”与“语义资产化”的最新共识或异动。
- **研判**: 评估当前全球范围（如 AMI Labs）在临床逻辑审计与 Evidence-Mesh 方面的落地实践。
- **对齐**: 确保情报简报内容与 `memory.md` 中的“算力主权物理化”及“代理式经济”战略高度对齐。

## 2. 扫描矩阵规划 (Scanning Matrix)
| 领域 | 核心关键词 | 优先级 |
| :--- | :--- | :--- |
| **Agentic Economy** | ACE, Agentic Workflow, MCP Protocol, Logic Lake | 高 |
| **Medical MSL 2.0** | WiNEX, MSL, FHIR, Semantic Hard-Locking | 高 |
| **Sovereign Compute** | 本地算力, Lobster, MicroVM, Sovereign AI | 中 |
| **Healthcare Policy** | 电子病历分级, 医保支付, 临床推理审计 | 中 |

## 3. 工具链与资源调度
- **采集引擎**: `scripts/fetch_news.py` (配置并发抓取)。
- **精炼引擎**: `scripts/refine.py` (启用 MSL 2.0 专用精炼 Prompt)。
- **验证手段**: `google_web_search` (针对 L4 情报执行 Grounding 校验)。

## 4. 关键成果 (Deliverables)
- `intelligence_[YYYYMMDD]_briefing.md` (中文战略简报)。
- 追加写入 `MEMORY.md` 的增量认知资产。

---
*Mentat Intelligence Hub (V5.0)*
