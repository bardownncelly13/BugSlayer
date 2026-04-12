"""Load taint_findings.jsonl and build context for triage/patch (Semgrep-shaped finding dict)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

try:
    from .get_func_by_name import get_enclosing_function_at_line
except ImportError:
    import sys

    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from get_func_by_name import get_enclosing_function_at_line


def parse_vuln_fn_key(fn_key: str) -> Tuple[str, int]:
    """
    Parse ingest/Neo4j function key: path::name(parameters)::start_line
    Returns (relative_path, function_start_line_1based).
    """
    if not fn_key or "::" not in fn_key:
        raise ValueError(f"invalid fn_key: {fn_key!r}")
    base, line_s = fn_key.rsplit("::", 1)
    try:
        start_line = int(line_s)
    except ValueError as e:
        raise ValueError(f"invalid fn_key (line): {fn_key!r}") from e
    if "::" not in base:
        return base, start_line
    path, _sig = base.split("::", 1)
    return path, start_line


def load_taint_findings_jsonl(path: str) -> List[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_taint_sink_code_context(repo_root: str, vuln_fn_key: str) -> str:
    """Tree-sitter body for the sink function identified by vuln_fn_key."""
    try:
        rel_path, start_line = parse_vuln_fn_key(vuln_fn_key)
    except ValueError:
        return ""
    abs_path = os.path.normpath(
        os.path.join(os.path.abspath(repo_root), rel_path.replace("/", os.sep))
    )
    if not os.path.isfile(abs_path):
        return ""
    fn = get_enclosing_function_at_line(abs_path, start_line)
    if not fn:
        return ""
    return (
        "## Taint sink (tree-sitter function scope)\n"
        f"Name: `{fn['name']}`  lines {fn['start_line']}-{fn['end_line']}  "
        f"key: `{fn.get('fn_key', '')}`\n\n"
        f"{fn['body']}"
    )


def synthetic_finding_from_taint_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Minimal Semgrep-shaped dict for PatchStrategy, patch_validation, and git_ops.
    check_id avoids ':' so git branch names stay valid.
    """
    contract = row.get("contract") or {}
    sink_raw = str(row.get("sink_type") or "sink")
    sink_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", sink_raw).strip("-") or "sink"

    msg_parts = [
        f"Taint finding: reachable from entrypoint to sink ({sink_raw}).",
        f"Verdict: {row.get('verdict', '')}",
    ]
    if row.get("tainted_param_names"):
        msg_parts.append(f"Tainted parameters: {row['tainted_param_names']}")
    if contract.get("notes"):
        msg_parts.append(str(contract["notes"]))
    if contract.get("dangerous_operations"):
        msg_parts.append("Dangerous ops: " + "; ".join(map(str, contract["dangerous_operations"][:5])))
    if contract.get("required_mitigations"):
        msg_parts.append(
            "Mitigations: " + "; ".join(map(str, contract["required_mitigations"][:5]))
        )
    message = "\n".join(msg_parts)

    vuln_key = row.get("vuln") or ""
    try:
        _path, start_line = parse_vuln_fn_key(vuln_key)
    except ValueError:
        start_line = 1

    return {
        "check_id": f"taint-{sink_slug}",
        "extra": {
            "message": message,
            "severity": str(row.get("verdict", "unknown")),
        },
        "start": {"line": start_line},
        "_taint": True,
        "_taint_row": row,
    }


def taint_contract_excerpt(row: Dict[str, Any]) -> str:
    c = row.get("contract") or {}
    if not c:
        return ""
    keys = (
        "sink_type",
        "dangerous_operations",
        "tainted_inputs",
        "required_mitigations",
        "notes",
        "confidence",
    )
    slim = {k: c[k] for k in keys if k in c}
    return "\n\n## Taint contract\n" + json.dumps(slim, indent=2, ensure_ascii=False)
