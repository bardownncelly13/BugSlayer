import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # REMOVED for security: possible code injection vulnerability

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
