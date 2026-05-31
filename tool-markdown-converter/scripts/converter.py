"""
<!-- Input: Source file path, Output file path (optional), Use Azure flag -->
<!-- Output: Markdown content or file, Success/Error status -->
<!-- Pos: scripts/converter.py. Robust wrapper for 'markitdown'. -->

!!! Dependency: Requires 'markitdown[all]' installed via pip globally.
"""

import argparse
import subprocess
import os
import sys
import json
import time

MAX_CHARS = 100000

def check_markitdown():
    try:
        subprocess.run(["markitdown", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def write_telemetry(status, duration_sec, input_path, output_len):
    """
    Automated telemetry logging. Agent doesn't need to manually write json files anymore.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Walk up 4 directories to reach .gemini root
        # scripts -> tool-markdown-converter -> skills -> config -> .gemini
        gemini_root = os.path.abspath(os.path.join(script_dir, "..", "..", "..", ".."))
        telemetry_dir = os.path.join(gemini_root, "MEMORY", "skill_audit", "telemetry")
        os.makedirs(telemetry_dir, exist_ok=True)
        
        timestamp = int(time.time())
        record_path = os.path.join(telemetry_dir, f"record_{timestamp}.json")
        
        data = {
            "skill_name": "tool-markdown-converter",
            "status": status,
            "duration_sec": round(duration_sec, 2),
            "input_file": os.path.basename(input_path),
            "output_chars": output_len
        }
        
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Warning: Failed to auto-write telemetry: {e}", file=sys.stderr)

def convert_file(input_path, output_path=None, use_azure=False, azure_endpoint=None):
    start_time = time.time()
    abs_input = os.path.abspath(input_path)
    
    if not os.path.exists(abs_input):
        return {"status": "error", "message": f"Input file not found: {abs_input}"}

    ext = os.path.splitext(abs_input)[1].lower()
    
    if ext == '.djvu':
        return {"status": "error", "message": "The .djvu format is a scanned image format. Please physically convert it to PDF first so it can be processed via Azure OCR."}
        
    if ext in ['.mobi', '.azw3', '.epub']:
        import tempfile
        # Try using calibre's ebook-convert
        try:
            subprocess.run(["ebook-convert", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return {"status": "error", "message": f"'{ext}' format requires Calibre's 'ebook-convert' tool to be installed globally."}
            
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_txt_path = tmp.name
            
        print(f"Intercepted {ext} format. Dispatching to ebook-convert...", file=sys.stderr)
        try:
            # ebook-convert outputs a lot of logs, we suppress stdout if not debugging
            subprocess.run(["ebook-convert", abs_input, tmp_txt_path], capture_output=True, text=True, check=True)
            with open(tmp_txt_path, "r", encoding="utf-8", errors="replace") as f:
                output_content = f.read()
                
            if len(output_content.strip()) < 1000:
                warning_header = (
                    f"## ⚠️ System Warning: Print Replica / Scanned Image Book Detected\n"
                    f"The conversion engine only found {len(output_content.strip())} characters of text. "
                    f"This is typically because the original {ext} file is just a wrapper around scanned images. "
                    f"Please provide an OCR-processed PDF or a true text-based EPUB instead.\n"
                )
                output_content = warning_header
                
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(output_content)
                result_stdout = f"Saved to {output_path}"
                output_len = len(output_content)
            else:
                result_stdout = output_content
                output_len = len(output_content)
                
            duration = time.time() - start_time
            write_telemetry("success", duration, abs_input, output_len)
            os.remove(tmp_txt_path)
            
            return {
                "status": "success",
                "message": f"Converted {os.path.basename(abs_input)} to markdown via calibre.",
                "output": result_stdout
            }
        except subprocess.CalledProcessError as e:
            os.remove(tmp_txt_path)
            return {"status": "error", "message": f"ebook-convert failed: {e.stderr}"}

    if not check_markitdown():
        return {"status": "error", "message": "'markitdown' command not found. Ensure `pip install markitdown[all]` was executed globally."}

    # Build command directly hitting native markitdown
    cmd = ["markitdown", abs_input]
    
    if output_path:
        cmd.extend(["-o", output_path])
    
    if use_azure:
        cmd.append("-d")
        if azure_endpoint:
            cmd.extend(["-e", azure_endpoint])

    print(f"Executing: {' '.join(cmd)}", file=sys.stderr)
    
    try:
        result = subprocess.run(cmd, capture_output=not bool(output_path), text=True, check=True)
        duration = time.time() - start_time
        
        output_content = result.stdout if not output_path else f"Saved to {output_path}"
        output_len = len(output_content) if result.stdout else 0
        
        # Context overflow protection
        if not output_path and output_len > MAX_CHARS:
            warning_header = (
                f"## ⚠️ System Warning: Document Too Large\n"
                f"The document is {output_len} chars long. Showing first {MAX_CHARS} chars to prevent agent context overflow.\n"
                f"Please use standard specific file reading or splitting strategies to read the remainder if absolutely necessary.\n\n"
            )
            output_content = warning_header + output_content[:MAX_CHARS]
            
        write_telemetry("success", duration, abs_input, output_len)
        
        return {
            "status": "success",
            "message": f"Converted {os.path.basename(abs_input)} to markdown.",
            "output": output_content
        }
    except subprocess.CalledProcessError as e:
        duration = time.time() - start_time
        write_telemetry("error", duration, abs_input, 0)
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
