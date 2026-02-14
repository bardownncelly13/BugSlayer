from scanners.semgrep_scanner import semgrep_scan, print_findings
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from dotenv import load_dotenv
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from git_utils.git_ops import create_patch_pr, get_diff_for_file, create_temp_repo
from delta import extract_relevant_diff
from patch_validation import validate_patch, attempt_patch_loop
from pathlib import Path
import os
import argparse
import shutil

def main(repo_path: str = ".", semgrep_config: str = None, base_ref: str = "origin/main", head_ref: str = "HEAD"):
    triage = TriageStrategy()
    patcher = PatchStrategy()
    findings = semgrep_scan(repo_path=repo_path, semgrep_config=semgrep_config, base_ref=base_ref, head_ref=head_ref)
    print_findings(findings)

    # For each finding, run triage and (if real) propose a patch
    for file, file_findings in findings.items():
        try:
            file_diff = get_diff_for_file(file, base_ref=base_ref)
            print(f"file diff was extracted as: {file_diff}")
        except Exception as e:
            print(f"get diff for file: {file} failed with exception {e}")
            file_diff = None

        for finding in file_findings:
            line = finding.get("start", {}).get("line")
            diff_snippet = (
                extract_relevant_diff(file_diff, line)
                if file_diff and line
                else None
            )

            # Fallback if extract_relevant_diff or diff_diff_for_file fails
            # Pulls the exact line which the LLM flagged
            if not diff_snippet and line:
                with open(os.path.join(repo_path, file), "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    diff_snippet = lines[line - 1].rstrip("\n")

            context = {
                "file": file,
                "finding": finding,
                "diff": diff_snippet,
            }

            # More debug
            # print(context)

            triage_result = triage.run(context)
            if not triage_result or not triage_result.is_real_issue:
                continue

            context["triage"] = triage_result
            # We can replace this as needed, first solution I thought of was to make it configurable
            MAX_PATCH_ATTEMPTS = int(os.environ.get("MAX_PATCH_ATTEMPTS", 5))

            # Create sandbox clone
            temp_repo_path = create_temp_repo(repo_path)

            # Attempt patch loop
            valid_patch = attempt_patch_loop(
                context=context,
                triage_result=triage_result,
                patcher=patcher,
                temp_repo_path=temp_repo_path,
                original_file_path=file,
                patched_file_path=file,
                max_attempts=MAX_PATCH_ATTEMPTS,
            )

            if not valid_patch:
                print(f"No valid patch generated for {file}")
                shutil.rmtree(temp_repo_path)
                continue

            create_patch_pr(
                repo_path=repo_path,
                finding=finding,
                file=file,
                patch=valid_patch,
                base_ref=base_ref,
            )

            shutil.rmtree(temp_repo_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Path to repo")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref")
    parser.add_argument("--head-ref", default="HEAD", help="Git head ref (commit) to compare against base-ref")
    parser.add_argument("--semgrep-config", default=None, help="Path to Semgrep config YAML")
    parser.add_argument("--run-deps", action="store_true", help="Also run dependency scanner")
    args = parser.parse_args()
    load_dotenv(".env")

    main(repo_path=args.repo, semgrep_config=args.semgrep_config, base_ref=args.base_ref, head_ref=args.head_ref)

