import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # Removed for security - eval should not be used on untrusted input

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
