import json
import os
import sys
import re
from neo4j import GraphDatabase

NEO4J_URI  = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

INPUT_JSONL = sys.argv[1] if len(sys.argv) > 1 else "calls.jsonl"

def ensure_schema(tx):
    tx.run("CREATE CONSTRAINT callsite_id IF NOT EXISTS FOR (cs:CallSite) REQUIRE cs.id IS UNIQUE")
    tx.run("CREATE INDEX callsite_resolved IF NOT EXISTS FOR (cs:CallSite) ON (cs.resolved)")

    tx.run("CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)")
    tx.run("CREATE INDEX function_path IF NOT EXISTS FOR (fn:Function) ON (fn.path)")
    tx.run("CREATE INDEX function_key IF NOT EXISTS FOR (fn:Function) ON (fn.key)")

def parse_python_imports(snippet: str):
    """
    Very lightweight import parser from the snippet. We use snippet because it is local+cheap.
    Returns:
      module_aliases: dict alias->module  for `import pkg.mod as m`
      imported_names: dict name->module   for `from pkg.mod import foo as bar`
    """
    module_aliases = {}
    imported_names = {}

    for line in (snippet or "").splitlines():
        # strip "N: " prefix from snippet format
        m = re.match(r"^\s*\d+:\s*(.*)$", line)
        if m:
            line = m.group(1)

        line = line.strip()
        if line.startswith("#"):
            continue

        m = re.match(r"^import\s+([a-zA-Z0-9_\.]+)(?:\s+as\s+([a-zA-Z0-9_]+))?\s*$", line)
        if m:
            mod = m.group(1)
            alias = m.group(2) or mod.split(".")[0]
            module_aliases[alias] = mod
            continue

        m = re.match(r"^from\s+([a-zA-Z0-9_\.]+)\s+import\s+(.+)$", line)
        if m:
            mod = m.group(1)
            rest = m.group(2).strip()
            # very basic split; ignores parenthesized imports etc.
            for part in rest.split(","):
                part = part.strip()
                m2 = re.match(r"^([a-zA-Z0-9_]+)(?:\s+as\s+([a-zA-Z0-9_]+))?\s*$", part)
                if m2:
                    name = m2.group(1)
                    alias = m2.group(2) or name
                    imported_names[alias] = mod
            continue

    return module_aliases, imported_names

def python_module_to_paths(module: str):
    """
    Repo-only module mapping:
      pkg.mod -> pkg/mod.py or pkg/mod/__init__.py
    """
    if not module:
        return []
    parts = module.split(".")
    py1 = "/".join(parts) + ".py"
    py2 = "/".join(parts) + "/__init__.py"
    return [py1, py2]

def create_callsite(tx, rec):
    tx.run(
        """
        MATCH (caller:Function {key:$caller_key})
        MERGE (cs:CallSite {id:$id})
        SET cs.caller_key = $caller_key,
            cs.file = $file,
            cs.line = $line,
            cs.callee_text = $callee_text,
            cs.callee_name = $callee_name,
            cs.snippet = $snippet,
            cs.language = $language,
            cs.resolved = coalesce(cs.resolved, false)
        MERGE (caller)-[:HAS_CALLSITE]->(cs)
        """,
        {
            "id": rec["callsite_id"],
            "caller_key": rec["caller_key"],
            "file": rec["file"],
            "line": rec["call_line"],
            "callee_text": rec.get("callee_text", ""),
            "callee_name": rec.get("callee_name", ""),
            "snippet": rec.get("snippet", ""),
            "language": rec.get("language", ""),
        },
    )

def resolve_same_file_unique(tx, rec) -> bool:
    """
    If exactly one function in same file matches callee_name, resolve.
    """
    callee_name = rec.get("callee_name") or ""
    if not callee_name:
        return False

    rows = tx.run(
        """
        MATCH (callee:Function {path:$file, name:$name})
        RETURN callee.key AS key
        """,
        file=rec["file"],
        name=callee_name,
    ).data()

    if len(rows) != 1:
        return False

    callee_key = rows[0]["key"]
    tx.run(
        """
        MATCH (cs:CallSite {id:$id})
        MATCH (caller:Function {key: cs.caller_key})
        MATCH (callee:Function {key:$callee_key})
        SET cs.resolved = true,
            cs.resolved_by = "same_file_unique",
            cs.confidence = 0.95
        MERGE (cs)-[:RESOLVES_TO]->(callee)
        MERGE (caller)-[r:CALLS]->(callee)
        ON CREATE SET r.count = 1, r.source = "same_file_unique"
        ON MATCH  SET r.count = coalesce(r.count,0) + 1
        """,
        id=rec["callsite_id"],
        callee_key=callee_key,
    )
    return True

def resolve_python_import_unique(tx, rec) -> bool:
    """
    Python-only:
    - if callee_text looks like "alias.func", map alias via imports to a module, then to a repo path, then resolve func in that file
    - if callee_name was imported directly via "from mod import func", map to module, then to file, then resolve func
    Only resolve when unique.
    """
    if rec.get("language") != "python":
        return False

    callee_text = (rec.get("callee_text") or "").strip()
    callee_name = (rec.get("callee_name") or "").strip()
    if not callee_name:
        return False

    module_aliases, imported_names = parse_python_imports(rec.get("snippet") or "")

    # Case A: direct imported function (from mod import func as alias) then called as alias()
    if callee_name in imported_names:
        mod = imported_names[callee_name]
        candidate_paths = python_module_to_paths(mod)
        rows = tx.run(
            """
            MATCH (callee:Function)
            WHERE callee.path IN $paths AND callee.name = $name
            RETURN callee.key AS key
            """,
            paths=candidate_paths,
            name=callee_name if callee_name else "",
        ).data()

        if len(rows) == 1:
            callee_key = rows[0]["key"]
            tx.run(
                """
                MATCH (cs:CallSite {id:$id})
                MATCH (caller:Function {key: cs.caller_key})
                MATCH (callee:Function {key:$callee_key})
                SET cs.resolved = true,
                    cs.resolved_by = "py_import_unique",
                    cs.confidence = 0.9,
                    cs.module = $mod
                MERGE (cs)-[:RESOLVES_TO]->(callee)
                MERGE (caller)-[r:CALLS]->(callee)
                ON CREATE SET r.count = 1, r.source = "py_import_unique"
                ON MATCH  SET r.count = coalesce(r.count,0) + 1
                """,
                id=rec["callsite_id"],
                callee_key=callee_key,
                mod=mod,
            )
            return True

        return False

    # Case B: module qualified call: alias.func(...)
    if "." in callee_text:
        left, right = callee_text.split(".", 1)
        left = left.strip()
        right_name = right.split(".", 1)[-1].strip()  # last segment
        right_name = right_name.split("(", 1)[0].strip()

        if left in module_aliases:
            mod = module_aliases[left]
            candidate_paths = python_module_to_paths(mod)
            rows = tx.run(
                """
                MATCH (callee:Function)
                WHERE callee.path IN $paths AND callee.name = $name
                RETURN callee.key AS key
                """,
                paths=candidate_paths,
                name=right_name,
            ).data()

            if len(rows) == 1:
                callee_key = rows[0]["key"]
                tx.run(
                    """
                    MATCH (cs:CallSite {id:$id})
                    MATCH (caller:Function {key: cs.caller_key})
                    MATCH (callee:Function {key:$callee_key})
                    SET cs.resolved = true,
                        cs.resolved_by = "py_module_unique",
                        cs.confidence = 0.9,
                        cs.module = $mod
                    MERGE (cs)-[:RESOLVES_TO]->(callee)
                    MERGE (caller)-[r:CALLS]->(callee)
                    ON CREATE SET r.count = 1, r.source = "py_module_unique"
                    ON MATCH  SET r.count = coalesce(r.count,0) + 1
                    """,
                    id=rec["callsite_id"],
                    callee_key=callee_key,
                    mod=mod,
                )
                return True

    return False

def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    total = 0

    with driver.session() as session:
        session.execute_write(ensure_schema)

        with open(INPUT_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)

                # 1) Always create CallSite
                session.execute_write(create_callsite, rec)

                # 2) Deterministic resolutions (stop on first success)
                resolved = session.execute_write(resolve_same_file_unique, rec)
                if not resolved:
                    resolved = session.execute_write(resolve_python_import_unique, rec)

                total += 1

    driver.close()
    print("ingested callsites:", total)

if __name__ == "__main__":
    main()