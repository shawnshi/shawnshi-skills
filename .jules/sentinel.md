## 2026-06-09 - Fix Subprocess Command Injection Pattern
**Vulnerability:** subprocess calls were using shell=True with argument lists.
**Learning:** Passing a list of arguments to subprocess.run or subprocess.Popen with shell=True on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself.
**Prevention:** Always use shell=False with argument lists to ensure correct execution and prevent command injection vulnerabilities.
