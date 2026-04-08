import json
import os
import sys
from neo4j import GraphDatabase
from get_func_by_name import get_function_by_name

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

# Default to parent directory gemini_results.json
DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gemini_results.json")
INPUT_JSON = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON


def normalize_repo_path(path: str) -> tuple[str, str]:
    """Return (relative_path_from_repo_root, absolute_path)."""
    if not path:
        return path, path
    abs_path = path if os.path.isabs(path) else os.path.abspath(os.path.join(REPO_ROOT, path))
    rel_path = os.path.relpath(abs_path, REPO_ROOT)
    return rel_path, abs_path


def update_function_flags(
    tx,
    path,
    function_name,
    function_line,
    parameters="",
    is_vulnerable=None,
    is_entry_point=None,
):
    """
    Update a Function node with vulnerablefunc/entrypoint flags.

    - function_name must be the *base name* (e.g., "vulnerable_copy"), NOT a full signature.
    - parameters must match what was used to create the Function key during ingest.
    - use None for a flag you don't want to overwrite.
    """
    fn_key = f"{path}::{function_name}{parameters}::{function_line}"

    tx.run(
        """
        MATCH (fn:Function {key: $fn_key})
        SET fn.vulnerablefunc = coalesce($is_vulnerable, fn.vulnerablefunc),
            fn.entrypoint     = coalesce($is_entry_point, fn.entrypoint)
        """,
        {
            "fn_key": fn_key,
            "is_vulnerable": is_vulnerable,
            "is_entry_point": is_entry_point,
        },
    )


def process_gemini_results(json_file: str) -> int:
    """Parse gemini_results.json and update neo4j with flags."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    updates = 0

    with open(json_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    with driver.session() as session:
        for file_entry in data:
            raw_path = file_entry.get("path")
            path, abs_path = normalize_repo_path(raw_path)
            print(
                f"Processing file entry raw_path={raw_path!r} "
                f"normalized_path={path!r} abs_path={abs_path!r}"
            )

            # -------------------------
            # Vulnerabilities
            # -------------------------
            for vuln in file_entry.get("vulnerabilities", []):
                function_name = vuln.get("function")
                is_entry_point = bool(vuln.get("is_entry_point", False))

                if not function_name:
                    continue

                base_function_name = function_name.split("(")[0].strip()

                func_info = get_function_by_name(abs_path, base_function_name)
                if not func_info:
                    print(
                        f"  Warning: Could not find function {function_name!r} "
                        f"(base={base_function_name!r}) in {raw_path!r} -> {abs_path!r}"
                    )
                    continue

                function_line = func_info["start_line"]
                parameters = func_info.get("parameters", "") or ""

                print(
                    f"  Found function lookup: base={base_function_name!r} path={abs_path!r} "
                    f"start_line={function_line} parameters={parameters!r}"
                )

                session.execute_write(
                    update_function_flags,
                    path,
                    base_function_name,  # IMPORTANT: base name only
                    function_line,
                    parameters,
                    is_vulnerable=True,
                    is_entry_point=is_entry_point if is_entry_point else None,
                )
                updates += 1
                print(
                    f"  Updated vulnerability: {path}::{base_function_name}{parameters}::{function_line} "
                    f"(vulnerable=True, entrypoint={is_entry_point})"
                )

            # -------------------------
            # Entry points
            # -------------------------
            for ep in file_entry.get("entry_points", []):
                function_name = ep.get("function")
                is_entry_point = bool(ep.get("is_entry_point", False))

                if not function_name or not is_entry_point:
                    continue

                base_function_name = function_name.split("(")[0].strip()

                func_info = get_function_by_name(abs_path, base_function_name)
                if not func_info:
                    print(
                        f"  Warning: Could not find function {function_name!r} "
                        f"(base={base_function_name!r}) in {raw_path!r} -> {abs_path!r}"
                    )
                    continue

                function_line = func_info["start_line"]
                parameters = func_info.get("parameters", "") or ""

                print(
                    f"  Found function lookup: base={base_function_name!r} path={abs_path!r} "
                    f"start_line={function_line} parameters={parameters!r}"
                )

                session.execute_write(
                    update_function_flags,
                    path,
                    base_function_name,  # IMPORTANT: base name only
                    function_line,
                    parameters,
                    is_vulnerable=None,  # don't overwrite vulnerability flag
                    is_entry_point=True,
                )
                updates += 1
                print(
                    f"  Updated entry point: {path}::{base_function_name}{parameters}::{function_line} "
                    f"(entrypoint=True)"
                )

    driver.close()
    return updates


def main():
    if not os.path.exists(INPUT_JSON):
        print(f"Error: {INPUT_JSON} not found")
        sys.exit(1)

    updates = process_gemini_results(INPUT_JSON)
    print(f"\nTotal updates: {updates}")


if __name__ == "__main__":
    main()