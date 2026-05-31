---
name: academic-scientific-visualization
description: "Meta-skill for publication-ready scientific figures. Use when creating journal submission figures requiring multi-panel layouts, significance annotations, error bars, colorblind-safe palettes, and specific journal formatting for Nature, Science, Cell, IEEE, ACM, or discipline-specific manuscripts."
---

<strategy-gene>
Keywords: scientific figure, publication figure, multi-panel, significance annotation, colorblind-safe
Summary: Produce publication-ready scientific figures with statistical transparency, journal sizing, and accessible visual design.
Strategy:
1. Identify target journal, figure type, panel count, statistical annotations, and export formats.
2. Use reusable helpers and references for journal specs, palettes, and export validation.
3. Render or inspect the output before final delivery; revise if labels, colors, size, or uncertainty display fail.
AVOID: Never submit low-DPI, unlabeled, color-only, or statistically ambiguous figures.
</strategy-gene>

# Scientific Visualization

This is the entrypoint for journal-grade figures. The complete historical cookbook is preserved in `references/full_visualization_playbook.md`; load it only when detailed code examples or library-specific recipes are needed.

## When to Use
- Use for manuscript figures, scientific plots, multi-panel layouts, statistical visualization, figure repair, and journal formatting.
- Use when the user mentions publication, Nature/Science/Cell, significance bars, error bars, confidence intervals, colorblind-safe palettes, or figure export quality.
- Do not use for generic business dashboards unless the user explicitly asks for scientific publication standards.

## Workflow
1. **Clarify target**: Determine journal or venue, figure type, audience, panel count, data source, and required file formats.
2. **Select library**: Prefer Matplotlib/Seaborn for static publication figures; use Plotly only when exploration or interactive review is central.
3. **Design figure**: Set size, DPI, typography, axes, units, legend, panel labels, and caption requirements.
4. **Encode evidence**: Show uncertainty with CI/SD/SEM as appropriate; show individual points when sample size is small.
5. **Check accessibility**: Use colorblind-safe palettes, redundant encodings, sufficient contrast, and grayscale viability.
6. **Export and verify**: Use helper scripts where possible, inspect rendered output, and correct clipping, unreadable text, missing units, or empty plots.

## Resources
- Full cookbook: `references/full_visualization_playbook.md`
- Publication requirements: `references/publication_guidelines.md`, `references/journal_requirements.md`
- Colors: `references/color_palettes.md`, `assets/color_palettes.py`
- Examples: `references/matplotlib_examples.md`
- Helpers: `scripts/figure_export.py`, `scripts/style_presets.py`
- Style files: `assets/publication.mplstyle`, `assets/nature.mplstyle`, `assets/presentation.mplstyle`

## Validation Checklist
- Resolution meets target journal requirements.
- Fonts are readable at final size.
- Axes include units where applicable.
- Error bars or uncertainty bands are defined.
- Significance annotations match the statistical test.
- Colors remain interpretable for colorblind readers and in grayscale.
- Multi-panel labels are consistent.
- Exported files open correctly and are not blank.

## Failure Modes
- **No target venue**: Use conservative default journal settings and state the assumption.
- **Missing statistical method**: Ask for or infer the test only when justified; otherwise label the figure as descriptive.
- **Color accessibility failure**: revise palette or add shape/line-style encoding.
- **Unreadable final size**: increase dimensions or simplify the layout.
- **Export failure**: fall back to PNG plus vector format when possible, and report the blocked format.

## Output Contract
- Deliver figure files or code that can reproduce them.
- Include the statistical meaning of error bars, bands, and significance marks.
- Include source or data provenance when external data is used.
- Do not claim publication readiness until the rendered figure has been inspected.

## Telemetry
- Record target journal, figure type, export formats, validation checks, and unresolved limitations when persistent logging is available.
