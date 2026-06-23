## 2026-06-22 - Subprocess Command Injection
**Vulnerability:** Use of shell=True with a list of arguments in subprocess.run in scripts/io_engine/gather_context.py
**Learning:** shell=True on Unix executes the first string as a shell and ignores the rest, and introduces command injection risks.
**Prevention:** Always use shell=False with argument lists.
