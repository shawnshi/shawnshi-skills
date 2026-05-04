## 2026-05-04 - Fix Command Injection from Dynamic Shell Commands

**Vulnerability:** A critical command injection vulnerability existed in `personal-intelligence-hub/scripts/hub_utils.py` due to the use of `shell=True` in `subprocess.Popen()` while passing a command string resolved directly from an environment variable (`PIH_LLM_COMMAND`). If an attacker could control this environment variable, they could inject arbitrary shell commands (e.g., `gemini ask -; rm -rf /`).

**Learning:** When a command string is dynamically constructed or resolved from external sources (like environment variables, configuration files, or user input), passing it to `subprocess` functions with `shell=True` is extremely dangerous. The shell interpreter will evaluate any metacharacters present in the string.

**Prevention:** To safely execute dynamically provided command strings, they must be parsed into a structured argument list using `shlex.split(command)` and executed with `shell=False`. This ensures that the operating system executes the target binary directly with the specified arguments, without invoking a shell interpreter that could evaluate malicious metacharacters.
