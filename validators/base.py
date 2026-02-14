from abc import ABC, abstractmethod
from pathlib import Path
import subprocess


class ValidationError(Exception):
    pass


class LanguageValidator(ABC):
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    @abstractmethod
    def syntax_check(self) -> None:
        """
        Raise ValidationError if syntax fails.
        """
        pass

    def run_cmd(self, cmd: list[str]) -> None:
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValidationError(
                f"Command failed: {' '.join(cmd)}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
