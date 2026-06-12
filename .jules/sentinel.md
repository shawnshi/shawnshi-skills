## 2026-06-12 - Command Injection Risk via shell=True
**Vulnerability:** In `scripts/io_engine/gather_context.py`, `subprocess.run` was called with `shell=True` while passing a list of arguments.
**Learning:** Using `shell=True` with a list of arguments on POSIX systems is incorrect and can lead to command injection risks. It executes only the first element as the command, passing the rest as arguments to the shell itself.
**Prevention:** Always use `shell=False` when passing a list of arguments to `subprocess.run` or `subprocess.Popen` to ensure correct execution and prevent command injection vulnerabilities.
