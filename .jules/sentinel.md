## 2024-06-19 - Command Injection Risk in gather_context.py
**Vulnerability:** Found a command injection vulnerability in `scripts/io_engine/gather_context.py`. The `calendar_params` dict was converted to JSON, but passed via `shell=True` to `subprocess.run()`. This is unsafe.
**Learning:** Even when inputs are JSON encoded, using `shell=True` exposes the program to shell injection and makes escaping arguments very complex and risky. It is safer to use array arguments without `shell=True`.
**Prevention:** Always avoid `shell=True` unless absolutely necessary, and construct subprocess commands as a list of arguments.
