## 2026-05-24 - Fix Command Injection in Subprocess
**Vulnerability:** subprocess calls used shell=True alongside argument lists instead of raw strings. This causes the first element to be executed as the command and passes the rest as arguments to the shell itself on POSIX systems.
**Learning:** Always use shell=False with argument lists to ensure correct execution and prevent command injection vulnerabilities.
**Prevention:** Ensure shell=False is used when passing argument lists to subprocess.run or subprocess.check_output.
