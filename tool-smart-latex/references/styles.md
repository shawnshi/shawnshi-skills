---
title: Style References
date: 2026-02-21
status: Active
author: System
---

# Style References

This document lists the available document styles for the Smart Doc LaTeX engine.

## Supported Styles

| Style Code | Description | Target Audience | Template File |
| :--- | :--- | :--- | :--- |
| **`book`** | Standard book layout. Elegant, readable, suitable for novels or general non-fiction. | General Readers | `templates/book.tex` |
| **`tech_book`** | O'Reilly-style technical book. Features code blocks, sidebars, and tips. | Developers, Engineers | `templates/tech_book.tex` |
| **`academic`** | Academic paper/journal style. Two-column options, abstract, formal headings. | Researchers, Students | `templates/academic.tex` |
| **`tech_report`** | Internal technical report. Clean, business-oriented layout. | Business, Enterprise | `templates/tech_report.tex` |
| **`cv`** | Curriculum Vitae / Resume. Compact, skill-focused layout. | Job Seekers | `templates/cv.tex` |

## Style Detection Logic

If the style is set to `auto`, the engine (`smart_engine.py`) analyzes the first 3000 characters (lowercased) for keyword frequency:

| Style | Keywords |
| :--- | :--- |
| **Academic** | abstract, introduction, reference, conclusion, method, doi, figure, table |
| **CV** | education, experience, skills, project, resume, curriculum vitae, contact, email |
| **Tech Report** | code, python, java, function, api, install, usage, guide, tutorial |
| **Book** | chapter, prologue, once upon a time, dialogue, story |
| **Tech Book** | o'reilly, technical, programming, software, hardware |

Additionally, Markdown files containing fenced code blocks (` ``` `) receive a +5 bonus for both `tech_report` and `tech_book`.

The style with the highest total score wins. If all scores are 0, defaults to `tech_report`.

## Template Features

All templates support:
*   **Chinese Support**: Native CTeX environment.
*   **Pandoc Compatibility**: `\tightlist`, `\newcounter{none}` patches included.
*   **Hyperlinks**: Clickable TOC and cross-references.

Style-specific features:
*   **Tech Report**: `minted` syntax highlighting (requires `-shell-escape`).
*   **Book / Tech Book**: Custom tcolorbox environments (definition, alert, note boxes).
*   **Academic**: Two-column layout with single-column abstract, `gbt7714` bibliography.
*   **CV**: `fontawesome5` icons, `paracol` two-column layout.
