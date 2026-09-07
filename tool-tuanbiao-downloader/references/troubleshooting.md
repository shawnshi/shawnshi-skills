# Troubleshooting & Advanced Usage

## Common Issues

### 1. "img2pdf not found"
**Cause**: The library is not installed in the current environment.
**Solution**: Only with explicit authorization to install dependencies, run `pip install img2pdf` (or `uv pip install img2pdf` when using `uv`). Otherwise report the missing dependency; images alone are not a successful PDF delivery.

### 2. PDF Creation Fails (Numerical Sort)
**Cause**: If the images are not named `0.jpg, 1.jpg...`, the numerical sort might fail.
**Solution**: The script will fallback to alphabetical sort. Ensure no unrelated `.jpg` files are in the folder.

### 3. Early Termination (404 Error)
**Cause**: The script stops after three consecutive errors, not only 404 responses. This may indicate missing pages, access/network failure, or the end; it is not proof of completeness.
**Solution**: Check source page count and access permission first. Only for a verified supported source, use `--start N` to resume at a known image index; do not bypass restrictions or repeatedly retry a blocked source.

## Advanced Usage

### Manual PDF Merge
If you already have images in a folder and just want to merge them:
```bash
img2pdf [FOLDER]/*.jpg --output standard_name.pdf
```

### Path ID Extraction Logic
The script only requests `https://www.ttbz.org.cn/kkfileview/{path}/{i}.jpg`. Supply a verified public image-view URL on that host or its single-segment path ID, not another site's URL, an ordinary PDF link, or a GB/ISO standard number. Its regex extraction and fallback normalization do not validate host, source permission, or path safety; verify inputs before invocation and reject path separators or traversal in raw IDs. If the source format changes or is unsupported, stop this script and use only separately authorized, available general-purpose capabilities, or explain the limitation. Do not treat this interface as a generic downloader.
