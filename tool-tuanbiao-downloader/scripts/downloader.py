"""
<!-- Input: Path ID or URL, Start Index (Optional) -->
<!-- Output: Image Directory, Merged PDF file -->
<!-- Pos: scripts/downloader.py. Specialized downloader for image-based standards. -->

!!! Maintenance Protocol: If URL template changes, update URL_TEMPLATE constant.
!!! Dependency: Requires 'requests' and 'img2pdf'.
"""

import os
import requests
import time
import sys
import glob
import argparse
import shutil
import re

# --- Constants ---
MAX_CONSECUTIVE_ERRORS = 3
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# The template used for downloading standard images
URL_TEMPLATE = "https://www.ttbz.org.cn/kkfileview/{path}/{i}.jpg"

def extract_path_id(input_str):
    """
    Extract Path ID from a raw ID or a URL.
    Supports:
    - T_ISC_0095-2025
    - https://www.ttbz.org.cn/kkfileview/T_ISC_0095-2025/index.html
    """
    input_str = input_str.strip()
    
    # Try to extract from URL if it looks like a link
    if "ttbz.org.cn" in input_str:
        # Match pattern like /kkfileview/ID/
        match = re.search(r'kkfileview/([^/]+)', input_str)
        if match:
            return match.group(1)
            
    # Normalize basic ID (handle dashes and spaces)
    return input_str.replace("—", "-").replace(" ", "").strip()

def create_pdf(directory, output_filename):
    """Combines all JPGs in the directory into a PDF."""
    try:
        import img2pdf
    except ImportError:
        print("\n[WARN] 'img2pdf' library not found. Skipping PDF generation.")
        return

    print(f"\n[INFO] Generating PDF from {directory}...")
    
    image_files = glob.glob(os.path.join(directory, "*.jpg"))
    if not image_files:
        print("[WARN] No images found to combine.")
        return

    # Sort numerically (0.jpg, 1.jpg, ... 10.jpg)
    try:
        image_files.sort(key=lambda x: int(os.path.basename(x).split('.')[0]))
    except ValueError:
        image_files.sort()

    try:
        pdf_bytes = img2pdf.convert(image_files)
        with open(output_filename, "wb") as f:
            f.write(pdf_bytes)
        print(f"[SUCCESS] PDF Created: {output_filename}")
    except Exception as e:
        print(f"[ERROR] PDF creation failed: {e}")

def download_images(raw_input, start_num=0):
    path_id = extract_path_id(raw_input)
    if not path_id:
        print("[ERROR] Could not resolve Path ID.")
        return

    if not os.path.exists(path_id):
        os.makedirs(path_id)
        print(f"[INFO] Target: {path_id}")

    print(f"[INFO] Downloading standard: {path_id}...")

    i = start_num
    consecutive_errors = 0
    success_count = 0
    skipped_count = 0
    
    # Session for connection reuse
    with requests.Session() as session:
        session.headers.update(HEADERS)
        
        while True:
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n[INFO] Termination condition met (End of document).")
                break

            url = URL_TEMPLATE.format(path=path_id, i=i)
            filename = os.path.join(path_id, f"{i}.jpg")
            
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                print(f"[SKIP] Page {i} exists.         ", end="\r")
                skipped_count += 1
                consecutive_errors = 0
                i += 1
                continue
            
            try:
                print(f"[DOWN] Fetching Page {i}...       ", end="\r")
                response = session.get(url, timeout=15)
                
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(response.content)
                    success_count += 1
                    consecutive_errors = 0
                elif response.status_code == 404:
                    # 404 usually means we hit the end of the document
                    consecutive_errors += 1
                else:
                    print(f"\n[FAIL] Status {response.status_code} on page {i}")
                    consecutive_errors += 1
                    
            except Exception as e:
                print(f"\n[ERR] Connection error on page {i}: {e}")
                consecutive_errors += 1
            
            i += 1
            time.sleep(0.1) # Polite delay

    print("\n" + "-" * 30)
    print(f"[DONE] New: {success_count}, Existing: {skipped_count}")
    
    if success_count + skipped_count > 0:
        pdf_name = f"{path_id}.pdf"
        create_pdf(path_id, pdf_name)
    else:
        print("[WARN] No images were retrieved.")

def main():
    parser = argparse.ArgumentParser(description="Tuanbiao Batch Downloader")
    parser.add_argument("path_id", nargs="?", help="Path ID or URL")
    parser.add_argument("--start", type=int, default=0, help="Starting index")
    
    args = parser.parse_args()
    
    if not args.path_id:
        print("Usage: python downloader.py <PATH_ID_OR_URL>")
        return
    
    download_images(args.path_id, args.start)

if __name__ == "__main__":
    main()
