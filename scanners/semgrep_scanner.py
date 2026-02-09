import json
import subprocess
from typing import List, Dict, Optional

def scan_with_semgrep(
    repo_path: Optional[str] = ".",
    configs: Optional[List[str]] = None,
) -> List[Dict]:
    if not configs:
        configs = ["p/security-audit"]

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

def main(repo_path: Optional[str] = ".", semgrep_config: str = "", base_ref: str = "origin/main"):
    # compatibility wrapper; base_ref unused for `scan`
    if semgrep_config and "," in semgrep_config:
        configs = [x.strip() for x in semgrep_config.split(",") if x.strip()]
    elif semgrep_config:
        configs = [semgrep_config]
    else:
        configs = ["p/security-audit", "p/owasp-top-ten"]

    return scan_with_semgrep(repo_path=repo_path, configs=configs)