# personal-cognitive-auditor Handoff Contract

本技能默认只在对话中交付复盘。周、月、季度 canonical 自动保存使用独立的周期审计 payload 和结构化请求门，不需要本交接载荷。只有用户明确要求交接到其他流程时，才生成下列载荷；生成载荷不等于授权写入。

## Required Fields

```json
{
  "period_type": "daily|weekly|monthly|quarterly|annual",
  "audit_title": "string",
  "audit_body_markdown": "string",
  "next_tactics": ["string"],
  "followup_flags": ["string"],
  "requires_mentat_diary": false
}
```

## Field Semantics

- `period_type`：复盘周期。
- `audit_title`：非空标题。
- `audit_body_markdown`：要交接的完整 Markdown 正文，不包含 `Handoff Payload` 自身。
- `next_tactics`：至少一个非空动作；没有可支持动作时不生成交接。
- `followup_flags`：可为空，只包含用户可见且与本次复盘相关的标签。
- `requires_mentat_diary`：默认且通常为 `false`。只有用户明确要求另行生成 Mentat 日志时才可设为 `true`；该值不授权写入。

## Handoff Rules

- 日度、年度、自定义路径和外部交接先展示完整复盘、目标写入位置和载荷，等待用户确认后再调用持久化流程；周、月、季度 canonical 自动保存另走受保护的 `periodic-audit-request-v1` 门。
- 保留正文中的数据缺口、来源窗口和不确定性。
- 不在载荷中加入人格标签、医学判断、隐藏推理或超出任务所需的私人数据。
- `personal-diary-writer` 仍须执行自己的预览和确认门禁；本载荷不能绕过该门禁。
