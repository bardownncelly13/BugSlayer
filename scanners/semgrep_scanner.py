import json
import subprocess
from typing import List, Dict, Optional, Tuple
import tempfile
import os
import re
from collections import defaultdict
from git_utils.git_ops import git_cmd
from scanners.utils import group_findings_by_file


def scan_code_string(
    code: str,
    configs: Optional[List[str]] = None,
    language: str = "python"
) -> List[Dict]:
    """Scan a code string directly without needing a repo path"""
    if not configs:
        configs = ["p/security-audit"]
    
    # Create temp file with code
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{language}', delete=False) as f:
        f.write(code)
        temp_path = f.name
    
    try:
        cmd = ["semgrep", "scan", "--quiet", "--json"]
        for c in configs:
            cmd += ["--config", c]
        cmd.append(temp_path)
        
        p = subprocess.run(cmd, capture_output=True, text=True)
        
        if p.returncode not in (0, 1):
            raise RuntimeError(f"Semgrep failed: {p.stderr}")
        
        if not p.stdout.strip():
            return []
        
        return json.loads(p.stdout).get("results", [])
    finally:
        os.unlink(temp_path)


def scan_paths(
    paths: List[str],
    repo_root: str = ".",
    configs: Optional[List[str]] = None,
) -> List[Dict]:
    """Scan a list of file paths (relative to repo_root or absolute).

    Skips paths that do not exist and continues on per-file errors.
    Returns a flat list of semgrep result dicts.
    """
    if not configs:
        configs = ["p/security-audit"]

    results: List[Dict] = []
    for p in paths:
        full = p if os.path.isabs(p) else os.path.join(repo_root, p)
        if not os.path.exists(full):
            continue
        try:
            file_results = scan_with_semgrep(repo_path=full, configs=configs)
        except Exception:
            # skip files that cause semgrep/config errors
            continue
        if file_results:
            results.extend(file_results)

    return results


def print_findings(findings: List[Dict]) -> None:
    """Print grouped, human-friendly details for a list of semgrep findings.

    Shows the matched source lines (with context) when the file is available.
    """
    # Accept either a flat list of findings or a grouped dict {file: [findings]}
    if isinstance(findings, dict):
        grouped = findings
    else:
        grouped = group_findings_by_file(findings)
    for file, file_findings in grouped.items():
        print(file)

        # Try to load the source file for context printing
        full_path = file if os.path.isabs(file) else os.path.join(os.getcwd(), file)
        file_lines = None
        if os.path.exists(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as fh:
                    file_lines = fh.read().splitlines()
            except Exception:
                file_lines = None

        for f in file_findings:
            rule = f.get("check_id") or f.get("rule") or f.get("rule_id") or "unknown-rule"
            start_line = f.get("start", {}).get("line")
            end_line = f.get("end", {}).get("line") or start_line
            extra = f.get("extra", {}) or {}
            message = extra.get("message") or f.get("message") or ""
            severity = extra.get("severity") or f.get("severity") or ""
            snippet = extra.get("lines") or extra.get("code") or None

            out = f"  - {rule}: line={start_line} severity={severity} message={message}"
            print(out)

            # If we have the file content, print a small context block
            if file_lines and start_line:
                ctx = 2
                a = max(1, start_line - ctx)
                b = min(len(file_lines), (end_line or start_line) + ctx)
                print("    snippet:")
                for ln in range(a, b + 1):
                    mark = ">>" if start_line and end_line and (ln >= start_line and ln <= end_line) else "  "
                    line_text = file_lines[ln - 1]
                    print(f"      {mark} {ln:4d}: {line_text}")
            else:
                if snippet:
                    print("    snippet:")
                    for ln in (snippet.splitlines() if isinstance(snippet, str) else [snippet]):
                        print(f"      {ln}")
import subprocess
from typing import List, Dict, Optional
import os
from git_utils.git_ops import git_cmd
from scanners.utils import group_findings_by_file


def scan_with_semgrep(
    repo_path: Optional[str] = ".",
    configs: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
) -> List[Dict]:
    if not configs:
        configs = ["p/security-audit"]

    # If a specific path was provided but it doesn't exist, skip scanning.
    if repo_path and repo_path != "." and not os.path.exists(repo_path):
        return []

    cmd = ["semgrep", "scan", "--quiet", "--json"]
    for c in configs:
        cmd += ["--config", c]

    if extra_args:
        cmd += extra_args

    cmd.append(repo_path or ".")

    p = subprocess.run(cmd, capture_output=True, text=True)

    # 0=no findings, 1=findings, 2+ error (bad args/config/etc.)
    if p.returncode not in (0, 1):
        raise RuntimeError(
            "Semgrep failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"Return code: {p.returncode}\n"
            f"stderr:\n{p.stderr}\n"
            f"stdout:\n{p.stdout}\n"
        )

    if not p.stdout.strip():
        return []

    data = json.loads(p.stdout)
    if data.get("errors"):
        raise RuntimeError(
            "Semgrep reported errors in JSON output:\n"
            + json.dumps(data["errors"], indent=2)
        )

    return data.get("results", [])


def _has_diff(base_ref: str, head_ref: str, repo_path: str = ".") -> bool:
    print(f"[DEBUG] _has_diff base_ref={base_ref!r}, head_ref={head_ref!r}, repo_path={repo_path!r}")
    try:
        proc = git_cmd(["diff", "--name-only", f"{base_ref}..{head_ref}"], repo_path)
        print(f"[DEBUG] git diff output:\n{proc.stdout}")
        changed_files = [f for f in proc.stdout.splitlines() if f.strip()]
        print(f"[DEBUG] changed_files={changed_files}")
        return len(changed_files) > 0
    except Exception as e:
        print(f"[DEBUG] git diff failed: {e}")
        return False


def _parse_changed_line_ranges(diff_text: str) -> Dict[str, List[Tuple[int, int]]]:
    """
    Parse unified diff text and return added/modified line ranges per file.

    Returns:
        { "path/to/file.py": [(start_line, end_line), ...], ... }
    """
    ranges: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    current_file: Optional[str] = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current_file = None
            continue

        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                current_file = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
            continue

        if line.startswith("@@") and current_file:
            # Example: @@ -12,0 +13,5 @@
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not m:
                continue
            start = int(m.group(1))
            length = int(m.group(2) or "1")
            if length <= 0:
                continue
            ranges[current_file].append((start, start + length - 1))

    return ranges


def _get_changed_line_ranges(
    base_ref: str,
    head_ref: str,
    repo_path: str = ".",
) -> Dict[str, List[Tuple[int, int]]]:
    proc = git_cmd(["diff", "-U0", f"{base_ref}..{head_ref}"], repo_path)
    return _parse_changed_line_ranges(proc.stdout or "")


def _filter_findings_to_changed_lines(
    findings: List[Dict],
    changed_ranges: Dict[str, List[Tuple[int, int]]],
) -> List[Dict]:
    if not findings or not changed_ranges:
        return []

    def _line_in_ranges(line: int, ranges: List[Tuple[int, int]]) -> bool:
        for start, end in ranges:
            if start <= line <= end:
                return True
        return False

    filtered: List[Dict] = []
    for f in findings:
        path = f.get("path")
        line = f.get("start", {}).get("line")
        if not path or not line:
            continue
        ranges = changed_ranges.get(path)
        if not ranges:
            continue
        if _line_in_ranges(line, ranges):
            filtered.append(f)

    return filtered


def semgrep_scan(
    repo_path: Optional[str] = ".",
    semgrep_config: str = None,
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
) -> Dict[str, List[Dict]]:
    """
    High-level helper:

    - If there is a git diff between base_ref and head_ref, run Semgrep with
      its diff support (baseline-ref) so it only reports findings in changed code.
    - If there is no diff, run a full repository scan.
    - If a scan produces no findings, print "No findings" and return {}.
    """
    print(f"[DEBUG] semgrep_scan called with repo_path={repo_path!r}, base_ref={base_ref!r}, head_ref={head_ref!r}")
    # Resolve semgrep configs
    if semgrep_config and "," in semgrep_config:
        configs = [x.strip() for x in semgrep_config.split(",") if x.strip()]
    elif semgrep_config:
        configs = [semgrep_config]
    else:
        configs = ["p/security-audit", "p/owasp-top-ten"]

    flat_results: List[Dict] = []

    if base_ref and head_ref and _has_diff(base_ref, head_ref, repo_path or "."):
        print(f"[DEBUG] Diff detected; scanning changed files between {base_ref}..{head_ref}")
        changed_ranges = _get_changed_line_ranges(base_ref, head_ref, repo_path or ".")
        changed_files = list(changed_ranges.keys())

        if not changed_files:
            print("[DEBUG] No changed files resolved from diff; running full repo semgrep")
            flat_results = scan_with_semgrep(repo_path=repo_path, configs=configs)
        else:
            flat_results = scan_paths(changed_files, repo_root=repo_path or ".", configs=configs)
            flat_results = _filter_findings_to_changed_lines(flat_results, changed_ranges)
    else:
        print(f"[DEBUG] No diff or diff unavailable; running full repo semgrep")
        flat_results = scan_with_semgrep(repo_path=repo_path, configs=configs)

    if not flat_results:
        print("No findings")
        return {}

    grouped = group_findings_by_file(flat_results)
    return grouped

def main(repo_path: Optional[str] = ".", semgrep_config: str = "", base_ref: str = "origin/main"):
    # compatibility wrapper; base_ref unused for `scan`
    if semgrep_config and "," in semgrep_config:
        configs = [x.strip() for x in semgrep_config.split(",") if x.strip()]
    elif semgrep_config:
        configs = [semgrep_config]
    else:
        configs = ["p/security-audit", "p/owasp-top-ten"]

    return scan_with_semgrep(repo_path=repo_path, configs=configs)
