from scanners.semgrep_scanner import scan_with_semgrep
from scanners.utils import group_findings_by_file
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
import argparse
import os
import json

# Default Semgrep config path
DEFAULT_SEMGREP_CONFIG = os.path.join("rules", "owasp_minimal.yml")

def main(repo_path: str = ".", semgrep_config: str = DEFAULT_SEMGREP_CONFIG, base_ref: str = "origin/main"):
    triage = TriageStrategy()
    patcher = PatchStrategy()

    findings = scan_with_semgrep(
        repo_path=args.repo,
        base_ref=args.base_ref,
        config=args.semgrep_config,
    )

    # Use this line to output found issues nicely
    # print(json.dumps(findings, indent=2))

    findings_by_file = group_findings_by_file(findings)

    for file, file_findings in findings_by_file.items():
        for finding in file_findings:
            context = {
                "file": file,
                "finding": finding,
                "diff": None,
            }

            triage_result = triage.run(context)
            if not triage_result or not triage_result.is_real_issue:
                continue

            context["triage"] = triage_result
            patch = patcher.run(context)

            if patch:
                print("=== Proposed Patch ===")
                print(patch.diff)
                print("======================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Path to repo")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref")
    parser.add_argument("--semgrep-config", default=DEFAULT_SEMGREP_CONFIG, help="Path to Semgrep config YAML")
    args = parser.parse_args()

    main(repo_path=args.repo, semgrep_config=args.semgrep_config, base_ref=args.base_ref)
