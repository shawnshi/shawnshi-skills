# Troubleshooting & Advanced Usage

## Common Issues

### 1. "img2pdf not found"
**Cause**: The library is not installed in the current environment.
**Solution**: Run `pip install img2pdf`. If you are using `uv`, run `uv pip install img2pdf`.

### 2. PDF Creation Fails (Numerical Sort)
**Cause**: If the images are not named `0.jpg, 1.jpg...`, the numerical sort might fail.
**Solution**: The script will fallback to alphabetical sort. Ensure no unrelated `.jpg` files are in the folder.

### 3. Early Termination (404 Error)
**Cause**: The standard repository might have a gap in page numbers, or the script reached the end.
**Solution**: If the document is incomplete, use `--start [N]` to resume from the missing page.

## Advanced Usage

### Manual PDF Merge
If you already have images in a folder and just want to merge them:
```bash
img2pdf [FOLDER]/*.jpg --output standard_name.pdf
```

### Path ID Extraction Logic
The script uses regex to find `kkfileview/` in URLs. If the URL structure of the website changes, this logic may need an update in `scripts/downloader.py`.
