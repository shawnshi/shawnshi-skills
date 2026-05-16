## 2024-05-16 - Command Injection via shell=True and Environment Variables
**Vulnerability:** Command injection risk in `hub_utils.py` due to passing an externally controllable environment variable (`PIH_LLM_COMMAND`) directly to `subprocess.Popen` with `shell=True`.
**Learning:** Using `shell=True` with user-controlled or externally-controlled input strings allows arbitrary command execution. Environment variables should not be trusted unconditionally.
**Prevention:** Always use `shell=False` and pass arguments as a structured list (e.g., using `shlex.split()`) when dealing with external process execution to prevent shell interpretation of metacharacters.
