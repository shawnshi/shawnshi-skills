# 分阶段执行协议

供主代理按 `SKILL.md` 的阶段路由执行；所有命令优先使用运行快照内的冻结脚本路径 `<execution_cli_path>`。

## baseline

初始化运行目录、重建历史索引、抓取基线源并生成启发式候选池与补检请求：

```powershell
python -X utf8 scripts/run_daily.py prepare --report-date <YYYY-MM-DD> --timezone Asia/Shanghai --article-broker-version 3
```

## supplement

补检阶段针对 `supplement_request.json` 中的每个 `gap_id`（`technology-supply`、`healthcare-digital-supply`、`policy-competition`、`risk-counterevidence`）执行取证闭环。推荐使用 `codemode` 自动化串联以下步骤：

1. **初始化车道账本**：
   ```powershell
   python -X utf8 <run_scripts>/supplement_agent.py broker-checkpoint --parent --request <supplement_request.json> --gap-id <gap_id>
   ```
2. **核验候选与执行搜索**：
   - 先完成 `required_bound_candidate_ids` 必读 URL 的 `reserve-fetch -> fetch_content(mode="readable") -> record-fetch`；
   - 按车道 `query_scope` 执行 `reserve-query --provider <provider> -> web_search -> record-query --provider <provider> --query-response <file>`；
   - 对搜索发现或候选池中的高价值 URL 继续执行 `reserve-fetch / record-fetch`，直至满足 `stop_eligible=true`。
   - 若遇到不可恢复的公共工具异常，可调用 `broker-terminal` 登记终态（记录 `diagnostic/broker-terminal`），避免 `supplemental=running` 悬挂。
3. **封存与生成草案**：
   - 调用 `broker-seal` 封存车道证据账本；
   - 调用 `supplement_agent.py finalize --request <supplement_request.json> --gap-id <gap_id> --parent` 生成并校验草案（已装配 draft 也必须先通过 `supplement_agent.py finalize --parent` 登记父级回执，父代理代收口计入 `diagnostic/parent-finalized-drafts`）。
4. **汇总登记**：
   - 正常收口：
     ```powershell
     python -X utf8 <execution_cli_path> finalize-supplement --manifest <run_manifest.json> --request <supplement_request.json> --draft <draft_1> --draft <draft_2> ...
     ```
   - 异常或超时恢复收口：
     ```powershell
     python -X utf8 scripts/run_daily.py reconcile-supplement --manifest <run_manifest.json> --request <supplement_request.json> --result <draft_or_final> --progress-state <progress_json>
     ```

## runtime

子代理进度门禁与状态监控命令规范（当启用独立子代理观察时使用）：

```powershell
python -X utf8 <run_scripts>/review_progress_gate.py --manifest <run_manifest.json> --kind semantic_review --reviewer-id SemanticEvaluator --invocation-id <semantic_request.invocation_id> --request-sha256 <manifest.artifacts.semantic_review_request.artifact_sha256> --watch-path <semantic-dynamic-draft>
```

## semantic-review

1. 创建语义评估请求并提取已核验合格候选（`eligible_candidates`）：
   ```powershell
   python -X utf8 <execution_cli_path> prepare-review --manifest <run_manifest.json> --kind semantic --max-turns 2
   python -X utf8 <run_scripts>/semantic_agent.py context --request <semantic_review_request.json>
   ```
2. 撰写 `semantic_dynamic.draft.json`：
   - 仅从 `eligible_candidates` 中选择条目，按 6:4 默认领域配比组织 `selected_items`；
   - 每个条目包含完整中文 `title_zh`、`fact`、`connection`、`deduction`、`actionability`、`summary_zh`；
   - 若 `claim_grounding` 中设置 `"evidence_ref": "auto"`，`semantic_agent.py finalize` 会自动从已登记正文计算精确 `start`、`end` 与 `readable_text_sha256`。
3. 组装并校验语义结果：
   ```powershell
   python -X utf8 <run_scripts>/semantic_agent.py finalize --request <semantic_review_request.json>
   python -X utf8 <execution_cli_path> validate-semantic-draft --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json>
   ```

## red-team

1. 生成红队审查请求：
   ```powershell
   python -X utf8 <execution_cli_path> prepare-review --manifest <run_manifest.json> --kind red_team --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --max-turns 2
   ```
   - 当无 L4、无重大资讯且无冲突时，自动走 `no_l4_fast_path` 生成 `not_required` 回执；
   - 当 `deterministic_fast_path=false` 时，写出 `red_team_receipt.draft.json` 并运行 `validate-red-team-draft` 验证后提升为 `red_team_receipt.json`。
2. 登记评审回执：
   ```powershell
   python -X utf8 <execution_cli_path> register-review --manifest <run_manifest.json> --refined <refined_core.json> --semantic-receipt <semantic_receipt.json> --red-team-receipt <red_team_receipt.json>
   ```

## archive

执行最终门禁校验、事件去重、Markdown 渲染与事务归档：

```powershell
python -X utf8 <execution_cli_path> forge --manifest <run_manifest.json> --refined <refined_core.json>
```
