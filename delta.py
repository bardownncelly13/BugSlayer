import subprocess
from typing import List

def get_changed_files(base_ref: str = "origin/main") -> List[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def get_diff_for_file(path: str, base_ref: str = "origin/main") -> str:
    result = subprocess.run(
        ["git", "diff", base_ref, "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
