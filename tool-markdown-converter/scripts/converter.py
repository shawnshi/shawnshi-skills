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
    except FileNotFoundError:
        return False

def write_telemetry(status, duration_sec, input_path, output_len):
    """
    Automated telemetry logging. Agent doesn't need to manually write json files anymore.
    """
    telemetry_dir = os.environ.get("MARKDOWN_CONVERTER_TELEMETRY_DIR")
    if not telemetry_dir:
        return
    try:
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
        return {"status": "error", "completeness": "error", "message": f"Input file not found: {abs_input}"}

    ext = os.path.splitext(abs_input)[1].lower()
    
    if ext == '.djvu':
        return {"status": "error", "completeness": "error", "message": "The .djvu format is a scanned image format. Please physically convert it to PDF first so it can be processed via Azure OCR."}
        
    if ext in ['.mobi', '.azw3', '.epub']:
        import tempfile
        # Try using calibre's ebook-convert
        try:
            subprocess.run(["ebook-convert", "--version"], capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            return {"status": "error", "completeness": "error", "returncode": e.returncode,
                    "message": f"ebook-convert version check failed: {e}; stderr: {e.stderr}"}
        except FileNotFoundError as e:
            return {"status": "error", "completeness": "error", "message": f"Calibre ebook-convert unavailable: {e}"}
            
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_txt_path = tmp.name
            
        print(f"Intercepted {ext} format. Dispatching to ebook-convert...", file=sys.stderr)
        try:
            # ebook-convert outputs a lot of logs, we suppress stdout if not debugging
            subprocess.run(["ebook-convert", abs_input, tmp_txt_path], capture_output=True, text=True, check=True)
            with open(tmp_txt_path, "r", encoding="utf-8") as f:
                output_content = f.read()
                
            if not output_content.strip():
                return {"status": "error", "completeness": "error",
                        "message": "Calibre extracted no text; source content type is unverified.",
                        "warnings": ["OCR may be needed if source inspection confirms image-only content."]}

            if output_path:
                try:
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(output_content)
                except (OSError, UnicodeError) as e:
                    return {"status": "error", "completeness": "partial",
                            "message": f"Failed to save ebook-convert output ({type(e).__name__}): {e}",
                            "output": output_content,
                            "warnings": ["Saving failed; returning extracted text. The target may be absent or incomplete."]}
                result_stdout = f"Saved to {output_path}"
                output_len = len(output_content)
            else:
                result_stdout = output_content
                output_len = len(output_content)
                
            duration = time.time() - start_time
            write_telemetry("success", duration, abs_input, output_len)
            return {
                "status": "success",
                "completeness": "full",
                "warnings": [],
                "message": f"Converted {os.path.basename(abs_input)} to markdown via calibre.",
                "output": result_stdout
            }
        except subprocess.CalledProcessError as e:
            failure = {"status": "error", "completeness": "error", "returncode": e.returncode,
                       "message": f"ebook-convert failed: {e}; stderr: {e.stderr}"}
            try:
                with open(tmp_txt_path, "r", encoding="utf-8") as f:
                    partial_text = f.read()
                if partial_text.strip():
                    failure.update(completeness="partial", output=partial_text,
                                   warnings=["Conversion failed; extracted text is incomplete and was not saved to the requested output."])
            except (OSError, UnicodeError) as read_error:
                failure["warnings"] = [f"Partial output unreadable: {read_error}"]
            return failure
        except (OSError, UnicodeError) as e:
            return {"status": "error", "completeness": "error",
                    "message": f"ebook-convert output error ({type(e).__name__}): {e}"}
        finally:
            try:
                os.remove(tmp_txt_path)
            except OSError as cleanup_error:
                print(f"WARNING: temporary output retained at {tmp_txt_path}: {cleanup_error}", file=sys.stderr)

    try:
        if not check_markitdown():
            return {"status": "error", "completeness": "error", "message": "'markitdown' command not found; installation requires separate authorization."}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "completeness": "error", "returncode": e.returncode,
                "message": f"markitdown version check failed: {e}; stderr: {e.stderr}"}
    except OSError as e:
        return {"status": "error", "completeness": "error", "message": f"markitdown unavailable: {e}"}

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
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = time.time() - start_time
        
        output_content = result.stdout if not output_path else f"Saved to {output_path}"
        output_len = len(output_content) if result.stdout else 0
        
        completeness = "full"
        warnings = []
        # Context overflow protection
        if not output_path and output_len > MAX_CHARS:
            warning_header = (
                f"## ⚠️ System Warning: Document Too Large\n"
                f"The document is {output_len} chars long. Showing first {MAX_CHARS} chars to prevent agent context overflow.\n"
                f"Please use standard specific file reading or splitting strategies to read the remainder if absolutely necessary.\n\n"
            )
            output_content = output_content[:MAX_CHARS]
            completeness = "partial"
            warnings.append(warning_header.strip())
            
        write_telemetry("success", duration, abs_input, output_len)
        
        return {
            "status": "success",
            "completeness": completeness,
            "warnings": warnings,
            "message": f"Converted {os.path.basename(abs_input)} to markdown.",
            "output": output_content
        }
    except subprocess.CalledProcessError as e:
        duration = time.time() - start_time
        write_telemetry("error", duration, abs_input, 0)
        return {
            "status": "error",
            "completeness": "error",
            "returncode": e.returncode,
            "message": f"Conversion failed: {e}; stderr: {e.stderr}"
        }
    except (OSError, UnicodeError) as e:
        return {"status": "error", "completeness": "error",
                "message": f"Conversion error ({type(e).__name__}): {e}"}

def main():
    parser = argparse.ArgumentParser(description="Markdown Converter Wrapper")
    parser.add_argument("input", help="Source file path")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("-d", "--azure", action="store_true", help="Use Azure Document Intelligence")
    parser.add_argument("-e", "--endpoint", help="Azure endpoint")
    
    args = parser.parse_args()
    
    result = convert_file(args.input, args.output, args.azure, args.endpoint)
    
    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}", file=sys.stderr)
    if result["status"] == "success":
        if not args.output:
            print(result["output"])
        else:
            print(result["message"])
    else:
        if result.get("completeness") == "partial":
            print(result["output"])
        print(f"ERROR: {result['message']}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
