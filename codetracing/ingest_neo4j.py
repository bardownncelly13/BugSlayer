import json
import os
import sys
from neo4j import GraphDatabase

NEO4J_URI  = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

REPO_NAME = os.environ.get("REPO_NAME", "myrepo")
REPO_ROOT = os.environ.get("REPO_ROOT", os.path.abspath("."))

INPUT_JSONL = sys.argv[1] if len(sys.argv) > 1 else "funcs.jsonl"


def ensure_schema(tx):
    tx.run("CREATE CONSTRAINT repo_name IF NOT EXISTS FOR (r:Repo) REQUIRE r.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE")
    tx.run("CREATE CONSTRAINT function_key IF NOT EXISTS FOR (fn:Function) REQUIRE fn.key IS UNIQUE")
    tx.run("CREATE INDEX function_name IF NOT EXISTS FOR (fn:Function) ON (fn.name)")
    tx.run("CREATE INDEX file_path_idx IF NOT EXISTS FOR (f:File) ON (f.path)")


def upsert_record(tx, repo_name, repo_root, rec):
    path = rec.get("path")
    name = rec.get("function")
    start_line = rec.get("start_line")

    fn_key = f"{path}::{name}::{start_line}"

    params = {
        "repo_name": repo_name,
        "repo_root": repo_root,
        "path": path,
        "fn_key": fn_key,
        "name": name,
        "language": rec.get("language"),
        "parameters": rec.get("parameters") or "",
        "start_line": rec.get("start_line"),
        "end_line": rec.get("end_line"),
        "body": rec.get("body") or "",
        "container": rec.get("class"),
    }

    tx.run(
        """
        MERGE (r:Repo {name: $repo_name})
        ON CREATE SET r.root = $repo_root

        MERGE (f:File {path: $path})
        MERGE (r)-[:HAS_FILE]->(f)

        MERGE (fn:Function {key: $fn_key})
        SET fn.name = $name,
            fn.language = $language,
            fn.parameters = $parameters,
            fn.start_line = $start_line,
            fn.end_line = $end_line,
            fn.body = $body,
            fn.path = $path,
            fn.container = $container

        MERGE (f)-[:DEFINES]->(fn)
        """,
        params,
    )


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    total = 0
    with driver.session() as session:
        session.execute_write(ensure_schema)

        with open(INPUT_JSONL, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)

                # if you ever accidentally pipe stats into the file, skip them
                if isinstance(rec, dict) and "_stats" in rec:
                    continue

                session.execute_write(upsert_record, REPO_NAME, REPO_ROOT, rec)
                total += 1

    driver.close()
    print(f"Ingested {total} functions.")


if __name__ == "__main__":
    main()