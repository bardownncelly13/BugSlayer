from scanners.semgrep_scanner import semgrep_scan, print_findings
from strategies.triage import TriageStrategy
from strategies.patch import PatchStrategy
from dotenv import load_dotenv
from git_utils.git_ops import (
    create_patch_pr,
    create_failure_pr,
    get_diff_for_file,
    create_temp_repo,
    resolve_effective_base_ref,
    resolve_pr_base_branch,
)
from delta import normalize_repo_relative
from patch_validation import attempt_patch_loop
from codetracing.taint_pipeline import (
    build_taint_sink_code_context,
    load_taint_findings_jsonl,
    parse_vuln_fn_key,
    synthetic_finding_from_taint_row,
    taint_contract_excerpt,
)
from pathlib import Path
import os
import argparse
import shutil
from time import ctime
from path_utils import normalize_path_for_runtime
import sys

# Add repo root and codetracing to path for codetracing imports
REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "codetracing"))

from codetracing.createCallgraph import main as create_callgraph_main
from codetracing.update_funcs_from_gemini import main as update_funcs_from_gemini_main
from codetracing.update_funcs_from_semgrep import apply_semgrep_findings_to_neo4j
from codetracing.tainttrace.run_tainttrace import main as run_tainttrace_main

def main(repo_path: str = ".", semgrep_config: str = None, base_ref: str = "origin/main", head_ref: str = "HEAD"):
    repo_path = normalize_path_for_runtime(repo_path)
    effective_base_ref = resolve_effective_base_ref(repo_path, base_ref)
    pr_base_branch = resolve_pr_base_branch(repo_path, effective_base_ref)
    print(f"[DEBUG] requested base_ref={base_ref!r}, effective_base_ref={effective_base_ref!r}, pr_base_branch={pr_base_branch!r}")

    # Create call graph first
    print("[*] Creating call graph...")
    create_callgraph_main()

    triage = TriageStrategy()
    patcher = PatchStrategy()
    findings = semgrep_scan(repo_path=repo_path, semgrep_config=semgrep_config, base_ref=effective_base_ref, head_ref=head_ref)
    print_findings(findings)

    # Mark enclosing functions as vulnerable in Neo4j so taint trace can reach them from entrypoints.
    apply_semgrep_findings_to_neo4j(findings, repo_path)

    # If a Gemini API key is configured, run a complementary LLM-based scan
    # over the same repository (changed files when base_ref provided).
    if os.getenv("GEMINI_API_KEY"):
        try:
            from scanners.flashscan import gemini_scan, print_gemini_findings, gemini_findings_to_json
            try:
                gemini_findings = gemini_scan(repo_path=repo_path, base_ref=effective_base_ref, head_ref=head_ref)
                print_gemini_findings(gemini_findings)
                # if gemini_findings:
                    # print("\n=== Gemini Results (JSON) ===\n")
                    # print(gemini_findings_to_json(gemini_findings))
            except Exception as e:
                print(f"Gemini scan failed: {e}")
        except Exception:
            # If flashscan or its optional deps are unavailable, continue silently
            print("Gemini scanner not available (missing dependency or import error)")
    else:
        print("no geminai api key")

    # Update functions from Gemini results
    print("[*] Updating functions from Gemini results...")
    update_funcs_from_gemini_main()

    # Run taint trace
    print("[*] Running taint trace...")
    run_tainttrace_main()

    taint_path = os.environ.get("TAINT_FINDINGS_JSONL")
    if not taint_path:
        candidates = (
            os.path.join(repo_path, "taint_findings.jsonl"),
            os.path.join(os.getcwd(), "taint_findings.jsonl"),
            os.path.join(REPO_ROOT, "taint_findings.jsonl"),
        )
        taint_path = next((p for p in candidates if os.path.isfile(p)), candidates[0])
    taint_rows = load_taint_findings_jsonl(taint_path)
    if not taint_rows:
        print(f"[taint] No rows in {taint_path!r}; skipping triage/patch loop.")

    # One iteration per taint row (entrypoint → sink)
    for idx, taint_row in enumerate(taint_rows):
        try:
            file, _vuln_line = parse_vuln_fn_key(taint_row["vuln"])
        except (KeyError, ValueError) as e:
            print(f"[taint] skip row {idx}: {e}")
            continue

        finding = synthetic_finding_from_taint_row(taint_row)

        try:
            file_diff = get_diff_for_file(file, base_ref=effective_base_ref, repo_path=repo_path)
            # print(f"file diff was extracted as: {file_diff}")
        except Exception as e:
            print(f"get diff for file: {file} failed with exception {e}")
            file_diff = None

        diff_snippet = build_taint_sink_code_context(repo_path, taint_row["vuln"])
        if not (diff_snippet and diff_snippet.strip()):
            line = finding.get("start", {}).get("line")
            if line:
                repo_abs = Path(repo_path)
                full_path = (repo_abs / file).resolve()
                if full_path.exists():
                    with open(full_path, "r", encoding="utf-8") as f:
                        flines = f.readlines()
                        if 0 < line <= len(flines):
                            diff_snippet = flines[line - 1].rstrip("\n")
        diff_snippet = (diff_snippet or "") + taint_contract_excerpt(taint_row)

        context = {
            "file": file,
            "finding": finding,
            "diff": diff_snippet,
        }

        triage_result = triage.run(context)
        if not triage_result or not triage_result.is_real_issue:
            continue

        context["triage"] = triage_result
        MAX_PATCH_ATTEMPTS = int(os.environ.get("MAX_PATCH_ATTEMPTS", 5))
        file = normalize_repo_relative(file, repo_path)

        temp_repo_path = create_temp_repo(repo_path)

        valid_patch = attempt_patch_loop(
            context=context,
            all_findings={},
            patcher=patcher,
            temp_repo_path=temp_repo_path,
            original_file_path=file,
            patched_file_path=file,
            max_attempts=MAX_PATCH_ATTEMPTS,
        )

        if not valid_patch:
            print(f"No valid patch generated for {file}")
            create_failure_pr(
                repo_path=repo_path,
                finding=finding,
                file=file,
                pr_base_branch=pr_base_branch,
                max_attempts=MAX_PATCH_ATTEMPTS,
            )
            shutil.rmtree(temp_repo_path)
            continue

        create_patch_pr(
            repo_path=repo_path,
            finding=finding,
            file=file,
            patch=valid_patch,
            pr_base_branch=pr_base_branch,
        )
        shutil.rmtree(temp_repo_path)
    print(f"Finished at {ctime()}")

    # Exit with code 1 if taint rows exist (CI: actionable reachability findings)
    if taint_rows:
        exit(1)
    else:
        exit(0)


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

