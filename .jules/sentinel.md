## 2024-05-08 - Prevent Command Injection with subprocess

**Vulnerability:** The codebase was using `shell=True` in several `subprocess.run` and `subprocess.Popen` calls (e.g., in `hub_utils.py` and `engine.py`). Using `shell=True` can expose the application to command injection vulnerabilities, especially when executing commands containing user-controlled input or environmental variables. Additionally, on POSIX systems, passing a list of arguments with `shell=True` results in only the first element being executed as the command, with the rest passed as arguments to the shell itself, leading to unexpected behavior.

**Learning:** When executing external processes in Python, especially CLI tools like `gemini` and `git`, setting `shell=True` adds an unnecessary shell layer. If the command string contains untrusted data, this can allow an attacker to execute arbitrary shell commands. Passing lists with `shell=True` is also an anti-pattern.

**Prevention:** Always use `shell=False` when calling `subprocess.run`, `subprocess.Popen`, or `subprocess.check_output`. Pass the command as a structured list of arguments (e.g., `["gemini", "--list-sessions"]`). If the command is dynamically constructed as a string and needs to be tokenized, use `shlex.split()` to safely parse it into a list before execution.
