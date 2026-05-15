## 2025-02-14 - Fix command injection risks with shell=True
**Vulnerability:** Command injection risk
**Learning:** Passing an argument list to `subprocess.run` or `subprocess.Popen` with `shell=True` can inadvertently cause command injection or incorrect execution if only the first element is executed and the rest are passed to the shell. The parameter `shell=True` allows invoking shell commands, which increases attack surface, especially with externally provided input strings.
**Prevention:** Consistently use `shell=False` when calling `subprocess` methods and use `shlex.split()` on the command string if needed to construct a safe argument list.
