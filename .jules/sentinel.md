## 2026-06-20 - PowerShell Command Injection via WMI
**Vulnerability:** Arbitrary PowerShell command injection due to unescaped user input (play_target) concatenated into a WMI Process Create command string in personal-musicbee-dj/src/cli.py.
**Learning:** Constructing shell strings using f-strings with user input allows escaping string bounds. In PowerShell context, single and double quotes must be properly escaped.
**Prevention:** Sanitize user input by properly escaping quotes before concatenating into shell commands, or avoid shell string construction entirely.
