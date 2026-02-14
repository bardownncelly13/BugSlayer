from .base import LanguageValidator


class GoValidator(LanguageValidator):
    def syntax_check(self) -> None:
        self.run_cmd(["go", "build", "./..."])
