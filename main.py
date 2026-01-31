from scanners.semgrep_scanner import scan_with_semgrep
from scanners.utils import group_findings_by_file
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(description="Diff-based code scanner")
    parser.add_argument("--repo", default=None, help="Path to git repo")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--semgrep-config", default="p/ci")
    args = parser.parse_args()

    triage = TriageStrategy()
    patcher = PatchStrategy()

    findings = scan_with_semgrep(
        repo_path=args.repo,
        base_ref=args.base_ref,
        config=args.semgrep_config,
    )

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
    main()
