import os
import subprocess


def bad_subprocess():
    user_input = input("Enter cmd: ")
    subprocess.run(user_input, shell=True)  


def bad_eval():
    code = input("Enter Python: ")
    eval(code)

def main():
    bad_subprocess()

    bad_eval()

if __name__ == "__main__":
    main()
