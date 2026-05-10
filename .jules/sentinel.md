## 2025-05-10 - Command Injection via Environment Variable

**Vulnerability:** Command injection risk in `personal-intelligence-hub/scripts/hub_utils.py` due to passing a user-controlled environment variable (`PIH_LLM_COMMAND`) directly to `subprocess.Popen` with `shell=True`.
**Learning:** Using `shell=True` with dynamic command strings derived from environment variables allows arbitrary command execution if the environment variable contains shell metacharacters (e.g., `;`, `|`, `&`).
**Prevention:** Always use `shell=False` and pass commands as a structured list using `shlex.split()` when the command includes user-provided inputs or environment variables.
