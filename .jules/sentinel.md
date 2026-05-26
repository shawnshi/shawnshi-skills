## 2026-05-26 - Fix command injection vulnerability with shell=True
**Vulnerability:** Subprocess calls used `shell=True` with a list of arguments.
**Learning:** On POSIX systems, passing a list to `subprocess.run` with `shell=True` causes only the first element to execute as the command, passing the rest as arguments to the shell itself. This can lead to unexpected behavior and command injection if external inputs are involved.
**Prevention:** Always use `shell=False` when passing arguments as a structured list to subprocess functions.
