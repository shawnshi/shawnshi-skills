# CLI Reference

## Supported Commands

| Command | Purpose |
|---------|---------|
| `python scripts\validator.py <outline.md>` | Validate the blueprint schema and special-slide rules |
| `python scripts\validator.py references\outline-template.md --allow-placeholders` | Validate the reusable canonical template |
| `python scripts\build-deck.py <deck-dir>` | Validate and package the blueprint into `blueprint_bundle.json` |
| `python scripts\build-deck.py <deck-dir> --output custom.json` | Write the package to a custom JSON filename |

## Notes

- `build-deck.py` no longer renders PPTX files.
- `outline.md` is required.
- Validation failure aborts packaging.
- Validator input is read-only; it does not normalize or rewrite the source file.
- Structural errors return a non-zero exit code. Style and density warnings do not.
- The package output is blueprint metadata, style metadata, and structured slide blocks.
