# Automated remediation could not produce a safe patch

A vulnerability was detected, but automated patch attempts did not pass validation.

- Rule: `python.lang.security.audit.subprocess-shell-true.subprocess-shell-true`
- File: `test_vulns.py`
- Line: `7`
- Severity: `ERROR`
- Message: Found 'subprocess' function 'run' with 'shell=True'. This is dangerous because this call will spawn the command using a shell process. Doing so propagates current shell settings and variables, which makes it much easier for a malicious actor to execute commands. Use 'shell=False' instead.
- Max patch attempts: 5

## Next steps
- Perform manual remediation for this finding.
- Re-run the scanner after applying a manual fix.

## Subprocess Shell Injection Risk

### Why This Is Risky
- **Shell Injection Attacks**: Using `shell=True` allows malicious input to execute arbitrary commands through shell metacharacters (`; | & $()` etc.)
- **Environment Propagation**: Inherits current shell's environment variables and settings, expanding the attack surface

### Safe Remediation Approach
- **Use `shell=False`**: Pass the command and arguments as a list instead of a string
- **Command as List**: Convert `subprocess.run("command arg1 arg2", shell=True)` to `subprocess.run(["command", "arg1", "arg2"], shell=False)`
- **Input Validation**: Sanitize and validate any user-controlled input passed to the subprocess
- **Alternative for Shell Features**: If shell features are truly needed, use `shlex.quote()` to safely escape arguments

### Reviewer Checklist
- [ ] Verify `shell=False` is explicitly set or command is passed as a list (which defaults `shell=False`)
- [ ] Confirm all arguments are properly separated in the command list, not concatenated as strings
- [ ] Check that any user input is validated/sanitized before being passed to subprocess functions
