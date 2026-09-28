# A 股公告事实：点时与更正链

此入口仅处理**明确授权的本地公告原件与事实包**；不自动下载公告、不扫描目录、不读取持仓。`scripts/cn_filing_facts.py` 是离线结构门，不是官方公告解析器、财务审计或历史股票池证明。

## 输入与运行

由研究者从上交所、深交所、北交所、巨潮或发行人原始披露逐项记录数字，保留完整原件和真实取证日志。输入 JSON 为 `schema_version: "pia_cn_filing_facts_v1"`、`instrument: {symbol, market: "CN", asset_type: "stock"}`（`symbol` 必须是 `instrument_gate.py` 的规范代码，如上交所 `600519.SS`；不能用 `.SH`）、带时区秒级 `cutoff_at` 和非空 `facts`。每条事实含与标的相同的 `symbol`、`fact_id`、`metric`、`period_end`、`valuation_date`（同报告期末）、`unit`（如 `CNY`）、正数 `scale`（原件记「百万元」时为 `1000000`）、有限数值 `value`、`revision: original|correction`、`supersedes_fact_id`（原始为 null）、`source_type: filing`、一手 `source_tier`，以及 `source_timing_contract.py` 的完整来源时间和原件回执字段。`unit` 与 `scale` 一起明确原件币种及数量级，同一指标更正链不得变更两者；口径变化须作为新指标单列并解释，不得悄悄串接。

先将原件路径逐项核对为本次授权范围，再运行 `python -B scripts/cn_filing_facts.py <package.json> --verify-raw`。该开关按输入回执中的 `raw_artifact` **逐个读取**完整原件并重算哈希；无开关时绝不读原件，返回 `insufficient_evidence`、不输出可消费的选中事实。任何原件缺失、畸形输入、未来时点、重复 ID、更正链断裂／分叉或同键多条原始事实，失败关闭。输入最大 32 MiB、事实至多 1000 条。脚本不会写回文件或联网。

**结果边界**：`status=complete` 只说明包结构、截至时间、更正链与所授权原件字节一致。`selected_facts` 是每个 `(metric, period_end, unit)` 的链末版本，并携带 `scale` 与来源时点；旧值留在输入中，不被覆盖。不能据此宣称原件属于该发行人、字段与原文语义一致、没有遗漏更正公告、所标注的历史观测时间真实，或行业同口径可比。研究者须逐项记录原文页／表／行、公告编号、合并或母公司口径、币种与数量级，以及更正公告覆盖情况；独立复核通过之前，不把选中值送入估值、历史回测或 `corporate_action_adjusted`/`survivorship_bias_control` 的证明。当前筛选仍遵循点时不可得则降级为事实阅读的规则。

本入口不修改旧 Dashboard、Brief 或 Alpha JSON。若未来要自动连接下游，必须另行明确原件语义核验回执与版本化接口；不得把此结构门的 `complete` 自动提升为完整投资结论。
