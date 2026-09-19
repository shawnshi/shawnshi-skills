---
title: Style References
date: 2026-09-19
status: Active
author: System
---

# Style References

Presets for the Smart LaTeX engine. Every typographic number below was measured
from a compiled PDF before it was written down (TeX Live 2026, Pandoc 3.8.3,
Windows CTeX fonts); re-measure `\the\baselineskip`, `\the\linewidth` and the
actual body font in the task copy before claiming compliance.

## Typography contract takes precedence

Read the skill's `SKILL.md` typography procedure and the current `WRITING.md`
before selecting a style. A bundled preset is a starting point. It is not a publisher-approved exception,
and only explicit user instructions or an applicable
supplied template or publisher, journal, legal, or brand guide override
conflicting defaults; retain the other requirements.

For ordinary English body text, check 10–12 pt, an actual baseline distance of
120–145% of the font size, and a target of 45–90 characters per line. Use left
alignment unless an explicit governing style requires justification; enable the
appropriate language's hyphenation when justification is required. Apply Chinese
spacing and punctuation to Chinese passages; do not reinterpret the English
character-count target as a Chinese character limit.

The 15–18 px and long-form 16–20 px screen defaults are not PDF point-size
settings.

## Language routing

The templates take one switch, `cjk`, which `smart_engine.py` passes as
`-M cjk=true|false` after reading the source (or `--lang`). It selects the CTeX
`scheme` and therefore changes four things at once:

| | `cjk=true` (Chinese) | `cjk=false` (English) |
| :--- | :--- | :--- |
| CTeX `scheme` | `chinese` | `plain` |
| Heading, caption and box labels | Chinese | English |
| Leading | CTeX's 1.3 linespread | the class baseline (120–124%) |
| Body alignment | justified (LaTeX default) | ragged right (`ragged2e`) |

The 120–145% leading target and the 45–90 character target are scoped to English
body text, so a Chinese document keeps the CTeX leading convention. The switch
follows the dominant language: Chinese is chosen when ideographs make up at
least 20% of the ideograph-plus-letter count. A genuinely mixed document cannot
have two leading values at once, so `--linespread` overrides the routed default
when a governing style requires one value throughout. Code is stripped before
the language is counted, so an English document quoting a few Chinese characters
stays English.

## Measured presets

Measured on English (ragged right) and Chinese (justified) documents built from
the same body text:

| Style code | Class and options | Body size | Measured baseline | Leading | Measure | English chars/line | Chinese chars/line |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **`academic`** | `ctexart` two-column, 10 pt, A4 | 10 pt | 12.00 pt | 120.0% | 251 pt (8.8 cm/col) | 60 | 25 |
| **`book`** | `ctexbook`, 12 pt, A4 | 12 pt | 14.50 pt | 120.8% | 455 pt (16 cm) | 85 | 38 |
| **`tech_book`** | `ctexbook`, 11 pt, A4 | 11 pt | 13.60 pt | 124.2% | 441 pt (15.5 cm) | 88 | 40 |
| **`tech_report`** | `ctexart`, 12 pt, A4 | 12 pt | 14.50 pt | 120.8% | 455 pt (16 cm) | 85 | 38 |
| **`cv`** | `article` + `ctex`, 11 pt, A4 | 11 pt | 13.60 pt | 124.2% | 450 pt (15.8 cm) | 90 | 41 |

Chinese documents using the same presets measure 156.0% (`academic`), 157.1%
(`book`, `tech_report`) and 161.5% (`tech_book`, `cv`) with the CTeX linespread —
the Chinese convention, not a defect, but it does mean "the preset compiles" says
nothing about the English leading target.

## Pandoc compatibility

Each template carries the subset of Pandoc's own LaTeX prelude these presets
need, because a custom `--template` replaces Pandoc's default template entirely:

* `\tightlist`, and `\passthrough` (required as soon as `--listings` is used);
* `\newcounter{none}` guarded by `\@ifundefined{c@none}`, without which every
  table fails with `No counter 'none' defined`;
* the `secnumdepth` branch, so `--number-sections` actually controls numbering;
* `\pandocbounded`, which Pandoc ≥ 3 wraps around every image;
* the `CSLReferences` environment and citation commands used by `--citeproc`.

## Filters

* **`scripts/twocol_table.lua`** (`academic` only): rewrites Pandoc's
  `longtable` output into `tabularx` inside a `table` float, because `longtable`
  is not supported in two-column mode. Limitation: a `tabularx` block cannot
  break across pages, so a table taller than one column overflows with an
  overfull warning instead of continuing on the next page. For a long table in a
  two-column document, place it manually in a `table*` float or use a
  single-column preset.
* **`scripts/div_boxes.lua`**: maps fenced divs onto the tcolorbox environments a
  style actually defines, so a div whose class is not in the map renders as plain
  content instead of an undefined environment:

  | Style | Div classes | Environment |
  | :--- | :--- | :--- |
  | `book` | `definition`, `theorem`, `alert`, `note`, `tip` | `definitionBox`, `theoremBox`, `alertBox` |
  | `tech_book` | `note`, `tip` | `techNote` |
  | `tech_report` | `code`, `tip`, `note` | `codeBox`, `tipBox` |

## Citations

`--bibliography` (and optionally `--csl`) switches on `--citeproc`; with no flag
the engine uses the single `.bib` file found next to the source and warns when
several are present. Without either, Pandoc leaves `[@key]` in the text as-is:
the citation keys are preserved but no reference list is produced. The
`academic` template still loads `gbt7714` for a hand-written
`\bibliography{...}`; `--citeproc` and `gbt7714` are alternatives, and a GB/T
7714 numeric reference list needs a matching CSL file passed with `--csl`.

## Style detection

With `--style auto` the engine scores the first 3000 characters (lowercased) for
word-boundary keyword hits:

| Style | Keywords |
| :--- | :--- |
| **Academic** | abstract, introduction, reference, conclusion, method, doi, figure, table |
| **CV** | education, experience, skills, project, resume, curriculum vitae, contact, email |
| **Tech Report** | code, python, java, function, api, install, usage, guide, tutorial |
| **Book** | chapter, prologue, once upon a time, dialogue, story |
| **Tech Book** | o'reilly, technical, programming, software, hardware |

Text-like sources containing fenced code blocks get +5 for `tech_report` and
`tech_book`. Ties are resolved in the fixed priority `academic`, `cv`,
`tech_book`, `book`, `tech_report`; a score of zero across all styles falls back
to `tech_report`. Pass `--style` explicitly when detection matters.

## Style-specific features

* **Tech Report**: `listings` syntax highlighting; shell escape stays disabled.
  Inline code becomes `\lstinline` wrapped in `\passthrough`.
* **Book / Tech Book**: custom tcolorbox environments, reachable from Markdown
  through the div classes listed above.
* **Academic**: two-column layout with a single-column abstract, `gbt7714`.
* **CV**: `fontawesome5` icons and `paracol` for a split layout; both are opt-in
  and only appear in the commented usage examples. Page numbers stay on, because
  CVs are frequently longer than one page.
