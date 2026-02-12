import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # REMEDIATED: Avoid use of eval due to security risk

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
