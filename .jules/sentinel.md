## 2026-05-19 - Command Injection Risk with shell=True
**Vulnerability:** Use of shell=True in subprocess calls with external or dynamically constructed command inputs.
**Learning:** Passing a list of arguments to subprocess.run or subprocess.Popen with shell=True on POSIX systems is a command injection risk and can lead to unexpected execution behavior.
**Prevention:** Always use shell=False with argument lists to ensure correct execution and prevent command injection vulnerabilities.
