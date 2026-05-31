# personal-cognitive-auditor Handoff Contract

`personal-cognitive-auditor` does not write diary files directly. It hands off a structured payload to `personal-diary-writer`.

## Required Fields

```json
{
  "period_type": "daily|weekly|monthly|annual",
  "audit_title": "string",
  "audit_body_markdown": "string",
  "next_tactics": ["string"],
  "followup_flags": ["string"],
  "requires_mentat_diary": false
}
```

## Field Semantics
- `period_type`: audit cycle type
- `audit_title`: title used by diary writer
- `audit_body_markdown`: full Markdown body to be persisted
- `next_tactics`: 1-3 tactical follow-ups for the next cycle
- `followup_flags`: optional tags such as `accountability`, `long_cycle`, `yearly_reset`
- `requires_mentat_diary`: set `true` when the audit reveals architecture-level or cognition-level friction worth escalating

## Handoff Rules
- `audit_body_markdown` must be the exact report body, not a summary.
- `next_tactics` must not be empty.
- If the audit ran in degraded mode, preserve the `【数据缺口】` lines in `audit_body_markdown`.
- If the audit surfaces architecture-level cognitive debt, set `requires_mentat_diary: true`.
