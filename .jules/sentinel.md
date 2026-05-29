## 2026-05-29 - Prevent Command Injection via shell=True
**Vulnerability:** Use of `shell=True` in `subprocess.run` and `subprocess.check_output` with externally controllable inputs or argument lists, posing a command injection risk and incorrect argument parsing.
**Learning:** In Python, passing a list of arguments to `subprocess.run` with `shell=True` causes only the first element to be executed as the command. Furthermore, using `shell=True` allows shell metacharacters to be evaluated.
**Prevention:** Always use `shell=False` (the default) when executing subprocesses, and pass arguments as structured lists rather than concatenated strings.
