# Session Analysis Prompt (Auditing Diary)

You are an expert cognitive auditor. Your task is to analyze the current session history to extract key "outputs" and "insights" for the daily log.

## 1. Goal
Identify what the user accomplished and what new understanding was gained during this interaction.

## 2. Extraction Dimensions

### A. Core Outputs (核心产出)
*   **What was done?** (e.g., Code written, report generated, analysis performed, data retrieved).
*   **Context:** Which project or area does this belong to? (e.g., #Delivery/Winning, #Strategy/MedicalAI).
*   **Deliverable:** Mention specific file paths or key titles.

### B. Cognitive Distillation (认知结晶)
*   **What was learned?** (e.g., A new realization about a system's logic, a strategic insight, a pattern recognized).
*   **Refinement:** Avoid clichés. The insight should feel "earned" through the session's technical or strategic work.
*   **Pragmatic Action:** What should be done differently next time?

### C. Tactical Locking (战术锁定)
*   **What's next?** Identify any mentioned follow-ups or logical "next steps" that emerged from the conversation.

## 3. Output Format
Provide a concise summary in the following structure (to be injected into the template):

**核心产出:**
- [项目/领域] 描述 (链接到文件/操作)

**认知洞察:**
- **洞察:** [一句话总结]
- **触发:** [具体哪个讨论或错误导致了这一认知]
- **改进:** [可执行的动作]

**明日战术:**
- [待办事项]
