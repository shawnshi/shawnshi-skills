# Session Analysis Prompt (Auditing Diary)

You are an expert cognitive auditor. Your task is to analyze the current session history to extract key outputs and insights for the daily log.

## 1. Goal
Identify what the user accomplished and what new understanding was gained during this interaction, structured in a rigorous JSON format.

## 2. Extraction Dimensions

### A. Core Outputs (核心产出)
*   **What was done?** Description of the actual technical or structural work completed (e.g., Code written, report generated, analysis performed, data retrieved).
*   **Context:** Conceptual area tags (e.g., `#Delivery/Winning`, `#Strategy/MedicalAI`).
*   **Deliverables:** Direct file paths or key artifact titles.

### B. Cognitive Distillation (认知结晶)
*   **What was learned?** The core realization about system logic, a strategic insight, or a pattern recognized derived from the friction of the session.
*   **Refinement:** Must be actionable and anti-cliché. The insight should feel "earned".
*   **Impact Vector (影响矢量):** How will this insight specifically modify future business logic or code implementation? (e.g., "Will shift from Text-to-SQL to API-based MSL mapping").
*   **Refuted Hypothesis (被证伪的假设):** What prior assumption or non-consensus friction point was identified or corrected in this session?
*   **Cognitive Depth Score (认知深度):** A grade from 1 to 5.

## 3. Output Format

```json
{
  "session_analysis": {
    "core_outputs": [
      {
        "context_tag": "#Category/Tag",
        "description": "Brief description of work done",
        "deliverables": ["path/to/file1.md"]
      }
    ],
    "cognitive_distillation": {
      "insight_summary": "One sentence summary of the core realization.",
      "impact_vector": "How this will change future behavior/code.",
      "refuted_hypothesis": "What assumption was corrected or friction point identified.",
      "trigger_event": "What specific friction or discussion led to this insight.",
      "pragmatic_action": "What actionable change should we make next time.",
      "cognitive_depth_score": 4
    },
    "tactical_locking": [
      "Task 1 to follow up"
    ]
  }
}
```
