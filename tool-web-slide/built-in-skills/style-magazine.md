# Magazine Style (电子杂志风)

This is the dictionary and visual constraint for the "Magazine" style. Use this when the user asks for "Magazine", "电子杂志风", "画册", or "社论风格".

## Visual Constraints
- **Aesthetic**: Editorial, elegant, heavy use of serif typography, distinct columns, like a high-end printed magazine.
- **Typography**: 
  - `var(--serif)` for large elegant headlines.
  - `var(--sans)` for body text and captions.
- **Colors**: Typically warm paper backgrounds (`#f5f4f0`) or dark charcoal (`#1a1a1a`) with rich, subdued accent colors.

## Component Dictionary
Use ONLY the following CSS classes for layout and content formatting:

### Layout Primitives
- `.mag-canvas`: The main wrapper inside `.slide`, overriding `.canvas-card` with tighter margins.
- `.mag-header`: Editorial header, often spanning multiple columns.
- `.mag-title`: Elegant, oversized serif title. `.mag-title.italic` for emphasis.
- `.mag-lead`: The lead paragraph, slightly larger and often bold or serif.

### Editorial Structures
- `.mag-article`: A 2-column or 3-column text layout (`column-count: 2`).
- `.mag-drop-cap`: The first letter of an article, enlarged and floated left.
- `.mag-pull-quote`: A large quote breaking the text flow. `<blockquote class="mag-pull-quote">`.
- `.mag-figure`: Image wrapper with editorial caption. `<figure class="mag-figure">`.
- `.mag-caption`: Text underneath the figure.

### Data & Timelines
- `.mag-stat`: Large numbers using serif font.
- `.mag-list`: Elegant bullet points with custom markers (e.g., em dashes).

## Example Slide
```html
<section class="slide" data-animate="fade">
  <div class="canvas-card mag-canvas" style="display:flex;flex-direction:column">
    <div class="mag-header">
      <span class="t-meta">EDITORIAL / ISSUE 04</span>
      <h1 class="mag-title">The <span class="italic">Future</span> of Care.</h1>
    </div>
    
    <div class="mag-article" style="margin-top: 5vh; column-count: 2; column-gap: 4vw;">
      <p><span class="mag-drop-cap">A</span>s we step into the new era of medical informatics, the paradigm shifts from passive record-keeping to active, predictive intelligence.</p>
      <p>Data lakes and language models now merge to form a singular intelligence layer.</p>
      
      <blockquote class="mag-pull-quote">
        "It's no longer about storing data; it's about asking the data questions."
      </blockquote>
    </div>
  </div>
</section>
```
