import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # Disabled use of eval for security

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
