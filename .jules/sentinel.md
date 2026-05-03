## 2024-05-24 - Subprocess Command Injection via shell=True

**Vulnerability:** Use of `shell=True` in `subprocess.run`, `subprocess.Popen`, and `subprocess.check_output` with either lists of arguments or un-sanitized string commands (e.g., in `hub_utils.py` and `engine.py`).

**Learning:** Passing a list of arguments to `subprocess` functions with `shell=True` on POSIX systems only executes the first element as the command, passing the rest as arguments to the shell itself, leading to unexpected behavior. Using `shell=True` with strings containing unsanitized input is a command injection risk.

**Prevention:** Always use `shell=False` when calling `subprocess` functions and pass arguments as structured lists. If a command string needs to be parsed, use `shlex.split()` before passing it to `subprocess` with `shell=False`.
