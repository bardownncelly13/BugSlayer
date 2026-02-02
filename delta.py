import subprocess
from typing import List, Optional

def git_cmd(args: List[str], repo_path: Optional[str] = None) -> subprocess.CompletedProcess:
    cmd = ["git"]
    if repo_path:
        cmd += ["-C", repo_path]
    cmd += args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )

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
