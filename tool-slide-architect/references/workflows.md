# Blueprint-Only Workflows

## Standard Flow

1. Draft `outline.md` using `references/outline-template.md`.
2. Validate it:
   ```bash
   python scripts/validator.py path\to\outline.md
   ```
3. Package it:
   ```bash
   python scripts/build-deck.py path\to\deck-dir
   ```
4. Review `blueprint_bundle.json` and the validated `outline.md`.

## Revision Flow

When revising a deck:
1. Edit `outline.md`
2. Re-run the validator
3. Re-run `build-deck.py`

## Output

The workflow only emits blueprint assets:

- `outline.md`
- `blueprint_bundle.json`

No slide image generation or PPTX assembly is part of the default workflow.
