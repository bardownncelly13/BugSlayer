from scanners.semgrep_scanner import scan_with_semgrep
from scanners.utils import group_findings_by_file
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from git_utils.git_ops import run_git, stage_files, commit_changes, apply_patch, create_branch, get_diff_for_file
from delta import extract_relevant_diff
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
        file_diff = get_diff_for_file(file, base_ref=args.base_ref)

        for finding in file_findings:
            line = finding.get("start", {}).get("line")
            diff_snippet = (
                extract_relevant_diff(file_diff, line)
                if file_diff and line
                else None
            )

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
            patch = patcher.run(context)
            
            # Temporary solution before the fuzzing and improved patching is in place
            # TODO Update once new structure is done
            if not patch or not patch.old or not patch.new:
                print(f"No patch generated for {file}")
                continue

            branch_name = f"llm-fix/{finding['check_id']}-{file.replace('/', '-')}"
            commit_message = f"fix(security): {finding['extra'].get('message', '')}"

            files_changed = [file]

            print("=== Dry Run ===")
            print("Branch:", branch_name)
            print("Commit message:", commit_message)
            print("Files changed:", files_changed)
            print("Risk level:", patch.risk)
            print("Old snippet:\n", patch.old)
            print("New snippet:\n", patch.new)
            print("================\n")

            # Apply patch locally
            create_branch(repo_path, branch_name)

            apply_patch(
                repo_path=repo_path,
                file_path=file,
                old=patch.old,
                new=patch.new,
            )

            stage_files(repo_path, files_changed)
            commit_changes(repo_path, commit_message, author="LLM Bot <bot@example.com>")

            # Switch back to the previous branch
            run_git(["checkout", "-"], repo_path)

            # if patch:
            #     print("=== Proposed Patch ===")
            #     print(patch.diff)
            #     print("======================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Path to repo")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref")
    parser.add_argument("--semgrep-config", default=DEFAULT_SEMGREP_CONFIG, help="Path to Semgrep config YAML")
    args = parser.parse_args()

    main(repo_path=args.repo, semgrep_config=args.semgrep_config, base_ref=args.base_ref)
