import subprocess
import pickle

password = "supersecret123"

data = input()
# eval(data)  # Disabled due to security risks

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
