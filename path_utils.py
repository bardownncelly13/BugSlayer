from pathlib import Path
import os
import re


def normalize_path_for_runtime(path_value: str, resolve_relative: bool = True) -> str:
    """
    Normalize a path for the current runtime (Windows or POSIX/WSL).

    Handles:
    - Absolute POSIX paths (/home/user/repo, /mnt/c/...)
    - Absolute Windows paths (C:\\Users\\... or C:/Users/...)
    - Windows drive-prefixed form missing slash (C:Users\\...)
    - Relative paths
    """
    raw = str(path_value).strip().strip("\"'")
    # Guard against a common shell-escaping issue where Windows backslashes are
    # consumed before Python receives argv, e.g.:
    #   C:\Users\me\repo  ->  C:Usersmerepo
    # This form is ambiguous and cannot be safely reconstructed.
    if re.match(r"^[A-Za-z]:[^\\/].*", raw) and os.name != "nt":
        raise ValueError(
            "Malformed Windows path (missing separators after drive letter). "
            "Use one of: C:/path/to/repo, /mnt/c/path/to/repo, "
            "or quote/escape backslashes so they are preserved."
        )

    m = re.match(r"^([A-Za-z]):(?:[\\/](.*)|(.*))$", raw)
    if m and os.name != "nt":
        drive = m.group(1).lower()
        rest = (m.group(2) or m.group(3) or "").replace("\\", "/").lstrip("/")
        return str(Path(f"/mnt/{drive}/{rest}").resolve())
    p = Path(raw)
    if p.is_absolute():
        return str(p.resolve())
    return str(p.resolve()) if resolve_relative else raw
