import os
import sys
import subprocess
import platform

def find_drawio_executable():
    system = platform.system()
    if system == "Windows":
        paths = [
            r"C:\Program Files\draw.io\draw.io.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\draw.io\draw.io.exe")
        ]
        for p in paths:
            if os.path.exists(p):
                return p
    elif system == "Darwin":
        p = "/Applications/draw.io.app/Contents/MacOS/draw.io"
        if os.path.exists(p):
            return p
    elif system == "Linux":
        # Check for WSL
        try:
            with open("/proc/version", "r") as f:
                if "microsoft" in f.read().lower():
                    # WSL2
                    return "/mnt/c/Program Files/draw.io/draw.io.exe"
        except FileNotFoundError:
            pass
        
        # Native Linux
        try:
            return subprocess.check_output(["which", "drawio"]).decode().strip()
        except subprocess.CalledProcessError:
            pass
            
    return None

def main():
    if len(sys.argv) < 3:
        print("Usage: python export_drawio.py <input.drawio> <format>")
        print("Formats: png, svg, pdf, jpg")
        sys.exit(1)

    input_file = os.path.abspath(sys.argv[1])
    fmt = sys.argv[2]
    
    if not os.path.exists(input_file):
        print(f"Error: File not found: {input_file}")
        sys.exit(1)

    executable = find_drawio_executable()
    if not executable:
        print("Warning: draw.io desktop app not found. Skipping export.")
        print(f"You can open the .drawio file directly: {input_file}")
        sys.exit(0)

    output_file = f"{input_file}.{fmt}"
    
    # Base command
    cmd = [executable, "-x", "-f", fmt]
    
    # Embed XML for supported formats
    if fmt in ["png", "svg", "pdf"]:
        cmd.append("-e")
        
    # Formatting
    if fmt in ["png", "jpg", "jpeg"]:
        cmd.extend(["-s", "2"])
        
    cmd.extend(["-b", "10", "-o", output_file, input_file])
    
    print(f"Executing: {' '.join(cmd)}")
    
    try:
        # Use subprocess to bypass shell escaping issues
        subprocess.run(cmd, check=True)
        print(f"Successfully exported to: {output_file}")
        
        # Delete the intermediate .drawio file since export succeeded
        os.remove(input_file)
        print(f"Deleted source file: {input_file}")
        
        # Open the file
        system = platform.system()
        if system == "Windows":
            os.startfile(output_file)
        elif system == "Darwin":
            subprocess.run(["open", output_file])
        elif system == "Linux":
            try:
                with open("/proc/version", "r") as f:
                    if "microsoft" in f.read().lower():
                        # WSL2
                        win_path = subprocess.check_output(["wslpath", "-w", output_file]).decode().strip()
                        subprocess.run(["cmd.exe", "/c", "start", '""', win_path])
                        return
            except FileNotFoundError:
                pass
            subprocess.run(["xdg-open", output_file])
            
    except subprocess.CalledProcessError as e:
        print(f"Error during export: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()