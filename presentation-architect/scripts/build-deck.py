import os
import subprocess
import argparse
import sys

def run_command(command):
    print(f"Running: {command}")
    try:
        subprocess.check_call(command, shell=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Build slide deck (Prompts -> Images -> PPTX/PDF)")
    parser.add_argument("dir", help="Slide deck directory containing outline.md")
    parser.add_argument("--skip-prompts", action="store_true", help="Skip prompt generation")
    parser.add_argument("--skip-images", action="store_true", help="Skip image generation")
    parser.add_argument("--regenerate", "-r", help="Regenerate specific slides (comma-separated indices)")
    
    args = parser.parse_args()
    deck_dir = args.dir
    
    # Get script directory to find other scripts
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Generate Prompts
    if not args.skip_prompts and not args.regenerate:
        print("\n--- Step 1: Generating Prompts ---")
        cmd = f'python "{os.path.join(SCRIPT_DIR, "generate-prompts.py")}" "{deck_dir}"'
        if not run_command(cmd):
            sys.exit(1)

    # 2. Generate Images
    if not args.skip_images:
        print("\n--- Step 2: Generating Images ---")
        regen_flag = f'--regenerate "{args.regenerate}"' if args.regenerate else ""
        cmd = f'python "{os.path.join(SCRIPT_DIR, "generate-images.py")}" "{deck_dir}" {regen_flag}'
        if not run_command(cmd):
            sys.exit(1)

    # 3. Merge to PPTX
    print("\n--- Step 3: Merging to PPTX ---")
    cmd = f'npx tsx "{os.path.join(SCRIPT_DIR, "merge-to-pptx.ts")}" "{deck_dir}"'
    run_command(cmd)

    # 4. Merge to PDF
    print("\n--- Step 4: Merging to PDF ---")
    cmd = f'npx tsx "{os.path.join(SCRIPT_DIR, "merge-to-pdf.ts")}" "{deck_dir}"'
    run_command(cmd)

    print("\n--- Build Complete ---")

if __name__ == "__main__":
    main()