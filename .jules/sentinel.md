## 2024-04-27 - [CRITICAL] Command Injection via Environment Variable in `run_llm`

**Vulnerability:** Command injection vulnerability in `personal-intelligence-hub/scripts/hub_utils.py` where `subprocess.Popen` was used with `shell=True` and a command string derived from an environment variable (`PIH_LLM_COMMAND`).
**Learning:** Using `shell=True` exposes the application to command injection if any part of the command string is user-controllable, even if that control comes indirectly through environment variables intended for configuration. This is a severe risk in local tooling or runner environments.
**Prevention:** Always use `shell=False` when making subprocess calls, and pass command arguments as a structured list rather than a single string. When reading command strings from configuration or environment variables, use `shlex.split()` to safely parse them into argument lists before passing them to `subprocess` functions.
