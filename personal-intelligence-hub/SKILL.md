---
name: personal-intelligence-hub
description: 战略情报作战中枢。用于多源技术/医疗/AI 情报扫描、7 日去重、二阶推演、红队审计和分层简报生成。必须读取 `references/strategic_focus.json`、`references/quality_standard.md`、`references/briefing_template.md` 和 `references/karpathy_feeds.json`，并通过 `blackboard`、`history_manager`、`briefing_gate` 保证状态、去重与交付质量。
---

<strategy-gene>
Keywords: 战略情报扫描, 去重精炼, 二阶推演, 红队审计
Summary: 调度多源情报源执行 7 日闭环扫描，将新闻噪音转化为高价值行动杠杆。
Strategy:
1. 配置先行：严格依据 strategic_focus.json 锁定扫描主题与排除词。
2. 语义去重：执行 7 日 URL 与指纹对齐，确保 100% 信息增量。
3. 结构化提纯：每条情报必须满足 Fact -> Connection -> Deduction -> Actionability 结构。
4. 强制双链图谱与双轨落盘：对核心企业、人物或专有名词必须使用 `[[ ]]` 进行硬链接；若是长效落盘，必须遵守 Compiled Truth | Timeline 上下分割规范。
5. 异步入湖：提纯出的核心实体必须被推送至向量湖图谱。
AVOID: 严禁把“摘要”伪装成“洞察”；禁止在缺乏证据时输出 L4 级高等级判断；禁止重复推送同一信号；严禁在报告中遗漏重要实体的双链图谱标记；严禁越界将原始抓取数据直接写入核心图谱。
</strategy-gene>

# Personal Intelligence Hub V8.1

## 0. 核心约束
- **配置优先**: 扫描范围、主题、优先源、排除词都以 `references/strategic_focus.json` 为准。
- **质量合同**: 每条高价值情报必须满足 `references/quality_standard.md` 的 `fact / connection / deduction / actionability` 结构。
- **状态显式化**: 运行状态必须写入 `blackboard`，去重必须走 `history_manager`，交付前必须通过 `briefing_gate`。
- **跨平台与安全寻址**: 所有底层 Python 脚本调用必须使用 `{SKILL_DIR}` 绝对寻址，并强制挂载 UTF-8 环境锁，严禁依赖相对路径或默认字符集。

## 1. 运行资产
- **Feeds**: `references/karpathy_feeds.json`
- **Strategy Config**: `references/strategic_focus.json`
- **Quality Contract**: `references/quality_standard.md`
- **Briefing Template**: `references/briefing_template.md`
- **State Scripts**:
  - `scripts/blackboard.py`
  - `scripts/history_manager.py`
  - `scripts/briefing_gate.py`

## 2. 执行协议

### Phase 1 & 2: Fetch & Refine (物理爬取与去重)
1. 主代理执行底层抓取脚本（务必挂载编码锁）：
   `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/run_phase1_2.py"`
2. 脚本将自动调用 `fetch_news.py` 和 `refine.py`，完成数据采集并生成粗筛候选池 `intelligence_candidates.json`。
3. 主代理调用系统底层 `invoke_subagent` 启动独立精炼子代理（`TypeName: research` 或 `self`）进行二阶推演。

### Phase 3: Semantic Deduction (子代理推演)
1. 子代理读取粗筛数据，并依据质量合约执行二阶推演、双链补齐 `[[ ]]`。
2. 子代理**仅需将推演结果规范地写入** `intelligence_current_refined.json`。
3. 写入完成后，子代理将控制权交还主代理，结束其沙盒任务。

### Phase 4: Pipeline Gate Orchestration (主代理门控与锻造)
**约束**: 严禁要求子代理手动敲击多个脚本。以下验证流程必须由主代理接管：
1. **JSON 校验**: 主代理运行 `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/validate_refined_json.py"`。若报错，主代理自行阅读报错并修正 JSON。
2. **红队对抗**: 若精炼数据中存在 L4 候选，主代理运行 `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/adversarial_audit.py"`。
3. **最终锻造**: 主代理运行 `$env:PYTHONIOENCODING="utf-8"; python "{SKILL_DIR}/scripts/forge.py"` 生成最终简报，并通过 `briefing_gate`。

### Phase 5: Async Vector Lake Ingestion (异步图谱入湖)
1. 报告锻造完成后，主代理必须提取报告中包含 `[[ ]]` 双链标记的新生成实体，将其保存为标准图谱文件 `C:/Users/shich/.gemini/MEMORY/wiki/Entity_*.md`。
2. **异步同步**: 主代理调用 `mcp_vector-lake-mcp_prepare_ingest_batch` 提取待同步清单，随后利用 `invoke_subagent` 拉起 `vector-lake-ingestor` 执行后台异步入湖。绝对禁止直接调用阻塞式的 `sync_vector_lake`。

## 3. 结果门
- `punchline` 不得为空。
- `action_levers` 至少 3 条。
- `top_10` 最多 10 条且 URL 不得重复。
- 每个 Top item 必须有 `summary`。
- 若仍存在 L4，则必须存在 `adversarial_audit` 记录。

## 4. 反模式
- 禁止把“摘要”伪装成“洞察”。
- 禁止过去 7 天重复推送同一核心信号。
- 禁止在缺 Evidence 时输出高等级判断。
- 禁止把 skill 目录当作运行时数据库。

## 5. Telemetry & Failure Modes (降级容灾)
- **优雅降级 (Degraded Mode)**: 若无 LLM runner、子代理宕机、或 API 被限流，主代理必须跳过推演环节。直接提取粗筛池 `intelligence_candidates.json`，打上 `[Degraded Mode]` 标签，使用启发式脚本强行过检并生成底层事实简报，确保情报网“绝不静默”。
- **遥测记录**: 任务完成后（无论成功还是降级），将 telemetry 写入本地 audit path。推荐结构：
```json
{"skill_name":"personal-intelligence-hub","status":"success","mode":"daily_brief","runner":"llm","top10_count":10}
```

## When to Use
- Use this skill according to the frontmatter trigger description and the domain-specific rules already defined above.

## Workflow
- Follow the existing phases, scripts, and handoff rules in this skill. Do not skip validation or approval gates already defined above.

## Resources
- Use this skill directory's bundled scripts, references, assets, examples, prompts, and agents as needed. Load only the specific resource needed for the current request.

## Output Contract
- Final output must match the user request, preserve the skill's domain contract, and include validation evidence or an explicit reason validation could not run.
