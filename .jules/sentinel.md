## 2024-06-15 - Command Injection Vulnerability via shell=True
**Vulnerability:** Found `subprocess.run(..., shell=True)` combined with a list of arguments in `scripts/io_engine/gather_context.py`.
**Learning:** Using `shell=True` with argument lists on POSIX systems is insecure and incorrectly passes subsequent items to the shell rather than the command. It opens up potential command injection vulnerabilities.
**Prevention:** Always use `shell=False` when passing a list of arguments to `subprocess.run` or `subprocess.Popen` to ensure secure execution and prevent command injection risks.
