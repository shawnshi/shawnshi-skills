# Winning Clinical Style (极简医疗风)

This is the dictionary and visual constraint for the "Winning Clinical" style. Use this when the user asks for "Winning Clinical", "极简医疗风", "卫宁模板", or "医疗汇报".

## Visual Constraints
- **Primary Color**: `#005EB8` (Winning Medical Blue).
- **Aesthetic**: Strictly minimalist, professional, rigid grid-based.
- **Prohibitions**: No 3D objects, no cartoonish illustrations, no fluid shapes. Strict right angles and solid colors.

## Component Dictionary
Use ONLY the following CSS classes for layout and content formatting:

### Layout Primitives
- `.c-header`: Top level header block containing `.c-tracker` and `.c-action-title`.
- `.c-tracker`: Meta-information for the slide (e.g., `OUR VISION / 01`). Use Lucide icons.
- `.c-action-title`: The main headline of the slide, max font size 4.5vw.
- `.c-pillars`: A flex container for comparing or listing 2-3 items.
- `.c-pillar`: A column inside `.c-pillars`. 
- `.c-pillar.highlight`: A column with a highlighted top border (var(--accent)).
- `.c-pillar-title`: The title inside a pillar.
- `.c-pillar-body`: The text content inside a pillar.

### Era / Timeline Components
- `.s-era-grid`: A grid container for historical roadmaps or stages.
- `.s-era`: An individual stage block.
- `.s-era.highlight`: Highlighted stage block.
- `.s-era-period`: The year or period string (e.g., `1994 - 2014`).
- `.s-era-zh`: The Chinese title for the stage.
- `.s-era-en`: The English subtitle.
- `.s-era-role`: The description of the stage.

### Typography
- `.h-xl-zh`: Extra large Chinese headline.
- `.t-cat`: Category small tag text.
- `.t-meta`: Metadata text, usually smaller and semi-transparent.
- `.lead`: Lead paragraph text, slightly larger than body.

## Example Slide
```html
<section class="slide" data-animate="hero">
  <div class="canvas-card" style="display:flex;flex-direction:column">
    <div class="c-header" data-anim="hero-text">
      <div class="c-tracker"><i data-lucide="compass"></i> 顶层设计 <span class="sep">/</span> <span class="active">01</span></div>
      <h2 class="c-action-title">构建<strong>平台化中枢</strong>。</h2>
    </div>
    <div class="c-pillars" style="margin-top:4vh" data-anim="bottom">
      <div class="c-pillar highlight" data-anim="col">
        <h3 class="c-pillar-title">数据标准</h3>
        <p class="c-pillar-body">统一的数据与业务中台建设，标准化数据原生落盘。</p>
      </div>
    </div>
  </div>
</section>
```
