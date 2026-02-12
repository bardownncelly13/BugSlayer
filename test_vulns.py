import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # Removed for security reasons


subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
