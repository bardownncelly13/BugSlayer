import json
import subprocess
import os
import tempfile
from typing import List, Dict, Optional


def _run_cmd(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


def find_manifests(repo_root: str) -> List[str]:
    candidates = [
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "package.json",
        "yarn.lock",
        "Gemfile",
        "go.mod",
    ]
    found = []
    for c in candidates:
        p = os.path.join(repo_root, c)
        if os.path.exists(p):
            found.append(p)
    return found


def scan_requirements_with_pip_audit(req_path: str) -> List[Dict]:
    """Run `pip-audit -r requirements.txt --format=json` if available and parse results."""
    try:
        p = _run_cmd(["pip-audit", "-r", req_path, "--format", "json"]) 
    except FileNotFoundError:
        return []

    if p.returncode not in (0, 1):
        return []

    if not p.stdout.strip():
        return []

    try:
        data = json.loads(p.stdout)
    except Exception:
        return []

    findings: List[Dict] = []
    # pip-audit json schema may include 'vulnerabilities' list
    for v in data.get("vulnerabilities", []):
        findings.append({
            "tool": "pip-audit",
            "path": req_path,
            "package": v.get("package", {}).get("name"),
            "installed_version": v.get("package", {}).get("version"),
            "id": v.get("id") or v.get("vuln_id"),
            "description": v.get("description") or v.get("details"),
            "severity": v.get("severity"),
            "url": v.get("url"),
            "raw": v,
        })

    return findings


def scan_package_json_with_npm(repo_root: str) -> List[Dict]:
    """Run `npm audit --json` if npm is available and parse vulnerabilities."""
    try:
        p = _run_cmd(["npm", "audit", "--json"], cwd=repo_root)
    except FileNotFoundError:
        return []

    if p.returncode not in (0, 1):
        return []

    if not p.stdout.strip():
        return []

    try:
        data = json.loads(p.stdout)
    except Exception:
        return []

    findings: List[Dict] = []

    # Modern npm uses `vulnerabilities` mapping
    vulns = data.get("vulnerabilities") or {}
    for pkg, info in vulns.items():
        findings.append({
            "tool": "npm audit",
            "path": os.path.join(repo_root, "package.json"),
            "package": pkg,
            "installed_version": None,
            "severity": info.get("severity"),
            "title": info.get("title"),
            "url": info.get("url") or info.get("recommendation"),
            "details": info,
            "raw": info,
        })

    # Older npm returns `advisories`
    if not findings and "advisories" in data:
        for aid, adv in data.get("advisories", {}).items():
            findings.append({
                "tool": "npm audit",
                "path": os.path.join(repo_root, "package.json"),
                "package": adv.get("module_name"),
                "installed_version": adv.get("vulnerable_versions"),
                "severity": adv.get("severity"),
                "title": adv.get("title"),
                "url": adv.get("url"),
                "details": adv,
                "raw": adv,
            })

    return findings


def scan_with_dep_scan(repo_root: str) -> List[Dict]:
    """Run OWASP Dep-Scan (try common binary names) and parse JSON output into findings.

    Returns list of normalized findings.
    """
    candidates = ["dep-scan", "owasp-depscan", "owasp-dep-scan"]
    for bin_name in candidates:
        try:
            with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as tf:
                out_path = tf.name
            rc = subprocess.run([bin_name, "--output-format", "json", "--output-file", out_path, repo_root], capture_output=True, text=True)
            if rc.returncode != 0:
                # remove temp file if created
                if os.path.exists(out_path):
                    try:
                        os.unlink(out_path)
                    except Exception:
                        pass
                continue

            if not os.path.exists(out_path):
                continue

            with open(out_path, "r", encoding="utf-8") as fh:
                try:
                    data = json.load(fh)
                except Exception:
                    data = None
            try:
                os.unlink(out_path)
            except Exception:
                pass

            if not data:
                continue

            results: List[Dict] = []
            candidates_list = []
            if isinstance(data, dict):
                for key in ("vulnerabilities", "matches", "findings", "results"):
                    if key in data and isinstance(data[key], list):
                        candidates_list = data[key]
                        break
                if not candidates_list and "dependencies" in data and isinstance(data["dependencies"], list):
                    candidates_list = data["dependencies"]
            elif isinstance(data, list):
                candidates_list = data

            for item in candidates_list:
                pkg = item.get("package") or item.get("component") or item.get("name")
                ver = item.get("version") or item.get("installedVersion") or item.get("componentVersion")
                title = item.get("title") or item.get("name") or item.get("id")
                severity = item.get("severity") or item.get("cvss_score") or item.get("rating")
                desc = item.get("description") or item.get("detail") or item.get("description_short")
                refs = item.get("references") or item.get("reference") or item.get("url")
                results.append({
                    "tool": bin_name,
                    "path": repo_root,
                    "package": pkg,
                    "installed_version": ver,
                    "id": item.get("id") or item.get("vulnId") or None,
                    "title": title,
                    "description": desc,
                    "severity": severity,
                    "references": refs,
                    "raw": item,
                })

            if results:
                return results

        except FileNotFoundError:
            continue
        except Exception:
            continue

    return []


def scan_deps(repo_root: str = ".") -> List[Dict]:
    """Top-level dependency scanner. Detects manifests and runs available tooling.

    Returns a flat list of findings; each finding is a dict describing a vulnerable dependency.
    """
    manifests = find_manifests(repo_root)
    results: List[Dict] = []

    # Try OWASP dep-scan first
    dep_scan_results = scan_with_dep_scan(repo_root)
    if dep_scan_results:
        return dep_scan_results

    # Fallback to per-ecosystem scanners if dep-scan not available or produced no results
    for m in manifests:
        base = os.path.basename(m)
        if base == "requirements.txt":
            results.extend(scan_requirements_with_pip_audit(m))
        elif base == "package.json":
            results.extend(scan_package_json_with_npm(repo_root))

    return results
