## 2026-06-05 - Fixed command injection vulnerability in gather_context.py
**Vulnerability:** `subprocess.run` was called with `shell=True` and an argument list containing serialized JSON, creating a command injection risk if parameter generation is compromised.
**Learning:** Using `shell=True` with a list of arguments on POSIX systems causes only the first element to execute as the command, which is unsafe and unpredictable.
**Prevention:** Always use `shell=False` when calling `subprocess.run` with an argument list, and properly sanitize or parse parameters.
