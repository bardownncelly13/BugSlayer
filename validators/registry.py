from pathlib import Path
from .python_validator import PythonValidator
from .go_validator import GoValidator
from .rust_validator import RustValidator
from .cpp_validator import CppValidator
from .generic_validator import GenericValidator


EXTENSION_MAP = {
    ".py": PythonValidator,
    ".go": GoValidator,
    ".rs": RustValidator,
    ".cpp": CppValidator,
    ".cc": CppValidator,
    ".c": CppValidator,
}


def get_validator(repo_path: str):
    repo = Path(repo_path)

    extensions = {p.suffix for p in repo.rglob("*") if p.is_file()}

    for ext, validator_cls in EXTENSION_MAP.items():
        if ext in extensions:
            return validator_cls(repo_path)

    return GenericValidator(repo_path)
