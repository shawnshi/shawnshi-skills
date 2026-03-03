---
name: monthly-personal-insights
description: 运用“多面体分析”审计 30 天表现的战略元分析器，旨在解码用户与 AI 的交互协作模式。
triggers: ["出具我本月的系统交互报告", "解码我这段时间的操作摩擦", "生成本月元分析HTML报告", "分析我的AI指令依赖度"]
---

# monthly-personal-insights

## 🧠 Architecture Vision
Act as a "Battle-Hardened Strategic Architect". Your goal is to calculate the **"ROI of Interaction"** and provide a comprehensive audit of the user's digital footprint.
This skill generates an interactive HTML report that analyzes sessions across 6 dimensions (Facets) to identify patterns, frictions, and growth opportunities. It features a layered architecture separating core logic (`core/engine.py`) from presentation (`assets/template.html`).

## 📋 Execution Workflow
- [ ] **Stage 1: Processing Pipeline**
    *   Execute `python C:\Users\shich\.gemini\skills\monthly-personal-insights\analyze_insights_v4.py` for a full audit using LLM facet extraction OR `python C:\Users\shich\.gemini\skills\monthly-personal-insights\generate_final_report.py` for a quick cached rendering.
    *   The `core.engine` script automatically scrapes `gemini --list-sessions` and parses the latest `logs.json`.
- [ ] **Stage 2-5: Core Engine (Automated)**
    *   Filtering sessions (excludes agent sub-sessions, short/empty sessions).
    *   Metadata extraction (duration, tokens, tool usage).
    *   Robust JSON Facet Extraction using LLM (Goal, Satisfaction, Outcome, Friction, Type, Success).
    *   Aggregate Analysis.
- [ ] **Stage 6: Rendering**
    *   The scripts invoke the external HTML template `assets/template.html` to generate an interactive HTML report at `C:\Users\shich\.gemini\skills\monthly-personal-insights\reports\YYYYMMDD_Strategic_Audit.html` or its Cached counterpart.

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
