# Outline Template (V11 Blueprint Contract)

Use this file as the single schema for `outline.md`.

## Header

```markdown
# Slide Deck Outline

**Topic**: [topic description]
**Audience**: [target audience]
**Objective**: [decision or influence goal]
**Language**: [output language]
**Style**: [style name or custom]
**Slide Count**: N
**Generated**: YYYY-MM-DD HH:mm

---

<STYLE_INSTRUCTIONS>
Design Aesthetic:
  - [1-2 sentence visual thesis]

Background:
  Texture: [texture description]
  Base Color: [hex or named color]

Typography:
  Headline: [appearance description]
  Body: [appearance description]

Color Palette:
  Primary: [hex] - [usage]
  Secondary: [hex] - [usage]
  Accent: [hex] - [usage]
  Neutral: [hex] - [usage]

Visual Elements:
  - [element 1]
  - [element 2]

Density Guidelines:
  - [content density rule]
  - [whitespace rule]

Style Rules:
  Do: [positive guidance]
  Don't: [anti-pattern]
</STYLE_INSTRUCTIONS>

---
```

## Slide Schema

Every slide must use this structure:

```markdown
Page X: [narrative title sentence]
Type: Cover | Content | Closing

// NARRATIVE GOAL
[why this slide exists]

// KEY CONTENT
Headline: [main point]
Sub-headline: [supporting line]
Body/Data:
- [bullet or compressed data point]
- [bullet or compressed data point]
Trust_Anchor: [Ref: evidence id or source]

// VISUAL
[visual description]

// LAYOUT
[layout structure]

// Script:
[speaker script]

---
```

## Special Slide Rules

- Page 1 must be `Type: Cover`
- Final page must be `Type: Closing`
- Cover should contain only title-scale content, not dense bullets
- Closing must end with a call to action, next step, or closing thesis
- Middle pages must be `Type: Content`
