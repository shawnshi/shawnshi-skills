## 2024-05-15 - [CRITICAL] Fix command injection risks by removing shell=True

**Vulnerability:** Several scripts (`personal-monthly-insights/core/engine.py`, `scripts/io_engine/gather_context.py`, `personal-intelligence-hub/scripts/hub_utils.py`) used `shell=True` with `subprocess.run` and `subprocess.Popen`. In `hub_utils.py`, the `command` variable was a single string executed via shell, passing user-controlled `prompt` via `stdin`, while in others, lists were passed with `shell=True`.

**Learning:** On POSIX systems, passing a list of arguments to `subprocess` with `shell=True` executes only the first element as the command, passing the rest as arguments to the shell itself, which is unpredictable and dangerous. Passing an unsanitized string with `shell=True` directly exposes the application to command injection.

**Prevention:** Always use `shell=False` (the default) when executing subprocesses. Pass arguments as a structured list rather than a single string. When parsing string commands from environment variables, use `shlex.split()` to safely convert them into argument lists before passing to `subprocess`.
