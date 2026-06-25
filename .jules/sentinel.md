## 2026-06-22 - Subprocess Command Injection
**Vulnerability:** Use of shell=True with a list of arguments in subprocess.run in scripts/io_engine/gather_context.py
**Learning:** shell=True on Unix executes the first string as a shell and ignores the rest, and introduces command injection risks.
**Prevention:** Always use shell=False with argument lists.

## 2026-06-23 - PowerShell Command Injection via String Interpolation
**Vulnerability:** Unsanitized user input interpolated into a PowerShell command string in personal-musicbee-dj/src/cli.py.
**Learning:** Even when passing a string to a PowerShell argument, quotes must be escaped to prevent breakout attacks.
**Prevention:** Sanitize user input by escaping single and double quotes (e.g. replacing ' with '' and " with "") before interpolating into PowerShell commands.
## 2026-06-25 - Command Injection in improve.py
**Vulnerability:** Unsanitized user input via environment variable passed to subprocess.run with split().
**Learning:** Using .split() on strings that represent shell commands can lead to improper parsing and potential injection or unexpected behavior if arguments contain spaces or special characters.
**Prevention:** Always use shlex.split() to safely parse command-line strings in Python.
