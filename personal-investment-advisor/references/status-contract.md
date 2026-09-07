# 状态与失败关闭契约

## 顶层工作流状态

- `complete`：本次声明范围内的必需门禁、证据与计算均闭合。
- `incomplete`：流程已运行，但至少一个必需阶段未完成；Daily Sync 的 Thesis 未评估属于此状态。
- `insufficient_evidence`：输入可解析，但证据不足以支持声明。
- `failed`：输入、身份、计算或运行发生硬失败。

脚本可保留业务 `detail_status`，但不得用自然语言 `unknown`、`data_gap` 或历史上的 `ok` 模糊顶层闭合度。兼容读取旧归档时必须显式标出兼容模式，不能把旧状态升级为当前完成。

公开状态必须同时聚合顶层 `status`、所有 `stages[].status`、`completeness.complete` 与 `valid`，不能因为顶层已经是非完成状态就跳过子阶段。严重度固定为 `failed` 高于 `insufficient_evidence`，后者高于 `incomplete`，最后才是 `complete`；任一层出现 `invalid`、`failed` 或 `valid=false`，最终状态均为 `failed`。

`stages` 若存在必须是列表（空列表表示未声明子阶段），每项必须是含已知 `status` 的对象；逐层递归聚合该对象的 `valid`、`errors`、`completeness` 和子阶段。缺失或未知状态、畸形阶段、超过 64 层的嵌套均失败关闭。`errors` 非空与当前层完成状态矛盾时判定失败；独立未完成工作中的缺口说明不自动升级为执行失败。

子进程负退出码或退出码大于等于 3 是硬失败，优先于证据不足，包括筛选路由。筛选的业务 `pass`/`fail` 在退出码为 0 时都表示描述性筛选完成，而非执行失败；未知或畸形筛选项仍失败关闭。普通子进程退出码 1 不能伴随完成状态；退出码 2 不能伴随完成或未完成状态。证据不足可保留其独立状态，不掩盖硬退出失败。

## 结论强度

`unknown` 可用于自然语言说明未知结论，`not_applicable` 可用于不适用的方法项，二者都不能代替顶层工作流状态。缺失、冲突、陈旧或无法定位到原始来源的数据不得用零值、默认通过或模拟结果替代。

## 退出码

稳定 CLI 的退出码映射由 `scripts/status_contract.py` 统一提供。只有 `complete` 返回成功；`incomplete`、`insufficient_evidence` 与 `failed` 均返回非零，并保留结构化状态与原因，供调用方区分重试、补证和硬失败。
