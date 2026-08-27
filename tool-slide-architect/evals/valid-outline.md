<DECK_METADATA>
Schema_Version: 2
Topic: Canonical schema validation
Audience: Skill maintainers
Objective: Verify deterministic v2 parsing and packaging
Occasion: Release-candidate structural review
Deck_Mode: full
Duration_Minutes: 8
Language: English
Aspect_Ratio: 16:9
Confidentiality: internal
Status: final
Slide_Count: 3
Generated: 2026-08-26
Template_Ref: canonical-v2-test-fixture
Decision_Owner: Skill maintainer
Source_Cutoff: 2026-08-26
Must_Keep: Evidence IDs and stable slide IDs
Deck_ID: TSA-EVAL-001
Revision: 2.0
Prepared_By: Test suite
Reviewed_By: Test suite
</DECK_METADATA>

<STYLE_INSTRUCTIONS>
Style_ID: custom
Design_Aesthetic: Restrained technical documentation
Background: White
Typography: System sans serif
Color_Palette: Neutral gray with one blue accent
Density: balanced
Citation_Treatment: visible-footer
Brand_Rules: Use no external logos or unlicensed assets
Accessibility: Maintain readable type, contrast, labels, and non-color cues
</STYLE_INSTRUCTIONS>

---
Slide_ID: SLD-fixture-cover
Type: Cover
Page: 1
---

// NARRATIVE
[Goal]: Introduce the v2 structural validation task.
[Title]: Validate one canonical blueprint contract

// VISUAL
[Layout]: title-hero
[Visual Description]: Centered title with a small schema-version label.
[Chart]: none
[Assets]:
- A1 | generated geometric rule | owned | not-required

// DELIVERY
[Speaker Notes]: Explain that this fixture tests structural behavior rather than release readiness.
[Delivery Notes]: Move directly to the evidence page.

// END SLIDE

---
Slide_ID: SLD-fixture-evidence
Type: Data
Page: 2
Section: Structural validation
---

// NARRATIVE
[Goal]: Demonstrate structured claims, evidence, and references.
[Title]: Evidence IDs make claim support machine-checkable
[Takeaway]: A verified claim must resolve to an evidence record on the same slide.

// CONTENT
[Body]: The fixture links one verified fact to one dated local source and keeps unresolved items explicit.
[Action]: Preserve the identifiers when revising prose.

// EVIDENCE
[Claims]:
- C1 | fact | verified | The fixture uses Schema Version 2 | E1
[Evidence]:
- E1 | Local v2 fixture | 2026-08-26 | Structural parser behavior | evals/valid-outline.md
[Open Items]:
none
[Risk Flags]:
none

// VISUAL
[Layout]: custom:evidence-ledger
[Visual Description]: One claim card linked to one source record with visible IDs.
[Chart]: none

// DELIVERY
[Speaker Notes]: Point out that the source proves structure only and does not certify presentation quality.
[Delivery Notes]: Keep the scope statement explicit.

// END SLIDE

---
Slide_ID: SLD-fixture-decision
Type: Decision
Page: 3
Section: Structural validation
---

// NARRATIVE
[Goal]: Close with a bounded decision request.
[Title]: Adopt v2 as the structural exchange contract
[Takeaway]: Packaging may proceed only after structural errors are cleared.

// CONTENT
[Body]: The bundle remains a presentation blueprint and does not claim to be a rendered PPTX.
[Decision]:
- D1 | approve | Use v2 for subsequent blueprint fixtures | Skill maintainer | 2026-08-26
[Action]: Record any visual or business-quality review separately from structural validation.

// EVIDENCE
[Claims]:
- C1 | recommendation | partial | Use the v2 contract for deterministic downstream parsing | E1
[Evidence]:
- E1 | Local v2 fixture | 2026-08-26 | Structural parser behavior | evals/valid-outline.md
[Open Items]:
- O1 | decision | Confirm the downstream renderer adapter owner | Skill maintainer | unscheduled
[Risk Flags]:
- R1 | reputation | medium | Structural pass could be mistaken for release approval | Keep validation_scope visible in every report and bundle

// VISUAL
[Layout]: decision-card
[Visual Description]: A single decision request with scope and risk callouts.
[Chart]: none

// DELIVERY
[Speaker Notes]: State the requested contract decision and the remaining human review boundary.
[Delivery Notes]: Do not claim that a physical deck was generated or approved.

// END SLIDE
