## 2026-06-18 - Subprocess with shell=True and List Arguments
**Vulnerability:** In `./scripts/io_engine/gather_context.py`, `subprocess.run` was called with a list of arguments and `shell=True`.
**Learning:** Passing a list of arguments to `subprocess.run` with `shell=True` on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself, leading to unintended behavior and command injection vulnerabilities.
**Prevention:** Always use `shell=False` when passing a list of arguments to `subprocess.run` to ensure arguments are passed safely and directly to the executable.
