# Research Analyst Workflows (V9.0)

## Phase 0: Alignment & SCQA (MANDATORY)
1. **SCQA Framing**: Define Situation, Complication, Question, and the overarching Answer.
2. **Hypothesis Matrix**: Generate 3-5 core strategic hypotheses in `hypothesis_matrix.json`.
3. **MECE Audit**: Use `logic-adversary` to audit the structural completeness of the research plan.
4. **Approval**: Use `ask_user` to finalize the SCQA and the initial hypothesis matrix.

## Mode A: Strategic Brief (标准报告 / 约 4000 字)
*Target: Rapid synthesis of core action titles and so-what analysis.*
...

## Mode B: The Partner's Deep Dive (深度研究 / 10000+ 字)
*Target: Strategic defensibility, non-consensus insight, and conclusive action.*

### Task 1: Intelligence Saturation & Hypothesis Testing
1. **OSINT Discovery**: Use `retrieval_specialist` to probe data specifically to confirm/refute the hypotheses.
2. **Evidence-Mesh**: Record every finding in `evidence_matrix.csv`.

### Task 2: Narrative Construction (Action-Title Driven)
1. **Action-Title Blueprint**: Create `outline.md` using COMPLETE logical statements as headers.
2. **Approval**: **Mandatory** `ask_user` review of headers.
3. **Recursive Drafting**:
   - Write chapter-by-chapter, each >= 1200 words.
   - **Mandatory "So-What" Block**: Every chapter ends with a strategic impact analysis.
   - Use `logic-adversary` to stress-test the argument between chapters.

### Task 3: Final Synthesis & Pythonic Assembly
1. **Fidelity Audit**: Verify every action title is supported by the data in `working_memory.json`.
2. **Gray Framework**: Synthesize the Ideal, Survival, and Exit strategies.
3. **Physical Assembly**: Execute `assembler.py` for a 1:1 merge.
4. **Hypothesis Closure**: Final status update for the hypothesis matrix.
5. **Outcome**: A definitive, partner-grade strategic report.
