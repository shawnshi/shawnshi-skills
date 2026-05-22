## 2026-05-22 - Command Injection in subprocess calls
**Vulnerability:** Multiple instances of `subprocess.run` and `subprocess.check_output` using `shell=True` with arguments passed as structured lists instead of strings.
**Learning:** Using `shell=True` with a list of arguments on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself. This can lead to unexpected behavior and potential command injection vulnerabilities. It is also a security risk to use `shell=True`.
**Prevention:** Always use `shell=False` when passing arguments as structured lists to `subprocess` functions to ensure correct execution and prevent command injection vulnerabilities.
