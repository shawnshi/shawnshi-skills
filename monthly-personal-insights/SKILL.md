---
name: monthly-personal-insights
description: Strategic Meta-Analyst that audits 30-day performance using "Facet-based Analysis" to decode user-AI interaction patterns, minimize system entropy, and maximize project velocity. Generates an interactive HTML report.
---

# monthly-personal-insights

## 🧠 Architecture Vision
Act as a "Battle-Hardened Strategic Architect". Your goal is to calculate the **"ROI of Interaction"** and provide a comprehensive audit of the user's digital footprint.
This skill generates an interactive HTML report that analyzes sessions across 6 dimensions (Facets) to identify patterns, frictions, and growth opportunities.

## 📋 Execution Workflow
- [ ] **Stage 1: Collection**
    *   Execute `python C:\Users\shich\.gemini\skills\monthly-personal-insights\analyze_insights_v4.py`.
    *   This script scrapes `gemini --list-sessions` and reads `logs.json`.
- [ ] **Stage 2-5: Processing (Automated in script)**
    *   Filtering sessions (excludes agent sub-sessions, short/empty sessions).
    *   Metadata extraction (duration, tokens, tool usage).
    *   Facet Extraction using LLM (Goal, Satisfaction, Outcome, Friction, Type, Success).
    *   Aggregate Analysis.
- [ ] **Stage 6: Rendering**
    *   The script generates an interactive HTML report at `C:\Users\shich\.gemini\skills\monthly-personal-insights\reports\YYYYMMDD_Strategic_Audit.html`.

## 📝 Analysis Dimensions (Facets)
The analysis engine categorizes every session into:
1.  🎯 **Goal Category**: (13 types e.g., `implement_feature`, `debug_investigate`)
2.  😊 **Satisfaction**: (6 levels e.g., `frustrated` → `delighted`)
3.  ✅ **Outcome**: (5 types e.g., `completed`, `partial`)
4.  ⚠️ **Friction Type**: (12 types e.g., `misunderstood_request`, `buggy_code`)
5.  📋 **Session Type**: (5 types e.g., `single_task`, `exploratory`)
6.  🏆 **Success Type**: (7 types e.g., `excellent_reasoning`, `high_velocity`)

## 📊 Report Contents
- **Statistics Dashboard**: Sessions, messages, usage duration, token consumption, Git activity.
- **Visual Charts**: Daily activity curve, tool usage distribution, language breakdown, satisfaction spread.
- **Strategic Insights**: Domain identification, interaction style profile, `gemini.md` improvement suggestions, and "Interesting Moments" easter egg.

## 🔄 Post-Audit Trigger
After the script finishes, inform the user where the HTML report is located and offer to open it or update `memory.md` with the new findings.
