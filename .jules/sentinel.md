## 2026-06-06 - [CRITICAL] Command Injection via `shell=True` with argument lists
**Vulnerability:** Subprocess calls in `gather_context.py` and `engine.py` were using `shell=True` alongside argument lists (e.g., `["gws", "calendar", ...]`).
**Learning:** In Python, passing a list of arguments to `subprocess.run` with `shell=True` on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself. This not only leads to unexpected behavior but also opens up severe command injection risks if any part of the command list contains unsanitized input.
**Prevention:** Always use `shell=False` when passing arguments as structured lists to `subprocess` functions to ensure correct execution and prevent command injection.
