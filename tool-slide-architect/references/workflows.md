# Blueprint-Only Workflows

## Standard Flow

1. Draft `outline.md` using `references/outline-template.md`.
2. Validate it:
   ```bash
   python scripts/validator.py path\to\outline.md
   ```
   Use `--allow-placeholders` only when checking the reusable template itself.
3. Package the validated final outline:
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

No slide image generation or PPTX assembly is part of this workflow. Build a physical `.pptx` with an available presentation capability after the blueprint passes validation.
