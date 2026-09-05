# Skill Structure Template

Use this template when creating or refactoring a skill.

## Frontmatter

```yaml
---
name: skill-name
description: State what the skill does and when it should be used.
---
```

`name` and `description` are required. Use only optional fields supported by the current Pi runtime: `license`, `compatibility`, `metadata`, `allowed-tools`, and `disable-model-invocation`. Do not add fields that no active parser or runtime consumes.

## Body

Keep `SKILL.md` as the routing and execution layer. Include only what the model cannot reliably infer from the request, files, tool schemas, or deterministic scripts:

- the outcome and applicable scope;
- required inputs and relevant context;
- safety, authorization, privacy, persistence, and data boundaries;
- real tools or commands and when to use them;
- deliverables, validation evidence, and failure behavior.

Do not prescribe hidden reasoning, fixed agent counts, fixed rounds, or ceremonial planning. Let task complexity determine the work breakdown. Move long tutorials, examples, schemas, and reusable procedures into `references/`, `scripts/`, or `assets/`, and link them only where needed.

Use skill-relative paths for local resources. After changing referenced files, refresh `resource-manifest.json` and run the repository gate.
