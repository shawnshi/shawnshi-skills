## 2026-06-13 - Fixed Command Injection Risk in gather_context.py
**Vulnerability:** A `subprocess.run` call in `scripts/io_engine/gather_context.py` was executed with `shell=True` while passing arguments as a list.
**Learning:** Using `shell=True` with a list of arguments on POSIX systems is not only a potential command injection risk if arguments involve untrusted input, but it also causes incorrect argument passing (subsequent elements are passed as arguments to the shell itself, not the command).
**Prevention:** Always use `shell=False` when executing commands from Python `subprocess`, especially when passing arguments as a structured list.
