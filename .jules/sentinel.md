## 2025-04-25 - Fix command injection in personal-intelligence-hub LLM runner
**Vulnerability:** Unsanitized command injection via `PIH_LLM_COMMAND` environment variable passed to `subprocess.Popen` with `shell=True`.
**Learning:** External variables or commands passed to `subprocess` functions should avoid `shell=True` to prevent command injection, especially when derived from environment variables or custom configurations.
**Prevention:** Use `shell=False` and pass commands as structured lists (e.g. using `shlex.split()`) in `subprocess.Popen` calls.
