# Swiss Style (瑞士国际风)

This is the dictionary and visual constraint for the "Swiss" style. Use this when the user asks for "Swiss", "瑞士风", "网格排版", or "国际主义".

## Visual Constraints
- **Primary Colors**: 
  - `--paper`: `#ffffff` (White background)
  - `--ink`: `#0a0a0a` (Black text/blocks)
  - `--accent`: International Klein Blue (`#0000ff`) or other single vibrant color.
- **Aesthetic**: Extreme minimalism, strict grid alignment, stark black-and-white contrasts with a single accent color.
- **Typography**: `var(--sans)` for headings, `var(--mono)` for data/numbers. Headings use light weights (200/300).

## P0 Alignment Rules
1. **Never double-pad**: `.canvas-card` already has padding. Do NOT add `padding: 5vh 5vw` to its immediate children.
2. **Kicker placement**: `.t-meta` or `.t-cat` kickers MUST be strictly above the main title, never side-by-side.
3. **No Phantom Classes**: Use only predefined structural classes.

## Component Dictionary
Use ONLY the following CSS classes for layout and content formatting:

### Foundational Layouts
- **Hero/Cover (P1)**: `<section class="slide accent" data-animate="hero">`. Uses `.canvas-card` with an `<canvas class="ascii-bg">`. Main title `.h-hero` or raw `h1` with `font-weight: 200`.
- **Statement (P3/P10)**: Massive text centered. `<h1 class="h-statement">` with optional `.dot-mat` or `.ring-mat` decorative SVGs.
- **Split/Closing (P9)**: `<section class="slide split">` with `<div class="split-half">`. Left side `.half.b-accent`, right side `.half`.

### Grids & Matrices
- **Six Cells (P4)**: `<div class="cell-6">` with 6 `<div class="cell">` children.
- **Three Sub-cards (P5)**: `.grid-2-9` wrapper. Left `.lead-col`, right `.sub-card-stack` containing 3 `.sub-card.card-fill`.
- **Image Matrix (P15)**: `.matrix-fill` containing multiple `.matrix-cell`.
- **Four Columns (P19)**: `.four-cards` containing 4 `.fc-col`.

### Data & Timelines
- **Vertical Timeline (P2)**: `.timeline-v` containing `.tl-node` (with `.tl-axis` and `.tl-body`).
- **Horizontal Timeline (P11)**: `.timeline-h` containing `.tl-h-node`.
- **KPI Tower (P6)**: `.kpi-tower-row` with `.tower-col` and `.bar-tower`.
- **Horizontal Bar Chart (P7)**: `.h-bar-chart` with `.bar-row` and `.bar-fill`.

### Cards and Fills
- `.card-ink`: Black background with white text.
- `.card-accent`: Accent background.
- `.card-fill`: Grey background (default neutral).
- `.card-outlined`: Hairline border.

## Example Slide (Swiss Statement)
```html
<section class="slide" data-animate="statement-rise">
  <div class="canvas-card">
    <div class="chrome-min">
      <div class="l">SECTION · TOPIC</div>
      <div class="r">04 / NN</div>
    </div>
    <h1 class="h-statement">
      <span>Build it</span> <span>once.</span><br>
      <span>It runs</span> <span>forever.</span>
    </h1>
    <span class="stmt-anchor" style="position:absolute;bottom:8vh;right:5vw">— 核心主张</span>
  </div>
</section>
```
