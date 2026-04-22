## 2026-04-22 - [CRITICAL] Command Injection Risk in LLM Runner

**Vulnerability:** The `run_llm` function in `personal-intelligence-hub/scripts/hub_utils.py` executed commands using `subprocess.Popen` with `shell=True`. The command string was constructed using an externally controllable environment variable (`PIH_LLM_COMMAND`), making it vulnerable to command injection.
**Learning:** Even internal utility scripts that wrap CLI tools can introduce severe vulnerabilities if they pass unsanitized environment variables or user inputs directly to a shell. The convenience of `shell=True` often masks this risk.
**Prevention:** Always use `shell=False` for subprocess execution. Parse the command string into a structured list of arguments using `shlex.split()` before passing it to `subprocess.Popen` or `subprocess.run`.
