## 2026-05-18 - Prevent Command Injection with shell=False
**Vulnerability:** Subprocess calls using `shell=True` on POSIX systems can lead to command injection if variables passed into the command strings are not properly sanitized. In this case, `gws`, `git`, and `gemini` commands were passing array arguments with `shell=True` which is both dangerous and behaves incorrectly.
**Learning:** Passing a list of arguments to `subprocess.run` or `subprocess.Popen` with `shell=True` causes only the first element to be executed as the command, with the rest passed to the shell itself. This is both a functional bug and a security risk.
**Prevention:** Always use `shell=False` when using `subprocess.run` or `subprocess.Popen` with a list of arguments.
