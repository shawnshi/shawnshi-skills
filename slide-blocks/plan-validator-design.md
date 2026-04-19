# Plan Validator Design Draft

## Goal

Introduce a validator that catches assembly errors before PowerPoint COM execution.

The validator should sit between:

1. plan generation
2. `engine/runner.py`
3. `engine/assemble_template.py`

It is not a replacement for the engine. It is a compile-time gate for plan safety and contract compliance.

## Why This Exists

The current `--dry-run` behavior only checks file existence. That is too shallow for a system with:

- template-role semantics
- source slide page references
- mandatory closing conventions
- light/dark adaptation rules

The validator exists to move expensive failures left.

## Proposed Invocation

### CLI

```powershell
python -m engine.plan_validator tasks/plan_demo.json
python -m engine.plan_validator tasks/plan_demo.json --strict
python -m engine.plan_validator tasks/plan_demo.json --manifest manifests/light-default.json
```

### Runner integration

Preferred execution chain:

1. validator runs first
2. runner executes only if validator passes

Possible future interface:

```powershell
python -m engine.runner tasks/plan_demo.json --validate
```

## Inputs

### Required

- plan JSON file

### Optional

- template manifest path
- strict mode flag
- config path override

## Validation Layers

### Layer 1: JSON schema validation

Checks:

- top-level keys exist: `template_path`, `output_path`, `plan`
- `plan` is a non-empty array
- every step is an object
- every step is either:
  - template step
  - source step
- step fields are well-typed

Template step rules:

- must include `template_page`
- may include `replace_title`
- may include `font_size`

Source step rules:

- must include `src`
- must include `page`
- may include `replace_title`
- may include `fix_colors`
- may include `fix_colors_dark`

Invalid mixed-step example:

```json
{
  "template_page": 2,
  "src": "x.pptx"
}
```

This should fail.

### Layer 2: Path ownership validation

Checks:

- `template_path` exists
- every `src` exists
- `output_path` parent directory exists or can be created
- paths resolve under expected configured roots when strict mode is on

Strict-mode examples:

- `template_path` must resolve under `{materials_dir}`
- `output_path` must resolve under `{output_dir}`

This prevents environment drift and dead absolute paths from examples.

### Layer 3: Template contract validation

Checks:

- referenced `template_page` exists in the template deck
- all manifest-declared page roles exist
- closing page role exists
- transition page role exists if plan uses transition steps

If a manifest is present, validator should use manifest role semantics instead of engine constants.

### Layer 4: Source deck validation

Checks:

- every source deck opens successfully
- every `page` exists inside its source deck
- optional warning if source title detection is likely ambiguous

This can be implemented in two stages:

1. non-COM inspection where possible
2. COM-backed inspection only if needed

## Contract Rules

### Baseline rules

- cover page should be first
- closing page should be last
- transition pages should use `font_size: 40` when required by manifest
- no empty plan

### Optional policy rules

- forbid transition page immediately after cover
- require at least one content page before closing
- warn on repeated identical source pages
- warn on suspiciously large title strings

## Severity Model

### Error

The plan must not execute.

Examples:

- missing file
- invalid page reference
- invalid JSON structure
- unsupported mixed step
- missing required closing page

### Warning

The plan can execute, but quality risk is high.

Examples:

- title likely too long for transition page
- source deck background mode unclear
- excessive repeated source deck usage
- fix-colors flags inconsistent with detected backgrounds

## Output Format

### Human-readable summary

Example:

```text
[ERROR] Step 7 source page out of range: page 28, deck has 19 pages
[ERROR] Missing closing template page at final step
[WARN ] Step 3 transition page missing font_size=40
```

### Machine-readable JSON

Example:

```json
{
  "valid": false,
  "errors": [
    {
      "code": "SOURCE_PAGE_OUT_OF_RANGE",
      "step_index": 7,
      "message": "Requested page 28, but source deck has 19 pages."
    }
  ],
  "warnings": [
    {
      "code": "TRANSITION_FONT_SIZE_MISSING",
      "step_index": 3,
      "message": "Transition page should set font_size to 40."
    }
  ]
}
```

## Suggested Module Layout

Add:

- `engine/plan_validator.py`
- `engine/plan_schema.py`
- `engine/template_manifest.py`

Responsibilities:

- `plan_schema.py`: JSON structure validation and step normalization
- `template_manifest.py`: load and validate manifest semantics
- `plan_validator.py`: orchestrate schema, path, template, and source checks

## Minimal Implementation Order

### Step 1

Implement schema validation and path validation.

Reason:

- highest value
- no need to touch render engine

### Step 2

Implement manifest-aware validation for template roles.

Reason:

- removes the biggest structural SPOF

### Step 3

Implement source deck page-range validation.

Reason:

- catches common runtime failures before COM assembly

### Step 4

Add warning heuristics and optional strict-mode root enforcement.

Reason:

- improves operator quality without blocking valid plans

## Non-Goals

- do not replace `assemble_template.py`
- do not redesign hybrid retrieval
- do not introduce a new rendering engine
- do not turn this into a generic PPT platform

The validator is a gate, not a new center of gravity.

## Bottom Line

The validator should make invalid plans cheap to reject and valid plans cheap to trust.

That is the shortest path to making `slide-blocks` durable without rewriting the engine.
