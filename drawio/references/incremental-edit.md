# Incremental Edit Protocol

When the user requests modifications to an **existing** `.drawio` diagram (e.g., "add a module", "move this", "change the color"), follow this protocol instead of regenerating from scratch:

### Read-Modify-Write Cycle

1. **Read** the existing `.drawio` file using the view/read tool
2. **Parse** the XML mentally — identify all `mxCell` ids, their positions, and parent-child relationships
3. **Modify only the affected cells**:
   - To **add** a node: create a new `mxCell` with an ID that does not conflict with existing IDs (use `new_1`, `new_2`, etc. or descriptive IDs)
   - To **move** a node: change only its `x`/`y` in `mxGeometry`; do NOT change its `id` or `style`
   - To **delete** a node: remove its `mxCell` AND all edges where it appears as `source` or `target`
   - To **restyle** a node: change only the `style` attribute; preserve everything else
4. **Preserve** all unmentioned cells — their IDs, positions, styles, and parent relationships MUST remain identical
5. **Write** the complete modified XML back to the same file path

### Conflict avoidance

- Before adding nodes, scan all existing `id` attributes to avoid collisions
- When adding nodes near existing ones, respect the Layout Guidelines (200px horizontal, 120px vertical gaps)
- When adding nodes to a container, recalculate the container’s `width`/`height` if the new child extends beyond current bounds
- After adding edges, verify that both `source` and `target` IDs exist in the file

### When to full-regenerate instead

- User says "redo", "start over", "重新画"
- The requested change affects >50% of existing nodes
- The diagram type changes (e.g., flowchart → sequence diagram)