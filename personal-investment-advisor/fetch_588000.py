import subprocess
import sys

try:
    result = subprocess.run(
        [sys.executable, 'scripts/yf.py', '588000.SS', '--json', '--with-portfolio'],
        capture_output=True, text=True, encoding='utf-8'
    )
    with open('588000_raw.json', 'w', encoding='utf-8') as f:
        f.write(result.stdout)
    if result.returncode == 0:
        print("Fetched successfully")
    else:
        print("Error fetching:", result.stderr)
except Exception as e:
    print("Exception:", e)
