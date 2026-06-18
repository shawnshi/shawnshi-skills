# Binding and Using a Design System

When generating a presentation, you can inherit visual traits from a past project's Design System.

## How it works
If the user says "基于项目 X 制作一份新的 PPT" or similar:
1. Navigate to the past project folder (`MEMORY/slide-deck/X/`).
2. Read `_d_meta.json` to identify the core system components.
3. Read `_ds_prompt.md` in that folder. It contains specific tokens, brand colors, and component tweaks applied to that specific presentation.
4. When writing the new `index.html` for the new project (`MEMORY/slide-deck/Y/index.html`), inject the colors and rules specified in `X/_ds_prompt.md` into the CSS `<style>` block of the skeleton, or use the specific HTML structures requested.
5. Copy any customized local assets (like background images or specific fonts) from `X/assets/` or `X/images/` to `Y/`.

## Writing a Design System
When finishing ANY new project, you MUST output a `_ds_prompt.md` and `_d_meta.json` in the project directory so future sessions can reuse it.

Example `_d_meta.json`:
```json
{
  "baseStyle": "winning-clinical",
  "brandColor": "#005EB8",
  "hasCustomFonts": false,
  "componentOverrides": ["c-pillar"]
}
```

Example `_ds_prompt.md`:
```markdown
# Custom Design System for Project X

- **Base Theme**: Winning Clinical
- **Primary Brand Color**: `#005EB8`
- **Specific Adjustments**: 
  - `.c-pillar` has `border-radius: 4px;` added.
  - Headings use `.c-action-title` with `letter-spacing: -0.05em;`.
- **Backgrounds**: Uses `images/bg-pattern.svg` on all `.canvas-card` elements.

**Constraint**: Any future projects inheriting this system MUST use these specific CSS tweaks inline or in the `<head>` style block.
```
