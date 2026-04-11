# Agentic AI Architecture Patterns

When generating diagrams for AI Agents, RAG pipelines, or LLM-based systems, use these semantic shapes and patterns.

## Semantic Shape Vocabulary

| Component | draw.io Style String | Rationale |
|-----------|----------------------|-----------|
| **LLM / Foundation Model** | `rounded=1;whiteSpace=wrap;double=1;strokeWidth=2;` | Double border signifies core reasoning engine. |
| **Agent / Orchestrator** | `shape=hexagon;whiteSpace=wrap;` | Hexagon represents active decision-making/routing. |
| **Vector Database** | `shape=cylinder3;whiteSpace=wrap;size=10;strokeWidth=2;` | Cylinder with inner rings signifies structured embedding storage. |
| **Memory (Short-term)** | `rounded=1;whiteSpace=wrap;dashed=1;` | Dashed border for transient state. |
| **Knowledge Base (RAG)** | `shape=mxgraph.flowchart.multi-document;` | Stacked docs for external knowledge. |
| **Tool / Function** | `shape=process;whiteSpace=wrap;` | Process shape for deterministic execution. |
| **Prompt / Template** | `shape=note;whiteSpace=wrap;` | Note shape for text-based instructions. |

## Pattern 1: Five-Layer Agent Model

Standard layout for autonomous agents. Use horizontal swimlanes.

```
[Layer 1: Input]  -> User Query, File Upload, API Event
[Layer 2: Agent]  -> Planner / Orchestrator (Hexagon)
[Layer 3: Memory] -> Buffer, Long-term Context (Cylinder)
[Layer 4: Tools]  -> Search, Code Exec, SQL (Process)
[Layer 5: Output] -> Generated Response, Action Execution
```

## Pattern 2: Agentic RAG Pipeline

```
User Query -> [Planner Agent]
                 | ↔ [Vector Store] (Search)
                 | ↔ [Web Search Tool]
                 | ↔ [Refinement Loop] (Curved Arrow)
              -> Final Synthesis (LLM Node)
```

## Flow Semantics (Lines)

| Flow Type | style String Fragment | Use Case |
|-----------|-----------------------|----------|
| **Primary Data Flow** | `strokeWidth=2;strokeColor=#808080;` | Main request/response path. |
| **Memory Read** | `strokeColor=#6c8ebf;` | Retrieving context from stores. |
| **Memory Write** | `strokeColor=#6c8ebf;dashed=1;dashPattern=5 3;` | Persistent storage operations. |
| **Refinement/Loop** | `curved=1;edgeStyle=orthogonalEdgeStyle;` | Iterative reasoning or feedback. |
| **Trigger/Control** | `strokeColor=#b85450;` | Error handling or circuit breaking. |
