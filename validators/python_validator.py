from .base import LanguageValidator


class PythonValidator(LanguageValidator):
    def syntax_check(self) -> None:
        # Compile all Python files in repo
        self.run_cmd(["python", "-m", "compileall", "."])
