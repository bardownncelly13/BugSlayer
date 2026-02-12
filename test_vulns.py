import subprocess
import pickle

password = "supersecret123"

data = input()
print("Warning: eval() is dangerous and has been removed.")

subprocess.Popen("ls -la", shell=True)

pickle.loads(data)
