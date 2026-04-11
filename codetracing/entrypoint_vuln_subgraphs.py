
import os
from neo4j import GraphDatabase
from neo4j.exceptions import (
    ServiceUnavailable,
    AuthError,
    Neo4jError,
    SessionExpired,
    TransientError,
)
import json
import time


NEO4J_URI  = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

QUERY = """
MATCH (e:Function {entrypoint:true})
OPTIONAL MATCH p = (e)-[:CALLS*1..50]->(v:Function {vulnerablefunc:true})
WITH e, collect(DISTINCT v.key) AS vulnerableKeys, collect(p) AS paths
UNWIND paths AS p
UNWIND relationships(p) AS r
WITH e, vulnerableKeys,
     collect(DISTINCT [startNode(r).key, endNode(r).key]) AS edges
RETURN
  e.key AS entrypoint,
  vulnerableKeys,
  edges
ORDER BY entrypoint;
"""

def run_query_with_retries(driver, query, params=None, retries=3, base_delay_s=0.5):
    params = params or {}
    last_exc = None

    for attempt in range(1, retries + 1):
        try:
            with driver.session() as session:
                # execute_read will retry some transient errors internally too,
                # but we still wrap to control behavior/logging.
                def _tx(tx):
                    return [r.data() for r in tx.run(query, params)]

                return session.execute_read(_tx)

        except (TransientError, SessionExpired, ServiceUnavailable) as e:
            last_exc = e
            if attempt == retries:
                break
            time.sleep(base_delay_s * (2 ** (attempt - 1)))  # exponential backoff

        except Neo4jError as e:
            # Non-transient Cypher/runtime errors (syntax, type errors, etc.)
            raise RuntimeError(f"Neo4j query failed: {e.code} {e.message}") from e

    raise RuntimeError(f"Neo4j unavailable after {retries} attempts") from last_exc

def main():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
        # Force a connectivity check up front (catches bad URI/auth/db down)
        driver.verify_connectivity()
    except AuthError as e:
        raise SystemExit(f"Auth failed: {e}") from e
    except ServiceUnavailable as e:
        raise SystemExit(f"Cannot connect to Neo4j at {NEO4J_URI}: {e}") from e

    try:
        rows = run_query_with_retries(driver, QUERY, retries=5)

        # Prefer JSONL for large results
        out_path = "entrypoint_vuln_subgraphs.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        print(f"Wrote {len(rows)} rows to {out_path}")

    finally:
        driver.close()

if __name__ == "__main__":
    main()