from .base import LanguageValidator
from pathlib import Path


class RustValidator(LanguageValidator):
    def syntax_check(self) -> None:
        if (self.repo_path / "Cargo.toml").exists():
            self.run_cmd(["cargo", "check"])
        else:
            # Fallback: check individual files
            for file in self.repo_path.rglob("*.rs"):
                self.run_cmd(["rustc", "--emit=metadata", str(file)])
