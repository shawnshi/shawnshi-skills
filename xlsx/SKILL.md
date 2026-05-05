---
name: xlsx
description: "Specialized utility for advanced manipulation, analysis, validation, visualization, and creation of spreadsheet files including XLSX, XLSM, CSV, and TSV. Use whenever the user needs Excel files with formulas, formatting, charts, pivot tables, data validation, financial presentation, or workbook QA."
---

<strategy-gene>
Keywords: Excel, XLSX, openpyxl, formulas, pivot table, chart validation
Summary: Build or audit spreadsheet assets with formula integrity, visible provenance, and mandatory workbook validation.
Strategy:
1. Plan workbook structure before editing: sheets, formulas, charts, pivot needs, sources, and validation commands.
2. Build with Python/openpyxl or pandas where appropriate, keeping formulas in Excel instead of silently precomputing values.
3. Validate with the workbook tools before delivery; never hand off a file with formula errors or broken charts.
AVOID: Do not deliver spreadsheets with formula errors, missing source citations, empty charts, text-formatted numbers, or skipped validation.
</strategy-gene>

# XLSX

Use this skill for professional spreadsheet creation and QA. The full historical playbook is preserved in `references/full_xlsx_playbook.md`; load it only when detailed styling recipes, command examples, or cookbook-level guidance are needed.

## When to Use
- Use for `.xlsx`, `.xlsm`, `.csv`, `.tsv`, formulas, charts, pivot tables, financial models, workbook formatting, validation, and data QA.
- Use when the user expects an Excel deliverable, not just a textual table.
- Use for spreadsheet repair when formulas, styles, charts, or workbook structure may be broken.

## Workflow
1. **Scope**: Identify input files, output workbook name, required sheets, source data, formulas, charts, and audience.
2. **Inspect**: For existing workbooks, inspect sheet names, dimensions, headers, formulas, styles, and chart objects before editing.
3. **Plan**: Define sheet-by-sheet structure, formulas, formats, validations, chart ranges, and source-citation strategy.
4. **Build**: Use Python with openpyxl/pandas for workbook creation, styling, formulas, and charts unless a specialized CLI tool is required.
5. **Validate per sheet**: After each substantive sheet, check formula references, numeric formats, merged cells, frozen panes, and source columns.
6. **Validate workbook**: Run available workbook validation commands, chart checks, and recalculation checks before delivery.
7. **Report**: Provide the output file path and a short validation summary.

## Resources
- Full cookbook: `references/full_xlsx_playbook.md`
- Pivot table protocol: `pivot-table.md`
- Workbook CLI: `scripts/KimiXlsx`
- Prefer current local runtime Python packages for `openpyxl` and `pandas`.

## Spreadsheet Rules
- External data must include source provenance, preferably with `Source Name` and `Source URL` columns or a dedicated `Sources` sheet.
- Numeric values used in formulas must be numeric cells, not text.
- Financial and fiscal tables should use currency/percentage formats where appropriate.
- Workbook design should hide gridlines for polished deliverables unless the user needs raw data review.
- Charts must be based on actual workbook ranges and must not be empty.
- Pivot tables require reading `pivot-table.md` first.

## Failure Modes
- **Formula error**: Fix the formula or regenerate the workbook; do not deliver.
- **Invalid workbook structure**: Regenerate from source code rather than patching broken XML manually.
- **Missing source provenance**: Add source columns or a `Sources` sheet before delivery.
- **Empty chart**: Correct chart range and rerun chart validation.
- **Ambiguous requirements**: Produce a workbook plan and ask only for the smallest missing decision.
- **Unsupported pivot/chart path**: Use the documented CLI path or clearly report the blocker.

## Output Contract
- Deliver at least one `.xlsx` file when the task is workbook creation or modification.
- Include validation evidence: formula check, structure validation, chart check when charts exist, and any unresolved limitations.
- Final workbook must open in Excel-compatible software without repair prompts.
- Do not create extra README-style files unless the user requested documentation.

## Telemetry
- When persistent logging is available, record workbook path, sheet count, validation commands, validation status, and unresolved risks.
