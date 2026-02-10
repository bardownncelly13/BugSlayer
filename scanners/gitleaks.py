#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import tempfile
from typing import List, Dict

IMAGE_DEFAULT = "zricethezav/gitleaks:v8.18.4"

def scan_with_gitleaks_docker(repo_path: str, scan_git_history: bool = False, image: str = IMAGE_DEFAULT) -> List[Dict]:
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        raise SystemExit(f"--repo is not a directory: {repo_path}")

    with tempfile.TemporaryDirectory() as tmpout:
        report_host_path = os.path.join(tmpout, "gitleaks.json")

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{repo_path}:/repo:ro",
        ]

        # Mask venv dirs only if they exist on host (so mountpoints exist in /repo)
        if os.path.isdir(os.path.join(repo_path, ".venv")):
            cmd += ["--tmpfs", "/repo/.venv:ro"]
        if os.path.isdir(os.path.join(repo_path, "venv")):
            cmd += ["--tmpfs", "/repo/venv:ro"]

        cmd += [
            "-v", f"{tmpout}:/out",
            image,
            "detect",
            "--source", "/repo",
            "--report-format", "json",
            "--report-path", "/out/gitleaks.json",
        ]

        if not scan_git_history:
            cmd.append("--no-git")

        p = subprocess.run(cmd, capture_output=True, text=True)

        if p.returncode not in (0, 1):
            raise RuntimeError(
                "Gitleaks failed.\n"
                f"Command: {' '.join(cmd)}\n"
                f"rc={p.returncode}\n"
                f"stderr:\n{p.stderr}\n"
                f"stdout:\n{p.stdout}\n"
            )

        if not os.path.exists(report_host_path) or os.path.getsize(report_host_path) == 0:
            return []

        with open(report_host_path, "r", encoding="utf-8") as f:
            return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Repo/folder to scan")
    ap.add_argument("--history", action="store_true", help="Scan git history (committed content)")
    ap.add_argument("--image", default=IMAGE_DEFAULT)
    args = ap.parse_args()

    leaks = scan_with_gitleaks_docker(args.repo, scan_git_history=args.history, image=args.image)
    print(json.dumps(leaks, indent=2))
    raise SystemExit(1 if leaks else 0)

if __name__ == "__main__":
    main()