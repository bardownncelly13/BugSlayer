"""
Mark Neo4j Function nodes as vulnerable from Semgrep results.

Resolves each finding to the innermost enclosing function (tree-sitter) and
sets vulnerablefunc=true using the same fn_key format as ingest_neo4j /
extract_funcs: path::name{parameters}::start_line (path = relpath from repo root).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Tuple

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

try:
    from .get_func_by_name import get_enclosing_function_at_line
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from get_func_by_name import get_enclosing_function_at_line


def _rel_path_for_neo4j(repo_root: str, file_key: str) -> str:
    """
    Same shape as extract_funcs / funcs.jsonl: relpath from repo root, native separators.
    """
    root = os.path.abspath(repo_root)
    if os.path.isabs(file_key):
        full = os.path.normpath(file_key)
    else:
        full = os.path.normpath(os.path.join(root, file_key.replace("/", os.sep)))
    try:
        rel = os.path.relpath(full, root)
    except ValueError:
        rel = file_key
    if rel.startswith(".."):
        rel = file_key
    return rel


def _semgrep_finding_meta(finding: Dict[str, Any]) -> Tuple[str, str, str]:
    extra = finding.get("extra") or {}
    rule = (
        finding.get("check_id")
        or finding.get("rule_id")
        or finding.get("rule")
        or extra.get("check_id")
        or "semgrep"
    )
    message = str(extra.get("message") or finding.get("message") or "")
    severity = str(extra.get("severity") or finding.get("severity") or "")
    return str(rule), message, severity


def _mark_vulnerable_by_fn_key(
    tx,
    fn_key: str,
    vuln_issue: str,
    vuln_message: str,
    vuln_severity: str,
) -> int:
    r = tx.run(
        """
        MATCH (fn:Function {key: $fn_key})
        SET fn.vulnerablefunc = true,
            fn.vuln_issue = $vuln_issue,
            fn.vuln_message = $vuln_message,
            fn.vuln_severity = $vuln_severity
        RETURN count(fn) AS c
        """,
        fn_key=fn_key,
        vuln_issue=vuln_issue or None,
        vuln_message=vuln_message or None,
        vuln_severity=vuln_severity or None,
    )
    rec = r.single()
    return int(rec["c"]) if rec else 0


def apply_semgrep_findings_to_neo4j(
    findings_by_file: Dict[str, Any],
    repo_path: str,
) -> Dict[str, int]:
    """
    For each Semgrep finding, set vulnerablefunc on the matching Function node.

    Returns counts: updated, skipped_no_line, skipped_no_func, skipped_no_node, errors
    """
    counts = {
        "updated": 0,
        "skipped_no_line": 0,
        "skipped_no_func": 0,
        "skipped_no_node": 0,
        "errors": 0,
    }
    if not findings_by_file:
        return counts

    if os.environ.get("SKIP_NEO4J_SEMGREP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        print("[Neo4j] SKIP_NEO4J_SEMGREP set; not marking Semgrep findings on graph.")
        return counts

    repo_root = os.path.abspath(repo_path)
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, Neo4jError) as e:
        print(f"[Neo4j] Unavailable; skipping Semgrep vulnerability marks ({e}).")
        driver.close()
        return counts

    try:
        with driver.session() as session:
            for file_key, file_findings in findings_by_file.items():
                rel = _rel_path_for_neo4j(repo_root, file_key)
                abs_file = os.path.normpath(
                    os.path.join(repo_root, rel.replace("/", os.sep))
                )
                if not os.path.isfile(abs_file):
                    for _ in file_findings:
                        counts["skipped_no_func"] += 1
                    continue

                for finding in file_findings:
                    line = (finding.get("start") or {}).get("line")
                    if not line:
                        counts["skipped_no_line"] += 1
                        continue

                    func = get_enclosing_function_at_line(abs_file, int(line))
                    if not func:
                        counts["skipped_no_func"] += 1
                        continue

                    name = func.get("name") or ""
                    parameters = func.get("parameters") or ""
                    start_line = func.get("start_line")
                    if start_line is None:
                        counts["skipped_no_func"] += 1
                        continue

                    fn_key = f"{rel}::{name}{parameters}::{start_line}"
                    rule, message, severity = _semgrep_finding_meta(finding)

                    def _tx(tx):
                        return _mark_vulnerable_by_fn_key(
                            tx, fn_key, rule, message, severity
                        )

                    try:
                        n = session.execute_write(_tx)
                    except Neo4jError:
                        counts["errors"] += 1
                        continue

                    if n:
                        counts["updated"] += 1
                    else:
                        counts["skipped_no_node"] += 1
    finally:
        driver.close()

    print(
        "[Neo4j] Semgrep marks: "
        f"updated={counts['updated']}, "
        f"no_line={counts['skipped_no_line']}, "
        f"no_enclosing_func={counts['skipped_no_func']}, "
        f"no_graph_node={counts['skipped_no_node']}, "
        f"errors={counts['errors']}"
    )
    return counts


def main():
    print("Use apply_semgrep_findings_to_neo4j() from main or a driver script.")


if __name__ == "__main__":
    main()
