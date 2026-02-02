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


def extract_relevant_diff(diff: str, line: int, context_lines: int = 3) -> str:
    """
    Extract the diff hunk that contains or is closest to a given line.
    """
    lines = diff.splitlines()
    hunk = []
    in_hunk = False
    hunk_start = None
    hunk_end = None

    for i, l in enumerate(lines):
        if l.startswith("@@"):
            parts = l.split()
            for p in parts:
                if p.startswith("+"):
                    start = int(p.split(",")[0][1:])
                    length = int(p.split(",")[1]) if "," in p else 1
                    hunk_start = start
                    hunk_end = start + length
            in_hunk = hunk_start <= line <= hunk_end
            hunk = [l] if in_hunk else []
        elif in_hunk:
            hunk.append(l)

    return "\n".join(hunk)
