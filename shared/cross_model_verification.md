# Cross-model Verification

Use a second model only when the decision is high impact, the claim is difficult to verify directly, and an independently configured model is available. Most tasks should rely on primary sources and deterministic checks instead.

## Rules

1. Prefer primary-source verification over model agreement.
2. Select models from the capabilities currently configured in the environment; do not hardcode version names.
3. Do not send secrets, personal data, unpublished material, or licensed content to an external provider without explicit authorization.
4. Give the verifier the raw question and evidence, not the first model's conclusion, unless the task is an explicit critique.
5. Compare claims, citations, assumptions and uncertainty. Agreement between models is not proof.
6. Record provider, model identifier, date and prompt when reproducibility matters.
7. If the second model is unavailable, continue with source verification and state the limitation.

## Suggested output

| Claim | Primary evidence | Independent check | Conflict | Resolution |
|---|---|---|---|---|

Escalate unresolved conflicts instead of averaging them.
