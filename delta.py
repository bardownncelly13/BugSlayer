from pathlib import Path

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

def normalize_repo_relative(file_path, repo_root):
    """Return a path relative to repo_root, using forward slashes.
    If file_path is relative, it is interpreted relative to repo_root (not cwd).
    """
    repo_abs = Path(repo_root).resolve()
    path = Path(file_path)
    if path.is_absolute():
        rel = path.resolve().relative_to(repo_abs)
    else:
        # Treat as relative to repo root so this works when cwd is not the repo
        full = (repo_abs / path).resolve()
        rel = full.relative_to(repo_abs)
    return rel.as_posix()