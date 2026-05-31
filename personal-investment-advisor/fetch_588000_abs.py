import subprocess
import sys
import os

target_dir = r'C:\Users\shich\.gemini\config\skills\personal-investment-advisor'
script_path = os.path.join(target_dir, 'scripts', 'yf.py')
out_path = os.path.join(target_dir, '588000_raw.json')

try:
    result = subprocess.run(
        [sys.executable, script_path, '588000.SS', '--json', '--with-portfolio'],
        capture_output=True, text=True, encoding='utf-8', cwd=target_dir
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(result.stdout)
    if result.returncode == 0:
        print("Fetched successfully to", out_path)
    else:
        print("Error fetching:", result.stderr)
except Exception as e:
    print("Exception:", e)
