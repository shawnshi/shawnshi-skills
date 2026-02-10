# Advanced Workflows & Modification

## Slide Modification

### Edit Visuals
To regenerate specific slides (e.g., slide 3 and 5):
1. Modify `prompts/NN-slide-slug.md` if needed.
2. Run:
   ```bash
   /baoyu-slide-deck slide-deck/topic-slug/ --regenerate 3,5
   ```

### Switch Model
Regenerate a specific slide using a different artistic style:
```bash
/baoyu-slide-deck slide-deck/topic-slug/ --regenerate 3 --model dalle3
```

## Text Overlay Logic
If `--editable-text` was used:
- The background image will NOT contain text.
- `scripts/build-deck.py` will read `outline.md` and insert native PowerPoint text boxes.
- To edit text: **Open the PPTX file directly**. Do not regenerate.
