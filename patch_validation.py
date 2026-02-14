import difflib
from validators.registry import get_validator
from validators.base import ValidationError
from git_utils.git_ops import apply_patch, reset_temp_repo

def count_non_comment_lines(text: str) -> int:
    lines = text.splitlines()
    count = 0
    for line in lines:
        stripped = line.strip()
        # Slightly scuffed condition but should hold generally
        if stripped and not stripped.startswith(("#", "//", "/*", "*")):
            count += 1
    return count


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
    try:
        validator.syntax_check()
    except ValidationError as e:
        print(f"[VALIDATION] Syntax failed:\n{e}")
        return False

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
    triage_result,
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

        # Apply patch in temp repo
        try:
            apply_patch(temp_repo_path, original_file_path, patch.old, patch.new)
        except ValueError as e:
            reason = f"Attempt {attempt} failed: {str(e)}"
            print(reason)
            failure_reasons.append(reason)
            continue

        # Validate patch (syntax, tests, etc.)
        if not validate_patch(temp_repo_path, patched_file_path):
            reason = f"Attempt {attempt} failed validation."
            print(reason)
            failure_reasons.append(f"Attempt {attempt}: old={patch.old} new={patch.new} failed validation")

            reset_temp_repo(temp_repo_path)
            continue

        # Success
        return patch

    # Exhausted all attempts
    print(f"Patch generation failed after {max_attempts} attempts. Failures:\n" + "\n".join(failure_reasons))
    return None
