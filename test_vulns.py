import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data) # REMEDIATED: unsafe use of eval removed or replaced with safe alternative


subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
