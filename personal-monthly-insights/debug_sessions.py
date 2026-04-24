import subprocess
import re

# Pre-compiled regex for ANSI stripping
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|[0-9A-FF]{1,2})')

def strip_ansi(text):
    return ANSI_ESCAPE.sub('', text)

print("--- DEBUG: gemini --list-sessions raw output ---")
try:
    result = subprocess.run(["gemini", "--list-sessions"], capture_output=True, text=True, shell=True, encoding='utf-8', errors='ignore')
    raw_output = result.stdout
    print(f"Return Code: {result.returncode}")
    print(f"Stdout length: {len(raw_output)}")
    print(f"First 500 chars (repr):\n{repr(raw_output[:500])}")
    
    clean_output = strip_ansi(raw_output)
    print(f"Cleaned first 5 lines:")
    for line in clean_output.splitlines()[:10]:
        print(f"LINE: {repr(line)}")
        
    # Test current UUID regex
    id_pattern = re.compile(r'\[([a-f0-9\-]{36})\]')
    matches = id_pattern.findall(clean_output)
    print(f"UUID Matches found: {len(matches)}")
    if matches:
        print(f"First match: {matches[0]}")

except Exception as e:
    print(f"CRITICAL ERROR: {e}")
