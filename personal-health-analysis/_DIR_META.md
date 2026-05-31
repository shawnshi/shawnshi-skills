# _DIR_META.md

## Architecture Vision
Core skill directory for Garmin Health Analysis.
Orchestrates data fetching, visualization, and strategic health insights via
the GEB-Flow architecture: Auth → Data → Intelligence → Presentation.

## Member Index
- `SKILL.md`: [Manifest] Skill definition, user query mapping, and workflow instructions.
- `README.md`: [Docs] High-level capability overview (Chinese).
- `scripts/`: [Logic] Python scripts for auth, data fetching, query, analysis, visualization, and FHIR export.
- `references/`: [Knowledge] Health analysis frameworks, API docs, and extended capabilities reference.
- `agents/`: [Config] Gemini agent configuration (gemini.yaml).
- `output/`: [Output] Generated HTML dashboards, FHIR exports, and downloaded activity files.
- `install.sh`: [Setup] Unix installation script (pip dependencies).
- `install.ps1`: [Setup] Windows PowerShell installation script.

> ⚠️ **Protocol**: Sync this file whenever directory content or responsibility shifts.
