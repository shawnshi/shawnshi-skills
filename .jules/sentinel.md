## 2026-06-07 - Command Injection via subprocess shell=True
**Vulnerability:** Passing a list of arguments to `subprocess.run` with `shell=True` can lead to command injection if any argument contains untrusted input.
**Learning:** The Python `subprocess` module handles argument lists improperly when `shell=True` on POSIX systems, where it treats the first item as the command and the rest as arguments to the shell itself, leading to unexpected behavior and security risks.
**Prevention:** Always use `shell=False` when passing a list of arguments to `subprocess` functions, which ensures the arguments are passed safely without being interpreted by the shell.
