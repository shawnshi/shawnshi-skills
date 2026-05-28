## 2026-05-28 - Command Injection Risk with shell=True and Argument Lists
**Vulnerability:** Passing a list of arguments to subprocess functions with `shell=True` causes only the first element to execute as the command on POSIX systems, passing the rest as arguments to the shell itself. This exposes the system to command injection and leads to execution errors.
**Learning:** `shell=True` combined with argument lists is unsafe and functionally broken on POSIX systems. It negates the security benefits of argument lists.
**Prevention:** Always use `shell=False` when passing a structured list of arguments to `subprocess` functions.
