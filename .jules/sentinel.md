## 2026-06-10 - [Command Injection]
**Vulnerability:** subprocess.run used shell=True with a list of arguments.
**Learning:** Passing a list of arguments to subprocess.run with shell=True on POSIX systems causes only the first element to be executed as the command, passing the rest as arguments to the shell itself, which can lead to command injection or incorrect execution.
**Prevention:** Always use shell=False when passing a list of arguments to subprocess commands.
