import os
import sys
import glob
import json
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Stitch and Format Cognitive Book Mirror Results")
    parser.add_argument("--book_stem", type=str, required=True, help="The stem name of the book")
    parser.add_argument("--results_dir", type=str, required=True, help="Directory containing the result_*.md files")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"[-] Error: Results directory not found: {results_dir}")
        sys.exit(1)
        
    workspace_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    memory_read_dir = workspace_root / "MEMORY" / "raw" / "read"
    memory_read_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = memory_read_dir / f"{args.book_stem}_personalized_mirror.md"

    result_files = sorted(list(results_dir.glob("result_*.md")))
    if not result_files:
        print(f"[-] Error: No result files found in {results_dir}")
        sys.exit(1)

    print(f"[*] Stitching {len(result_files)} result files...")

    final_lines = []
    final_lines.append(f"# {args.book_stem} - 认知镜像\n")
    final_lines.append("| 📖 书籍原旨 (The Book) | 🪞 认知镜像 (The Mirror) |")
    final_lines.append("| :--- | :--- |")

    for filepath in result_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            print(f"[-] Warning: Failed to read {filepath.name} as UTF-8.")
            continue
            
        for line in lines:
            line_clean = line.strip()
            if not line_clean:
                continue
            if line_clean.startswith("| 📖") or line_clean.startswith("| :---"):
                continue
            if line_clean.startswith("|") and line_clean.endswith("|"):
                final_lines.append(line_clean)

    # Ensure output is UTF-8 to prevent Windows console encoding issues on printing
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(final_lines) + "\n")
    except Exception as e:
        print(f"[-] Error writing final output: {e}")
        sys.exit(1)

    # Avoid printing raw strings that might contain unicode on stdout in Windows
    print(f"[+] Successfully stitched {len(result_files)} files.")
    print(f"[+] Saved to: {output_file.as_posix()}")

if __name__ == "__main__":
    main()
