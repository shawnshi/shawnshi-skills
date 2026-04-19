# Research Analyst Workflows (V18.0)

## Mandatory Assets
Every project must maintain these files from boot to delivery:
- `working_memory.json`
- `hypothesis_matrix.json`
- `evidence_matrix.csv`
- `outline.md`
- `implementation_plan.md`
- `chapter_*.md` or mode-equivalent section files
- `final_report.md`

## Phase 0: Alignment & Boot
1. Confirm audience, budget, attack focus, target length, and mode.
2. Run `memory_manager.py init --path <project_path> --topic <topic> --mode <mode>`.
3. Run `blackboard.py init --topic <topic> --mode <mode>`.
4. Write the alignment packet into blackboard `alignment`.

## Phase 1: Hypotheses & Evidence
1. Generate 3-5 strategic hypotheses and persist them in `hypothesis_matrix.json`.
2. Record every sourced finding in `evidence_matrix.csv`.
3. Update `working_memory.json` with insights, entities, and technical anchors.
4. Sync evidence summaries to blackboard `evidence.*`.

## Phase 2: Logic Collision
1. Produce one `core_judgment` and at least one `second_hop_inference`.
2. Write `outline.md` with full-sentence action titles.
3. Write `implementation_plan.md` with mode, storyline, and approval gates.
4. Run `blackboard_validate.py --strict` before any drafting.

## Mode A: Strategic Brief
Target: 1500-2500 words.
1. Draft in one pass after blackboard passes.
2. Keep 3-5 sections only.
3. Must contain: center judgment, pessimistic ROI, action levers, residual risk.

## Mode B: The Partner's Deep Dive
Target: 8000+ words.
1. Draft chapter-by-chapter.
2. Each chapter should usually exceed 1200 words.
3. Stress-test between chapters and update `working_memory.json` after every chapter.

## Mode C: Board Memo
Target: 1000-1800 words.
1. Draft in one pass.
2. Open with `紧急预警` and `董事会动作建议`.
3. Bias toward decision cadence, not narrative breadth.

## Final Synthesis & Gate
1. Run `assembler.py --path <project_path> --mode <mode> --output final_report.md`.
2. Run `strategy_gate.py --path <project_path>\final_report.md --mode <mode> --blackboard <blackboard_path> --strict`.
3. Only ship if strategy gate returns `pass`.
4. Freeze project state to `🔴 归档冻结` after delivery.
