"""Assemble code context for triage/patch LLM prompts."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from codetracing.finding_symbols import infer_function_name_from_semgrep_finding
from codetracing.get_func_by_name import (
    get_enclosing_function_at_line,
    get_function_by_name,
)


def _include_git_diff_hunk() -> bool:
    """Off by default: tree-sitter scope is enough; avoids duplicating diff + file body."""
    return os.environ.get("LLM_INCLUDE_DIFF_HUNK", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def build_code_context_for_finding(
    repo_root: str,
    rel_file: str,
    finding: Dict[str, Any],
    file_diff: Optional[str],
    line: Optional[int],
) -> str:
    """
    Prefer tree-sitter function body (by Semgrep-inferred name + line disambiguation
    for overloads, else enclosing function at line).

    Git diff hunks are omitted by default (often redundant with full function text).
    Set LLM_INCLUDE_DIFF_HUNK=1 to append them again.
    """
    parts = []
    abs_path = os.path.join(repo_root, rel_file)
    if not os.path.isfile(abs_path):
        abs_path = str(Path(repo_root) / rel_file)
    if not os.path.isfile(abs_path):
        return _fallback_line_only(repo_root, rel_file, line, file_diff)

    func: Optional[Dict[str, Any]] = None
    name = infer_function_name_from_semgrep_finding(finding)
    if name and line:
        func = get_function_by_name(abs_path, name, target_line=line)
    elif name:
        func = get_function_by_name(abs_path, name, target_line=None)

    if func is None and line:
        func = get_enclosing_function_at_line(abs_path, line)

    if func:
        parts.append(
            "## Tree-sitter function scope\n"
            f"Name: `{func['name']}`  lines {func['start_line']}-{func['end_line']}  "
            f"key: `{func.get('fn_key', '')}`\n\n"
            f"{func['body']}"
        )

    if _include_git_diff_hunk() and file_diff and line:
        from delta import extract_relevant_diff

        hunk = extract_relevant_diff(file_diff, line)
        if hunk.strip():
            parts.append("## Git diff hunk (same file / line)\n" + hunk)

    if parts:
        return "\n\n".join(parts)

    return _fallback_line_only(repo_root, rel_file, line, file_diff)


def _fallback_line_only(
    repo_root: str,
    rel_file: str,
    line: Optional[int],
    file_diff: Optional[str],
) -> str:
    if file_diff and line:
        from delta import extract_relevant_diff

        h = extract_relevant_diff(file_diff, line)
        if h.strip():
            return h
    if line:
        p = Path(repo_root) / rel_file
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                if 0 < line <= len(lines):
                    return lines[line - 1]
            except OSError:
                pass
    return ""
