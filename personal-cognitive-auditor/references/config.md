# personal-cognitive-auditor Configuration

## Supported Period Types

- `daily`
- `weekly`
- `monthly`
- `annual`

日期、时区和周期起点采用用户明确指定的值；未指定时使用当前会话可确认的本地日期与时区，并在输出中说明。

## Input Contract

| 输入 | 可接受来源 | 缺失时处理 |
|---|---|---|
| 日志与工作产出 | 用户提供的文本、文件或明确授权目录 | 报告缺口，不自动扫描其他目录 |
| 日程 | 用户提供的清单或明确授权的日历查询 | 报告缺口，不把安排推断为出席 |
| 健康背景 | 用户提供的数据或明确授权的健康摘要 | 报告缺口，不推断医学结论 |
| 既往承诺 | 用户提供或明确授权读取的既往复盘 | 状态写“无法判断”或省略问责表 |
| 历史对话 | 当前请求中提供或明确授权的范围 | 不自动读取全局历史 |

任何单一来源缺失都不阻断复盘。缺失信息影响结论时，降低证据强度并说明不能确定的内容。

## Validation

- 草稿可用 [audit_gate.py](../scripts/audit_gate.py) 检查。
- 未处理占位符和已经出现但不符合 Schema 的 `Handoff Payload` 是硬错误。
- 章节、措辞、术语和量化建议只产生软提示。
- 交接仅在用户明确要求保存时生成，并遵守 [handoff_contract.md](handoff_contract.md)。
