---
name: drawio
description: Always use when user asks to create, generate, draw, or design a diagram, flowchart, architecture diagram, ER diagram, sequence diagram, class diagram, network diagram, mockup, wireframe, or UI sketch, or mentions draw.io, drawio, drawoi, .drawio files, or diagram export to PNG/SVG/PDF.
---

# Draw.io Diagram Skill (V11.0 Advanced Semantic)

Generate professional draw.io diagrams as native `.drawio` files. This version supports **Visual Styles** (Blueprint, Dark Terminal) and **Semantic Shapes** for AI/Agent architectures.

## Phase 1: Context Routing (MANDATORY)

**STOP.** Do not start generating XML immediately. You MUST first read the specific reference files that match the user's diagram request.

### 1. Routing by Diagram Type
Determine the diagram type and call the `read_file` tool on the corresponding path:
- **Flowchart (流程图/工作流)**: `C:\Users\shich\.gemini\skills\drawio\references\type-flowchart.md`
- **Sequence Diagram (时序图/调用链)**: `C:\Users\shich\.gemini\skills\drawio\references\type-sequence.md`
- **ER Diagram (实体关系图/数据表)**: `C:\Users\shich\.gemini\skills\drawio\references\type-er.md`
- **Medical IT Architecture (架构图/拓扑)**: `C:\Users\shich\.gemini\skills\drawio\references\patterns-medical.md`
- **AI / Agent Architecture (智能体/RAG)**: `C:\Users\shich\.gemini\skills\drawio\references\patterns-agentic.md`
- **Modifying an existing diagram**: `C:\Users\shich\.gemini\skills\drawio\references\incremental-edit.md`

### 2. Routing by Visual Style
If the user specifies a style (e.g., `--style blueprint`), you MUST read the corresponding style reference:
- **Blueprint**: `C:\Users\shich\.gemini\skills\drawio\references\style-blueprint.md`
- **Dark Terminal**: `C:\Users\shich\.gemini\skills\drawio\references\style-dark-terminal.md`

*Note: You MUST ALWAYS read `C:\Users\shich\.gemini\skills\drawio\references\semantic-colors.md` and `C:\Users\shich\.gemini\skills\drawio\references\xml-advanced.md` before generating any complex diagram.*

## Phase 2: Generating XML & Writing

1. **Generate the draw.io XML** based on the loaded references.
2. **High-Fidelity Rules**:
   - Use **Semantic Shapes**: Double border for LLMs, Hexagon for Agents, Ringed Cylinders for Vector Stores.
   - Use **Flow Semantics**: Color-code edges (Arctic Blue for Read/Write, Cherry Pink for Control).
3. **Output Path**: `C:\Users\shich\.gemini\diagrams\{content-theme}_{YYYY-MM-DD}.drawio`.
   - Use a descriptive slug for the theme (e.g., `rag-pipeline`).
   - Use the current date in ISO format.
   - If the directory does not exist, create it first using `run_shell_command("mkdir -Force ...")`.
4. **Write**: Save the XML using `write_file`.

### Diagram Quality Pre-flight Checklist:
- [ ] Filename follows the `{theme}_{date}.drawio` pattern.
- [ ] No `<!-- XML comments -->` anywhere (they cause parse errors).
- [ ] Every edge `mxCell` has a child `<mxGeometry relative="1" as="geometry" />`.
- [ ] Every node has an explicit `fontFamily` defined in its style (e.g., Inter, SF Mono).
- [ ] Absolutely NO default draw.io blue. Only use colors from `semantic-colors.md` or style references.

## Phase 3: Completion

Inform the user that the `.drawio` file has been generated and provide the absolute path. Mention that they can open this file in any draw.io editor (desktop or web).

## Usage Examples
- `generate a RAG pipeline diagram --style blueprint` -> Result: `rag-pipeline_2026-04-11.drawio`
- `draw a multi-agent collaboration flowchart --style dark-terminal` -> Result: `multi-agent-flow_2026-04-11.drawio`
- `visualize the medical integration engine architecture` -> Result: `medical-integration_2026-04-11.drawio`

## Telemetry (Mandatory)
Write telemetry data to `C:\Users\shich\.gemini\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`:
`{"skill_name": "drawio", "status": "success", "duration_sec": [ESTIMATE]}`
