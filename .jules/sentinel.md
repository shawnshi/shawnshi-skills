## 2026-05-25 - Command Injection Risk via shell=True
**Vulnerability:** Subprocess calls using shell=True with user-controllable input risk command injection vulnerabilities.
**Learning:** The codebase contained multiple instances of shell=True (e.g., engine.py, debug_sessions.py, gather_context.py).
**Prevention:** Always use shell=False and pass command arguments as structured lists.
