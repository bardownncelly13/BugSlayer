import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data) # REMEDIATED: Disabled to prevent code injection vulnerability

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
