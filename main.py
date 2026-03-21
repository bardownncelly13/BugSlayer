from scanners.semgrep_scanner import semgrep_scan, print_findings
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from dotenv import load_dotenv
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from git_utils.git_ops import (
    create_patch_pr,
    get_diff_for_file,
    create_temp_repo,
    resolve_effective_base_ref,
    resolve_pr_base_branch,
)
from delta import extract_relevant_diff, normalize_repo_relative
from patch_validation import attempt_patch_loop
from pathlib import Path
import os
import argparse
import shutil
from time import ctime
from path_utils import normalize_path_for_runtime

def main(repo_path: str = ".", semgrep_config: str = None, base_ref: str = "origin/main", head_ref: str = "HEAD"):
    repo_path = normalize_path_for_runtime(repo_path)
    effective_base_ref = resolve_effective_base_ref(repo_path, base_ref)
    pr_base_branch = resolve_pr_base_branch(repo_path, effective_base_ref)
    print(f"[DEBUG] requested base_ref={base_ref!r}, effective_base_ref={effective_base_ref!r}, pr_base_branch={pr_base_branch!r}")

    triage = TriageStrategy()
    patcher = PatchStrategy()
    findings = semgrep_scan(repo_path=repo_path, semgrep_config=semgrep_config, base_ref=effective_base_ref, head_ref=head_ref)
    print_findings(findings)

    # If a Gemini API key is configured, run a complementary LLM-based scan
    # over the same repository (changed files when base_ref provided).
    # if os.getenv("GEMINI_API_KEY"):
    #     try:
    #         from scanners.flashscan import gemini_scan, print_gemini_findings, gemini_findings_to_json

    #         try:
    #             gemini_findings = gemini_scan(repo_path=repo_path, base_ref=effective_base_ref, head_ref=head_ref)
    #             print_gemini_findings(gemini_findings)
    #             if gemini_findings:
    #                 print("\n=== Gemini Results (JSON) ===\n")
    #                 print(gemini_findings_to_json(gemini_findings))
    #         except Exception as e:
    #             print(f"Gemini scan failed: {e}")
    #     except Exception:
    #         # If flashscan or its optional deps are unavailable, continue silently
    #         print("Gemini scanner not available (missing dependency or import error)")
    # else:
    #     print("no geminai api key")

    # For each finding, run triage and (if real) propose a patch
    for file, file_findings in findings.items():
        # print("Inside loop")
        try:
            file_diff = get_diff_for_file(file, base_ref=effective_base_ref, repo_path=repo_path)
            # print(f"file diff was extracted as: {file_diff}")
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
                repo_abs = Path(repo_path)
                # file is repo-relative from semgrep; resolve against repo root
                full_path = (repo_abs / file).resolve()
                if full_path.exists():
                    with open(full_path, "r", encoding="utf-8") as f:
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
            # Make filename relative to repo_path
            file = normalize_repo_relative(file, repo_path)

            # Create sandbox clone
            temp_repo_path = create_temp_repo(repo_path)

            # Attempt patch loop
            valid_patch = attempt_patch_loop(
                context=context,
                all_findings=findings,
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

            # if DRY_RUN:
            #     print(f"[DRY RUN] Would create PR for {file}")
            # else:
            #     print(f"This should not run")
            create_patch_pr(
                repo_path=repo_path,
                finding=finding,
                file=file,
                patch=valid_patch,
                pr_base_branch=pr_base_branch,
            )
            shutil.rmtree(temp_repo_path)
    print(f"Finished at {ctime()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="Path to repo")
    parser.add_argument("--base-ref", default="origin/main", help="Git base ref")
    parser.add_argument("--head-ref", default="HEAD", help="Git head ref (commit) to compare against base-ref")
    parser.add_argument("--semgrep-config", default=None, help="Path to Semgrep config YAML")
    parser.add_argument("--run-deps", action="store_true", help="Also run dependency scanner")
    args = parser.parse_args()
    load_dotenv(".env")
    DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
    # repo_path = os.path.abspath(os.path.normpath(args.repo))

    # print("CWD:", os.getcwd())
    # print("Raw repo arg:", args.repo)
    # print("Resolved:", os.path.abspath(args.repo))

    # print(f"Resolved repo path: {repo_path}")

    print(f"Starting at {ctime()}")
    main(repo_path=args.repo, semgrep_config=args.semgrep_config, base_ref=args.base_ref, head_ref=args.head_ref)

