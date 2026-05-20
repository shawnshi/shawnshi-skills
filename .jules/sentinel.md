## 2026-05-20 - Command Injection Risk with shell=True
**Vulnerability:** Widespread use of `shell=True` in `subprocess` calls, especially dangerous when combining it with user-controllable environment variables (like `PIH_LLM_COMMAND`) or passing argument lists directly.
**Learning:** On POSIX systems, passing an argument list to `subprocess.run` with `shell=True` results in only the first item executing as the command, with the rest passed to the shell. Further, using `shell=True` with an unsanitized string allows for command injection.
**Prevention:** Always use `shell=False` for `subprocess` calls. If parsing a string command is necessary, use `shlex.split()` to safely tokenize it into a list before execution.
