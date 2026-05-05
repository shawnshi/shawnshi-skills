---
name: academic-deep-research
description: "Universal deep research agent team. Use for rigorous academic research, quick briefs, paper review, literature review, fact-checking, Socratic guided research dialogue, and systematic review or meta-analysis. Covers research question formulation, methodology design, literature search, source verification, cross-source synthesis, risk of bias assessment, APA 7.0 report compilation, editorial review, ethics review, and monitoring. Triggers on: research, deep research, literature review, systematic review, meta-analysis, PRISMA, evidence synthesis, fact-check, guide my research, 研究, 深度研究, 文献回顾, 系统性回顾, 后设分析, 事实查核, 研究方向."
---

<strategy-gene>
Keywords: 深度研究, PRISMA, 文献综述, 13-agent, 证据等级
Summary: 调度学术研究管线，从研究问题澄清到证据综合与 APA 报告交付。
Strategy:
1. 先判定模式：socratic、quick、full、review、lit-review、fact-check、systematic-review。
2. 建立 Evidence-Mesh：检索式、纳排标准、证据等级、冲突来源和限制必须可追踪。
3. 在 scoping、analysis、review 三处执行反证与伦理检查。
AVOID: 严禁编造引文；禁止把低质量来源伪装成 Tier 1；禁止跳过方法透明度。
</strategy-gene>

# Deep Research

Universal academic research workflow for evidence-backed synthesis. The full legacy playbook is preserved in `references/full_deep_research_playbook.md`; load it only when detailed mode tables, agent prompts, or examples are required.

## When to Use
- Use for deep research, literature review, systematic review, meta-analysis, PRISMA work, evidence synthesis, fact-checking, research design, or guided research-question formation.
- Prefer `socratic` mode when the user has a vague interest, unclear research question, or asks to be guided.
- Prefer `academic-paper-reader` for deeply understanding one paper.
- Prefer `academic-paper-writer` when the primary task is drafting or revising a paper from an already available evidence base.

## Modes
| Mode | Use When | Required Output |
|---|---|---|
| `socratic` | Topic is vague or exploratory | Research-question brief and next-step map |
| `quick` | User needs a short evidence brief | BLUF, key evidence, caveats |
| `full` | User asks for comprehensive research | APA-style report with citations |
| `review` | User provides a paper or claim set | Verdict, strengths, weaknesses, citation risk |
| `lit-review` | User asks for state of field | Thematic synthesis and gap map |
| `fact-check` | User asks whether claims are true | Claim-by-claim verdict and support |
| `systematic-review` | User asks PRISMA/meta-analysis | Protocol, search log, screening, RoB/GRADE |

## Workflow
1. **Scope**: Convert the prompt into a bounded research question. Use FINER-style checks for feasibility, importance, novelty, ethics, and relevance.
2. **Plan**: Define evidence tiers, search strategy, inclusion/exclusion criteria, and expected output shape.
3. **Investigate**: Search and screen sources. Track source title, author, year, venue, URL/DOI, evidence type, and reason for inclusion.
4. **Verify**: Grade source quality, detect predatory or weak evidence, and mark conflicts of interest.
5. **Synthesize**: Build claims only from cited evidence. Separate consensus, controversy, gaps, and weak signals.
6. **Red Team**: Challenge the research question, source base, causal claims, and hidden assumptions before finalizing.
7. **Compose**: Deliver the requested artifact with citations, limitations, and reproducibility notes.

## Resources
- Main detailed playbook: `references/full_deep_research_playbook.md`
- Evidence standards: `references/source_quality_hierarchy.md`, `references/cross_agent_quality_definitions.md`
- Methods: `references/methodology_patterns.md`, `references/systematic_review_protocol.md`, `references/systematic_review_toolkit.md`
- Ethics and reporting: `references/ethics_checklist.md`, `references/equator_reporting_guidelines.md`, `references/apa7_style_guide.md`
- Socratic mode: `references/socratic_mode_protocol.md`, `references/socratic_questioning_framework.md`
- Writing quality handoff: `academic-paper-writer/references/writing_quality_check.md`
- Downstream paper-writing handoff: `academic-paper-writer/SKILL.md`

## Handoff Contract
When handing research to `academic-paper-writer`, provide:
- research question brief
- search strategy and screening criteria
- annotated bibliography with source grades
- synthesis matrix
- limitations and uncertainty notes
- citation-risk flags

## Failure Modes
- **Insufficient evidence**: Return a limited brief with explicit gaps instead of inventing support.
- **Low-quality source base**: Down-rank conclusions and label evidence as tentative.
- **Conflicting evidence**: Present both sides with source quality comparison.
- **Unclear question**: Switch to `socratic` mode and produce a narrowed question before broad research.
- **Systematic review infeasible**: Explain missing protocol, database access, screening capacity, or statistical requirements.

## Output Contract
- Every substantive factual claim must be traceable to a source.
- Final output must include limitations, evidence quality, and uncertainty.
- Systematic review outputs must include protocol, search terms, screening logic, PRISMA-style counts, risk of bias, and synthesis method.
- Fact-check outputs must use claim-level verdicts, not a single blended conclusion.

## Telemetry
- Record mode, topic, source count, evidence tiers, and final status in the local skill-audit telemetry path when persistent logging is available.
