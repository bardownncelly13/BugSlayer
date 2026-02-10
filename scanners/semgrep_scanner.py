import json
import subprocess
from typing import List, Dict, Optional
import tempfile
import os
import delta
from scanners.utils import group_findings_by_file

def scan_with_semgrep(
    repo_path: Optional[str] = ".",
    configs: Optional[List[str]] = None,
) -> List[Dict]:
    if not configs:
        configs = ["p/security-audit"]

    # If a specific path was provided but it doesn't exist, skip scanning.
    if repo_path and repo_path != "." and not os.path.exists(repo_path):
        return []

    cmd = ["semgrep", "scan", "--quiet", "--json"]
    for c in configs:
        cmd += ["--config", c]
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
    # If semgrep had config errors, they show up here:
    if data.get("errors"):
        # Treat as failure (optional). If you prefer, return results anyway.
        raise RuntimeError("Semgrep reported errors in JSON output:\n" + json.dumps(data["errors"], indent=2))

    return data.get("results", [])

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

def main(repo_path: Optional[str] = ".", semgrep_config: str = "", base_ref: str = "origin/main"):
    # compatibility wrapper; base_ref unused for `scan`
    if semgrep_config and "," in semgrep_config:
        configs = [x.strip() for x in semgrep_config.split(",") if x.strip()]
    elif semgrep_config:
        configs = [semgrep_config]
    else:
        configs = ["p/security-audit", "p/owasp-top-ten"]

    return scan_with_semgrep(repo_path=repo_path, configs=configs)


def semgrep_scan(
    repo_path: Optional[str] = ".",
    semgrep_config: str = None,
    base_ref: str = "origin/main",
    head_ref: str = "HEAD",
) -> Dict[str, List[Dict]]:
    """High-level helper: resolve configs, get changed files between `base_ref` and `head_ref`, and scan only those files.

    Returns a dict mapping file path -> list of semgrep finding dicts (grouped by file).
    """
    # Resolve semgrep configs
    if semgrep_config and "," in semgrep_config:
        configs = [x.strip() for x in semgrep_config.split(",") if x.strip()]
    elif semgrep_config:
        configs = [semgrep_config]
    else:
        configs = ["p/security-audit", "p/owasp-top-ten"]

    # Determine changed files via git: prefer files changed between base_ref..head_ref
    try:
        if base_ref and head_ref:
            proc = delta.git_cmd(["diff", "--name-only", f"{base_ref}..{head_ref}"], repo_path)
            changed_files = [f for f in proc.stdout.splitlines() if f.strip()]
        else:
            proc = delta.git_cmd(["show", "--name-only", "--pretty=", head_ref or "HEAD"], repo_path)
            changed_files = [f for f in proc.stdout.splitlines() if f.strip()]
    except Exception:
        changed_files = []

    flat: List[Dict] = []
    if changed_files:
        # Debug: show which files will be scanned
        print(f"Scanning files from commit range {base_ref}..{head_ref}: {changed_files}")
        flat = scan_paths(changed_files, repo_root=repo_path, configs=configs)
        # If none of the changed files exist (e.g., only deletions), fall back to full repo
        if not flat:
            print("No findings from changed files; falling back to full repo scan")
            flat = scan_with_semgrep(repo_path=repo_path, configs=configs)
    else:
        print(f"No changed files between {base_ref} and {head_ref}; scanning full repository")
        flat = scan_with_semgrep(repo_path=repo_path, configs=configs)

    # Group findings by file for easier parsing by callers
    grouped = group_findings_by_file(flat)
    return grouped