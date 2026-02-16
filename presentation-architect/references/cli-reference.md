# CLI Reference

## Advanced Options

| Option | Description |
|--------|-------------|
| `--model <name>` | Specify image generation model backend (default: `gemini`). Supported: `gemini`, `dalle3`, `sdxl`. |
| `--editable-text` | **Experimental**: Generates background-only images and adds text as editable PowerPoint shapes. Higher quality text, easier to update. |
| `--resume` | **Smart Resume**: Checks `status.json` in the deck directory and only generates images for slides that are pending or failed. Ideal for large decks or network interruptions. |
| `--layered` | Generate separate background and foreground element layers (if supported by model). |

## Partial Workflows

| Command | Purpose |
|---------|---------|
| `/slide-deck path/to/content.md --outline-only` | Only generate `outline.md` for review. |
| `/slide-deck path/to/content.md --prompts-only` | Generate prompts but do not call image API. |
| `/slide-deck slide-deck/topic-slug/ --images-only` | Resume image generation from existing prompts. |
| `/slide-deck slide-deck/topic-slug/ --regenerate 3,5` | Specific slide regeneration. |
