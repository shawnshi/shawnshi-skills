# CLI Reference

## Advanced Options

| Option | Description | Status |
|--------|-------------|--------|
| `--skip-prompts` | Skip prompt generation step | ✅ Implemented |
| `--skip-images` | Skip image generation step | ✅ Implemented |
| `--regenerate 3,5` | Regenerate specific slides (comma-separated indices) | ✅ Implemented |
| `--model <name>` | Specify image generation model backend (default: `gemini`). Supported: `gemini`, `dalle3`, `sdxl`. | 🚧 Planned |
| `--editable-text` | **Experimental**: Generates background-only images and adds text as editable PowerPoint shapes. | 🚧 Planned |
| `--resume` | **Smart Resume**: Checks `status.json` and only generates pending/failed slides. | 🚧 Planned (basic skip-existing logic implemented) |
| `--layered` | Generate separate background and foreground element layers. | 🚧 Planned |

## Partial Workflows

| Command | Purpose | Status |
|---------|---------|--------|
| `python build-deck.py <dir>` | Full pipeline: Prompts → Images → PPTX/PDF | ✅ Implemented |
| `python build-deck.py <dir> --skip-prompts` | Skip prompt generation, run from existing prompts | ✅ Implemented |
| `python build-deck.py <dir> --skip-images` | Skip image generation, only merge existing images | ✅ Implemented |
| `python build-deck.py <dir> --regenerate 3,5` | Regenerate specific slides only | ✅ Implemented |
| `python generate-prompts.py <dir>` | Only generate prompt files from outline.md | ✅ Implemented |
| `python generate-images.py <dir>` | Generate images from existing prompts | ✅ Implemented |

