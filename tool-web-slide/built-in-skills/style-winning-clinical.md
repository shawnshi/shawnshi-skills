# Winning Clinical Style (极简医疗风)

This is the dictionary and visual constraint for the "Winning Clinical" style. Use this when the user asks for "Winning Clinical", "极简医疗风", "卫宁模板", or "医疗汇报".

## Visual Constraints (Winning Health 2.1.0 Design System)
- **Primary Color**: `#005EB8` (var(--primary-600)) for strategic bases, `#E3F2FD` (var(--primary-100)) for highlights.
- **Secondary Color**: `#00B5E2` (var(--secondary)) for AI accents.
- **Accent Color**: `#F2A900` (var(--accent)) for distinct alerts/warnings.
- **Gray Scale**: `#1A232C` (var(--gray-900)) for main text (ink), `#F2F6FA` (var(--gray-100)) for paper backgrounds.
- **Aesthetic**: Strictly minimalist, professional, rigid grid-based. Dual-mode rules for high-density medical IT interfaces and high-signal-to-noise ratio architectural presentations.
- **Prohibitions**: No 3D objects, no cartoonish illustrations, no fluid shapes. Strict right angles and solid colors. Maximum 3 accent colors per slide.

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

### Medical IT / HIT Specific Components
- `.c-statement`: Full slide container for a bold, declarative statement (Hero Quote).
- `.c-statement-text`: The large text of the statement.
- `.c-statement-sub`: The subtitle/attribution.
- `.c-kpi-group`: Grid container for highlighting key metrics/ROIs.
- `.c-kpi`: A single metric column.
- `.c-kpi-value`: The large number (wrap suffixes like "%" in `<span>`).
- `.c-kpi-label`: The description of the metric.
- `.c-timeline`: A horizontal connecting line for roadmap phases.
- `.c-timeline-step`: A step in the timeline.
- `.c-timeline-marker`: The circular dot on the timeline.
- `.c-timeline-year`: The year/phase label.
- `.c-timeline-title`: The title of the phase.
- `.c-timeline-desc`: The description.

### Era / Timeline Components (Legacy)
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
