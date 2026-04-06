"""Best-effort symbol extraction from Semgrep finding JSON."""

import re
from typing import Any, Dict, Optional


def infer_function_name_from_semgrep_finding(finding: Dict[str, Any]) -> Optional[str]:
    """
    Try to recover a function name for tree-sitter lookup.
    Semgrep rules vary; this is heuristic.
    """
    extra = finding.get("extra") or {}

    for mv in (finding.get("metavars"), extra.get("metavars")):
        if not isinstance(mv, dict):
            continue
        for _key, meta in mv.items():
            if not isinstance(meta, dict):
                continue
            text = (
                meta.get("abstract_content")
                or meta.get("svalue")
                or meta.get("text")
            )
            if not text or not isinstance(text, str):
                continue
            text = text.strip()
            if re.match(r"^[A-Za-z_][\w]*$", text):
                return text

    lines = extra.get("lines")
    if isinstance(lines, str):
        m = re.search(r"\bdef\s+(\w+)\s*\(", lines)
        if m:
            return m.group(1)
        m = re.search(r"\bfn\s+(\w+)\s*\(", lines)
        if m:
            return m.group(1)
        m = re.search(
            r"\b(?:static\s+)?(?:inline\s+)?(?:[\w:*&<>,\s]+)\s+(\w+)\s*\([^)]*\)\s*\{",
            lines,
        )
        if m:
            return m.group(1)

    return None
