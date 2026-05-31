# personal-cognitive-auditor Configuration (V2.0)

## 1. Runtime Defaults
- **timezone**: `Asia/Shanghai`
- **language**: `zh-CN`
- **default_week_start**: `Monday`

## 2. Supported Period Types
- `daily`
- `weekly`
- `monthly`
- `annual`

## 3. Capability Contract
- `physiology_context`
  - preferred: Garmin or health baseline summary
  - fallback: manual sleep / fatigue / recovery notes
- `calendar_context`
  - preferred: Google Calendar or structured schedule
  - fallback: manual event list
- `prior_tactics`
  - preferred: extracted tactics from prior audit
  - fallback: user-provided commitments
- `interaction_context`
  - preferred for weekly/monthly/annual
  - fallback: explicit `【数据缺口】未注入交互上下文`

## 4. Downgrade Rules
- Missing one source does not block delivery.
- Missing both physiology and calendar must trigger an explicit data-gap note.
- Missing prior tactics must convert accountability into a `no-prior-tactics` note.
- Missing interaction context blocks neither `daily` nor `weekly`, but must be disclosed for `weekly/monthly/annual`.

## 5. Handoff Target
- Downstream skill: `personal-diary-writer`
- Handoff must follow [handoff_contract.md](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/references/handoff_contract.md:1>)

## 6. Validation Rules
- Audit must pass [audit_gate.py](<C:/Users/shich/.codex/skills/personal-cognitive-auditor/scripts/audit_gate.py:1>) before hand-off.
- Final output must be Markdown, not JSON-only.
- Handoff payload must be embedded in the report.
