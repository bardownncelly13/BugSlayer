import os
import subprocess


def bad_subprocess():
    user_input = input("Enter cmd: ")
    subprocess.run(user_input, shell=True)  


import ast

def bad_eval():
    code = input("Enter Python: ")
    try:
        ast.literal_eval(code)
    except (ValueError, SyntaxError):
        print("Invalid input: only literal expressions allowed")

def main():
    bad_subprocess()

    bad_eval()

if __name__ == "__main__":
    main()
