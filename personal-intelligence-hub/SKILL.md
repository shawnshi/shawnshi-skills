---
name: personal-intelligence-hub
description: 生成基线优先、跨技术与医疗数字化并带历史去重的日资讯简报；区别管理周刊、事件雷达和论文综述。正式简报自动保存，生产预览仍产生运行中间态。当用户要求生成当日资讯简报、基线优先日报或跨技术／医疗数字化速览时使用。
---

# 技术与医疗数字化资讯简报

## 适用边界与模式路由

1. **职责边界**：生成基线优先、跨技术与医疗数字化并带历史去重的日资讯简报。管理层周刊交 `hit-weekly-brief`，行业事件雷达交 `hit-industry-radar`，学术论文综述交 `hit-lectures-scout`。
2. **输出模式**：
   - `formal_briefing`（默认）：完整执行 `prepare -> supplement -> semantic-review -> red-team -> forge`，正式归档 JSON、Markdown 与提交回执。
   - `preview`（仅当用户明确要求预览/速览）：执行至校验渲染，调用 `preview` 输出而不写正式归档。
   - `diagnostic` / `evaluation`：调用 `status`、`resume` 或 `evaluate` 检查运行态与覆盖漏斗。
   - 正式日简报默认自动归档。若用户明确要求预览或不保存，则只在答复交付，不落盘报告。

## 核心配比与质量门禁

- **领域配比**：默认领域请求比例为技术 60%、医疗数字化 40%，按最大余额法取整（如 10 条为 6:4、7 条为 4:3、5 条为 3:2、3 条为 2:1）。仅当存在已审计 L4 或具一手证据及近期决策影响的 L3 重大资讯时，允许在 `max_ratio_shift=0.2` 内调比。不以弱信号补数。
- **日期与窗口**：默认 3 日窗口（`report_date-2` 至 `report_date`，`Asia/Shanghai`）。`published_at` 必须为窗口内已知 `YYYY-MM-DD` 日期（支持正文提取、已登记 RSS `pool-declared/1` 或 URL 路径 `url-path/1`）；`event_date` 不得晚于 `published_at`。
- **洞察深度（L3/L4）**：每条入选事件须具备 `fact -> connection -> deduction -> actionability` 完整推演链。L3/L4、重大资讯或近期决策影响条目需绑定 `claim_grounding`（支持设 `evidence_ref: "auto"` 由 `semantic_agent.py` 自动从已核验正文定位字符偏移与 SHA-256）。

## 自动化四阶段执行流（推荐结合 Pi `codemode` 批处理）

详细分阶段协议见 `references/workflow_protocols.md`（按阶段按需参阅 `baseline` 节、`supplement` 节、`semantic-review` 节、`red-team` 节、`archive` 节与 `runtime` 节）。

### Stage 1: 基线扫描与运行初始化（`baseline` 节）

```powershell
python -X utf8 scripts/run_daily.py prepare --report-date <YYYY-MM-DD> --timezone Asia/Shanghai --article-broker-version 3
```

初始化运行快照后，后续命令统一使用返回的冻结脚本入口 `<execution_cli_path>` 与同目录的 `supplement_agent.py`、`broker_helper.py`、`semantic_agent.py`。

### Stage 2: 补检车道核验与主动检索（`supplement` 节）

使用 Pi `codemode` 批量编排各缺口车道（`technology-supply`、`healthcare-digital-supply`、`policy-competition`、`risk-counterevidence`）：

1. **启动车道**：`supplement_agent.py broker-checkpoint --parent --request <supplement_request.json> --gap-id <gap_id>`
2. **核验绑定候选与检索发现**：
   - URL 核验：`broker_helper.py reserve-fetch` $\rightarrow$ `fetch_content(mode="readable")` $\rightarrow$ `broker_helper.py record-fetch`
   - 主动检索：`broker_helper.py reserve-query --provider <p>` $\rightarrow$ `web_search` $\rightarrow$ `broker_helper.py record-query --provider <p> --query-response <txt>`
3. **封存与收口**：
   - `supplement_agent.py broker-seal --parent --request <supplement_request.json> --gap-id <gap_id>`
   - `supplement_agent.py finalize --request <supplement_request.json> --gap-id <gap_id> --parent`
   - 汇总登记：`<execution_cli_path> finalize-supplement --manifest <run_manifest.json> --request <supplement_request.json> --draft <draft_1> ...`

### Stage 3: 语义精选与红队门禁（`semantic-review` 节 & `red-team` 节）

1. **生成语义请求并获取合格候选池**：
   ```powershell
   python -X utf8 <execution_cli_path> prepare-review --manifest <run_manifest.json> --kind semantic --max-turns 2
   python -X utf8 <run_scripts>/semantic_agent.py context --request <semantic_review_request.json>
   ```
2. **撰写语义精选草案并发布**：
   基于 `eligible_candidates` 撰写 `semantic_dynamic.draft.json`（含 `punchline`、`insights`、`digest`、`market`、`action_levers` 及 `selected_items`），执行：
   ```powershell
   python -X utf8 <run_scripts>/semantic_agent.py finalize --request <semantic_review_request.json>
   python -X utf8 <execution_cli_path> validate-semantic-draft --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json>
   ```
3. **红队审查与登记**：
   ```powershell
   python -X utf8 <execution_cli_path> prepare-review --manifest <run_manifest.json> --kind red_team --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --max-turns 2
   python -X utf8 <execution_cli_path> register-review --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --red-team-receipt <red_team_receipt.json>
   ```

### Stage 4: 正式归档或预览（`archive` 节）

```powershell
python -X utf8 <execution_cli_path> forge --manifest <run_manifest.json> --refined <refined_core.json>
```
