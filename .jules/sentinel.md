## 2026-05-31 - Command Injection via shell=True
**Vulnerability:** Found `subprocess` calls using `shell=True` with a list of arguments. Passing a list of arguments to `subprocess.run` with `shell=True` causes only the first element to be executed as the command, which may result in unexpected behavior or command injection vulnerabilities.
**Learning:** `shell=True` is dangerous and unnecessary when commands are already split into a list of arguments.
**Prevention:** Always use `shell=False` when passing arguments as structured lists to `subprocess.run` or `subprocess.check_output`.
