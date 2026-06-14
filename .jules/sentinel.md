## 2026-06-14 - Fix command injection vulnerability in gather_context.py
**Vulnerability:** Command injection vulnerability due to `subprocess.run` using `shell=True` with a list of arguments in `scripts/io_engine/gather_context.py`.
**Learning:** Passing a list of arguments with `shell=True` on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself, which can lead to command injection if untrusted data is included, or at best, broken execution.
**Prevention:** Always use `shell=False` when passing arguments as structured lists to `subprocess` functions to prevent command injection vulnerabilities and ensure correct execution.
