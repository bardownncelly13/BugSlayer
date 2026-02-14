import subprocess
import pickle

password = "supersecret123"

data = input()
# eval was removed to prevent code execution vulnerability
# eval(data)

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
