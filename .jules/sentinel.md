## 2026-06-02 - Command Injection Risk with shell=True
**Vulnerability:** Passing a list of arguments to `subprocess` functions with `shell=True` on POSIX systems can lead to command injection if any of the elements are user-controlled, because only the first element is executed as the command and the rest are passed as arguments to the shell itself.
**Learning:** `shell=True` should not be used with argument lists. If `shell=True` is required, the command must be passed as a single string. However, passing untrusted input as a string with `shell=True` is dangerous.
**Prevention:** Always use `shell=False` when passing arguments as structured lists, or safely parse strings into lists using `shlex.split()` before executing with `shell=False`.
