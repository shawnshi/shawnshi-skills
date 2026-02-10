"""
<!-- Input: Source file path, Output file path (optional), Use Azure flag -->
<!-- Output: Markdown content or file, Success/Error status -->
<!-- Pos: scripts/converter.py. Robust wrapper for 'markitdown' (via uvx). -->

!!! Maintenance Protocol: If markitdown CLI parameters change, update the command builder.
!!! Dependency: Requires 'uv' installed in system PATH.
"""

import argparse
import subprocess
import os
import sys
import json

def check_uv():
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def convert_file(input_path, output_path=None, use_azure=False, azure_endpoint=None):
    if not os.path.exists(input_path):
        return {"status": "error", "message": f"Input file not found: {input_path}"}

    if not check_uv():
        return {"status": "error", "message": "'uv' tool not found. Please install uv (https://astral.sh/uv)."}

    # Build command
    cmd = ["uvx", "markitdown", input_path]
    
    if output_path:
        cmd.extend(["-o", output_path])
    
    if use_azure:
        cmd.append("-d")
        if azure_endpoint:
            cmd.extend(["-e", azure_endpoint])

    print(f"Executing: {' '.join(cmd)}", file=sys.stderr)
    
    try:
        # We don't capture stdout if -o is used, markitdown writes to file
        result = subprocess.run(cmd, capture_output=not bool(output_path), text=True, check=True)
        
        return {
            "status": "success",
            "message": f"Converted {input_path} to markdown.",
            "output": result.stdout if not output_path else f"Saved to {output_path}"
        }
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Conversion failed: {e.stderr}"
        }

def main():
    parser = argparse.ArgumentParser(description="Markdown Converter Wrapper")
    parser.add_argument("input", help="Source file path")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("-d", "--azure", action="store_true", help="Use Azure Document Intelligence")
    parser.add_argument("-e", "--endpoint", help="Azure endpoint")
    
    args = parser.parse_args()
    
    result = convert_file(args.input, args.output, args.azure, args.endpoint)
    
    if result["status"] == "success":
        if not args.output:
            print(result["output"])
        else:
            print(result["message"])
    else:
        print(f"ERROR: {result['message']}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
