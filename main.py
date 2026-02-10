from scanners.semgrep_scanner import semgrep_scan, print_findings
from scanners.deps_scanner import scan_deps
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
import delta
import argparse
import os
import json

# Default Semgrep config path


def main(repo_path: str = ".", semgrep_config: str = None, base_ref: str = "origin/main", head_ref: str = "HEAD"):
    triage = TriageStrategy()
    patcher = PatchStrategy()
    findings = semgrep_scan(repo_path=repo_path, semgrep_config=semgrep_config, base_ref=base_ref, head_ref=head_ref)
    print_findings(findings)

    # For each finding, run triage and (if real) propose a patch
    for file, file_findings in findings.items():
        try:
            file_diff = delta.get_diff_for_file(file, base_ref=base_ref)
        except Exception:
            file_diff = None

        for finding in file_findings:
            line = finding.get("start", {}).get("line")
            diff_snippet = (
                delta.extract_relevant_diff(file_diff, line)
                if file_diff and line
                else None
            )

            context = {
                "file": file,
                "finding": finding,
                "diff": diff_snippet,
            }

            # Triage
            try:
                triage_result = triage.run(context)
            except Exception as e:
                print(f"Triage failed for {file}:{line}: {e}")
                continue

            if not triage_result or not getattr(triage_result, "is_real_issue", False):
                continue

            context["triage"] = triage_result

            # Patch
            try:
                patch = patcher.run(context)
            except Exception as e:
                print(f"Patch generation failed for {file}:{line}: {e}")
                continue

            if patch:
                print("=== Proposed Patch ===")
                print(patch.diff)
                print("======================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Path to repo")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref")
    parser.add_argument("--head-ref", default="HEAD", help="Git head ref (commit) to compare against base-ref")
    parser.add_argument("--semgrep-config", default=None, help="Path to Semgrep config YAML")
    parser.add_argument("--run-deps", action="store_true", help="Also run dependency scanner")
    args = parser.parse_args()

    main(repo_path=args.repo, semgrep_config=args.semgrep_config, base_ref=args.base_ref, head_ref=args.head_ref)

    if args.run_deps:
        deps = scan_deps(args.repo)
        print("\nDependency scan findings:")
        if not deps:
            print("  (no dependency scanner findings or tools unavailable)")
        else:
            for d in deps:
                print(f"  - {d.get('tool')} {d.get('package')} severity={d.get('severity')} path={d.get('path')}")
