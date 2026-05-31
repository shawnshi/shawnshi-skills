# Skill Structure Template

Use this template when creating or refactoring a skill.

## Frontmatter

Required:

- `name`
- `description`

Optional:

- `version`
- `triggers`
- `benefits-from`
- `license`

## Recommended Section Order

```md
# Skill Title

## When to Use
State trigger intent, scope, and explicit non-goals.

## Workflow
Describe the execution flow or phases.

## Resources
List local scripts, references, assets, examples, prompts, or sibling skills that are part of the skill's physical dependency graph.

## Failure Modes
List anti-patterns, fallback rules, and common breakpoints.

## Output Contract
Define the minimum acceptable output and delivery gate.

## Telemetry
State whether telemetry is required and where it should be recorded.
```

## Notes

- Keep the main `SKILL.md` focused on trigger, workflow, and hard constraints.
- Move long tutorials, examples, and framework-specific detail into `references/`.
- Prefer local relative paths over hard-coded foreign runtime paths.
- If a skill references local files, refresh `resource-manifest.json` after edits.
