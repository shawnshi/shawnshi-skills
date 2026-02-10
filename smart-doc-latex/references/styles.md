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

If the style is set to `auto`, the engine analyzes the first 3000 characters for keywords:
*   **Academic**: abstract, introduction, doi, figure
*   **CV**: education, skills, experience, resume
*   **Tech Report**: code, api, install, usage
*   **Book**: chapter, prologue, story

## Template Features

All templates support:
*   **Chinese Support**: Native CTeX environment.
*   **Syntax Highlighting**: For code blocks (minted or listings).
*   **Hyperlinks**: Clickable TOC and cross-references.
