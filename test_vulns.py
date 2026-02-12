import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # Disabled for security. Avoid using eval on untrusted input.

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
