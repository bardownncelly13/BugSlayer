import os
import subprocess


def bad_subprocess():
    user_input = input("Enter cmd: ")
    subprocess.run(user_input, shell=True)  


def bad_eval():
    code = input("Enter Python: ")
    import ast
ast.literal_eval(code)  


if __name__ == "__main__":
    bad_subprocess()

    bad_eval()
    
