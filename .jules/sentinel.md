## 2026-06-03 - [Command Injection Vulnerability]
**Vulnerability:** Subprocess calls using `shell=True` with command lists (e.g., `["gemini", "--list-sessions"]`).
**Learning:** Using `shell=True` with a list of arguments on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself, which can lead to command injection vulnerabilities and unexpected behavior.
**Prevention:** Consistently use `shell=False` for all `subprocess` calls across all projects in the repository, and pass arguments as structured lists.
