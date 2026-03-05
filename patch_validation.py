import difflib
from validators.registry import get_validator
from validators.base import ValidationError
from git_utils.git_ops import apply_patch, reset_temp_repo
from scanners.semgrep_scanner import scan_paths
import os

def format_findings(findings):
    formatted = []

    for f in findings:
        check_id = f.get("check_id")
        message = f.get("extra", {}).get("message", "")
        line = f.get("start", {}).get("line", "?")
        snippet = f.get("extra", {}).get("lines", "").strip()

        formatted.append(
            f"""Rule: {check_id}
            Line: {line}
            Message: {message}
            Code:
            {snippet}
            """
        )

    return "\n---\n".join(formatted)

def fingerprint(findings):
    return {
        (
            f.get("check_id"),
            f.get("start", {}).get("line")
        )
        for f in findings
    }

def count_non_comment_lines(text: str) -> int:
    lines = text.splitlines()
    count = 0
    for line in lines:
        stripped = line.strip()
        # Slightly scuffed condition but should hold generally
        if stripped and not stripped.startswith(("#", "//", "/*", "*")):
            count += 1
    return count

def is_patch_comment_out(old: str, new: str) -> bool:
    """
    Returns True if the new patch is just commenting out the old line.
    """
    old_line = old.strip()
    new_line = new.strip()

    # exact comment
    if new_line == f"# {old_line}":
        return True

    # slightly modified comment (e.g., LLM added extra text)
    if old_line in new_line.replace("#", "") and "#" in new_line:
        return True

    return False

def destructive_change_detected(original: str, patched: str) -> bool:
    original_loc = count_non_comment_lines(original)
    patched_loc = count_non_comment_lines(patched)

    if original_loc == 0:
        return False

    # Major LOC reduction
    if patched_loc < original_loc * 0.7:
        return True

    # Executable line replaced by comment
    diff = list(difflib.unified_diff(
        original.splitlines(),
        patched.splitlines(),
        lineterm=""
    ))

    for line in diff:
        if line.startswith("-") and not line.startswith("---"):
            removed_line = line[1:].strip()
            if removed_line and not removed_line.startswith(("#", "//")):
                # Check if corresponding added line is comment
                # Simple heuristic: next line in diff
                # (Not perfect but effective)
                continue

    return False


def validate_patch(repo_path: str, original_file: str, patched_file: str) -> bool:
    # Syntax validation
    validator = get_validator(repo_path)
    # try:
    #     validator.syntax_check()
    # except ValidationError as e:
    #     print(f"[VALIDATION] Syntax failed:\n{e}")
    #     return False

    # Destructive heuristic
    with open(original_file) as f:
        original = f.read()

    with open(patched_file) as f:
        patched = f.read()

    if destructive_change_detected(original, patched):
        print("[VALIDATION] Destructive change detected.")
        return False

    return True

def attempt_patch_loop(
    context,
    all_findings,
    patcher,
    temp_repo_path,
    original_file_path,
    patched_file_path,
    max_attempts=5,
):
    failure_reasons = []

    for attempt in range(1, max_attempts + 1):
        # Add previous failures to context for LLM feedback
        context["previous_failures"] = failure_reasons

        patch = patcher.run(context)

        # Reject patches that just comment out the old line
        old_line = patch.old.strip()
        new_lines = patch.new.splitlines()

        commented_out = any(
            old_line in line and line.strip().startswith("#") 
            for line in new_lines
        )

        if commented_out:
            reason = f"Attempt rejected: patch just comments out old line.\nold={patch.old}\nnew={patch.new}"
            print(reason)
            failure_reasons.append(reason)
            continue

        # Apply patch in temp repo
        try:
            apply_patch(temp_repo_path, original_file_path, patch.old, patch.new)
        except ValueError as e:
            reason = f"Attempt {attempt} failed: {str(e)}"
            print(reason)
            print(patch.old)
            failure_reasons.append(reason)
            continue

        # Validate patch (syntax, tests, etc.)
        if not validate_patch(temp_repo_path, original_file_path, patched_file_path):
            reason = f"Attempt {attempt} failed validation."
            print(reason)
            failure_reasons.append(f"Attempt {attempt}: old={patch.old} new={patch.new} failed validation")

            reset_temp_repo(temp_repo_path)
            continue

        # Re-scan patched file
        # print(f"New Patch: {patch.new}")
        # print("Scanning repo root:", temp_repo_path)
        # print("Scanning file path:", original_file_path)
        # print("Absolute file being scanned:", os.path.join(temp_repo_path, original_file_path))

        baseline_findings = all_findings.get(original_file_path, [])
        baseline_fp = fingerprint(baseline_findings)

        new_findings = scan_paths(
            paths=[original_file_path],
            repo_root=temp_repo_path,
            configs=["p/security-audit", "p/owasp-top-ten"]
        )

        new_fp = fingerprint(new_findings)

        # Check if original finding still present
        original_rule = context['finding'].get("check_id")

        still_present = any(
            f.get("check_id") == original_rule
            for f in new_findings
        )

        # print(f"Bug is still present? {still_present}")

        if still_present:
            reason = f"Attempt {attempt}: original vulnerability still present after patch."
            failure_reasons.append(reason)
            reset_temp_repo(temp_repo_path)
            continue

        # Should only have vulnerabilities that did not exist pre-patch
        introduced = new_fp - baseline_fp

        # Check if new vulnerabilities introduced
        if introduced:
            detailed = format_findings(new_findings)

            reason = f"""
            Attempt {attempt} rejected.
            The patch introduced new vulnerabilities:

            {detailed}

            You must fix the original issue WITHOUT introducing these patterns.
            """
            # print(reason)
            failure_reasons.append(reason)

            reset_temp_repo(temp_repo_path)
            continue

        # Success
        return patch

    # Exhausted all attempts
    print(f"Patch generation failed after {max_attempts} attempts. Failures:\n" + "\n".join(failure_reasons))
    return None
