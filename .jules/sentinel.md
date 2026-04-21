## 2024-05-01 - Command Injection Risks with shell=True
**Vulnerability:** Found multiple instances of `subprocess.run` and `subprocess.Popen` using `shell=True` with user-controllable input or external commands.
**Learning:** Using `shell=True` allows shell metacharacters to be interpreted, leading to command injection if inputs are not properly sanitized. This is particularly critical in utility scripts that execute external commands or interact with the system shell.
**Prevention:** Always use `shell=False` (which is the default) and pass commands as structured lists (e.g., `["command", "arg1", "arg2"]`) rather than concatenated strings. When necessary to parse command strings, use `shlex.split()`.
