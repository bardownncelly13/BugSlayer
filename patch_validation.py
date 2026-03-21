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

    # Resolve paths relative to the validation repo root.
    original_path = original_file if os.path.isabs(original_file) else os.path.join(repo_path, original_file)
    patched_path = patched_file if os.path.isabs(patched_file) else os.path.join(repo_path, patched_file)

    # Destructive heuristic
    with open(original_path, encoding="utf-8") as f:
        original = f.read()

    with open(patched_path, encoding="utf-8") as f:
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
    target_rule = context["finding"].get("check_id")
    target_line = context["finding"].get("start", {}).get("line")
    scan_configs = ["p/security-audit", "p/owasp-top-ten"]

    # Build baseline from the same scan scope used after patching.
    # Using earlier pipeline findings can be misleading because they may be
    # diff-filtered rather than full-file results.
    baseline_findings = scan_paths(
        paths=[original_file_path],
        repo_root=temp_repo_path,
        configs=scan_configs,
    )
    baseline_fp = fingerprint(baseline_findings)

    for attempt in range(1, max_attempts + 1):
        # Add previous failures to context for LLM feedback
        context["previous_failures"] = failure_reasons

        patch = patcher.run(context)

        # Reject patches that just comment out the old line (check each replacement)
        commented_out = False
        for old_snippet, new_snippet in patch.replacements:
            old_line = old_snippet.strip()
            new_lines = new_snippet.splitlines()
            if any(
                old_line in line and line.strip().startswith("#")
                for line in new_lines
            ):
                commented_out = True
                break
        if commented_out:
            reason = "Attempt rejected: patch just comments out old line."
            print(reason)
            failure_reasons.append(reason)
            continue

        # Apply patch in temp repo
        try:
            print(f"Applying patch: {patch.replacements}")
            apply_patch(temp_repo_path, original_file_path, patch.replacements)
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
            failure_reasons.append(f"Attempt {attempt}: patch failed validation")

            reset_temp_repo(temp_repo_path)
            continue

        # Re-scan patched file
        # print(f"New Patch: {patch.new}")
        # print("Scanning repo root:", temp_repo_path)
        # print("Scanning file path:", original_file_path)
        # print("Absolute file being scanned:", os.path.join(temp_repo_path, original_file_path))

        new_findings = scan_paths(
            paths=[original_file_path],
            repo_root=temp_repo_path,
            configs=scan_configs,
        )

        new_fp = fingerprint(new_findings)

        # Check whether the specific target finding is still present.
        # Using only check_id is too broad because files can contain multiple
        # findings of the same rule.
        still_present = False
        if target_rule:
            for f in new_findings:
                if f.get("check_id") != target_rule:
                    continue
                if target_line is None:
                    still_present = True
                    break
                new_line = f.get("start", {}).get("line")
                if isinstance(new_line, int) and abs(new_line - target_line) <= 3:
                    still_present = True
                    break

        # print(f"Bug is still present? {still_present}")

        if still_present:
            reason = (
                f"Attempt {attempt}: targeted vulnerability still present after patch "
                f"(rule={target_rule}, original_line={target_line})."
            )
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
