
## 2026-06-21 - PowerShell Command Injection via WMI Process Create
**Vulnerability:** Unsanitized user input (`play_target`) in `personal-musicbee-dj/src/cli.py` was being directly interpolated into a PowerShell command string (`wmi_cmd`) to execute a MusicBee executable via `Invoke-WmiMethod`, allowing arbitrary command injection.
**Learning:** Even when interacting with supposedly simple local commands, dynamically generating command strings with user-controlled input can lead to command injection if not properly sanitized, especially on Windows environments where quoting rules differ. Using `subprocess.run` with `shell=False` is not enough to prevent injection if the target command itself is an unescaped PowerShell string.
**Prevention:** Properly sanitize string bounds for PowerShell parameters (e.g., escaping `"` to `""` and `'` to `''`) before interpolation, and explicitly specify `shell=False` in `subprocess.run()`.
