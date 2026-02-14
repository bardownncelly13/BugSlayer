from .base import LanguageValidator
from pathlib import Path


class CppValidator(LanguageValidator):
    def syntax_check(self) -> None:
        for file in self.repo_path.rglob("*.cpp"):
            self.run_cmd(["g++", "-fsyntax-only", str(file)])
