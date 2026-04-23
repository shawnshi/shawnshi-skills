## 2024-05-18 - Prevent Command Injection in subprocess calls

**Vulnerability:** Found a command injection vulnerability in `personal-intelligence-hub/scripts/hub_utils.py` where `subprocess.Popen` was called with `shell=True` using a command string sourced directly from an environment variable (`PIH_LLM_COMMAND`). An attacker with control over the environment variable could inject arbitrary shell commands.

**Learning:** Using `shell=True` with `subprocess` functions (like `Popen`, `run`, `call`) when the command string includes externally-controllable input (like environment variables, user input, or external files) opens up the system to command injection attacks. Even if the expected input is simple, malicious actors can append commands using shell operators like `;`, `&&`, or `|`.

**Prevention:** Always use `shell=False` for subprocess calls unless absolutely necessary. When `shell=False` is used, the command and its arguments must be passed as a structured list of strings, rather than a single string. If a single string command needs to be parsed, use `shlex.split()` to safely separate the command and its arguments before passing them to the subprocess call.
