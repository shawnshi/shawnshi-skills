## 2026-05-30 - Prevent Command Injection with Argument Lists
**Vulnerability:** Passing a list of arguments to `subprocess.run` or `subprocess.check_output` with `shell=True` causes only the first element to be executed on POSIX systems, while passing the rest to the shell itself. This can lead to unexpected behavior and command injection if not handled carefully.
**Learning:** Always use `shell=False` when passing arguments as a structured list to `subprocess` functions. `shell=True` is dangerous and unnecessary when arguments are already tokenized in a list.
**Prevention:** Use `shell=False` (the default) and pass arguments as structured lists (using `shlex.split()` if parsing string commands) to prevent command injection vulnerabilities.
