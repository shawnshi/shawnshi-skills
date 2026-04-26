## 2024-04-26 - Prevent Command Injection with shell=False

**Vulnerability:** The `subprocess.Popen` call in `personal-intelligence-hub/scripts/hub_utils.py` used `shell=True` with a dynamically resolved `command` string (`resolve_llm_command()`). If the environment variable `PIH_LLM_COMMAND` contained unescaped input, this could result in an arbitrary command injection vulnerability.
**Learning:** `shell=True` allows the underlying shell to interpolate variables and execute sequential commands, which introduces significant security risks if any part of the command string is user-controllable (e.g., via environment variables).
**Prevention:** Always use `shell=False` and pass commands as structured lists (e.g., parsed via `shlex.split()`) rather than concatenated strings.
