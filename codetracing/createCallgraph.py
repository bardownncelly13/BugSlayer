#!/usr/bin/env python3
import os
import sys
import subprocess
import time

# BugSlayer install root (contains codetracing/, graphdb/, main.py)
BUGSLAYER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BUGSLAYER_ROOT)

from extract_funcs import run_extract_funcs
from extract_calls import run_extract_calls
from ingest_neo4j import run_ingest_funcs
from ingest_calls_neo4j import run_ingest_calls

GRAPHDB_DIR = os.path.join(BUGSLAYER_ROOT, "codetracing", "graphdb")


def _scan_jsonl_paths(scan_root: str) -> tuple[str, str]:
    root = os.path.abspath(scan_root)
    return (
        os.path.join(root, "funcs.jsonl"),
        os.path.join(root, "calls.jsonl"),
    )

# Neo4j config
NEO4J_SERVICE = os.environ.get("NEO4J_SERVICE", "neo4j")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

def wipe_and_start_neo4j():
    print("[*] Wiping Neo4j (docker compose down -v)...")
    subprocess.run(["docker", "compose", "down", "-v", "--remove-orphans"], cwd=GRAPHDB_DIR, check=True)

    print("[*] Starting Neo4j (docker compose up -d)...")
    subprocess.run(["docker", "compose", "up", "-d"], cwd=GRAPHDB_DIR, check=True)

    print("[*] Waiting for Neo4j to accept cypher-shell...")
    for i in range(1, 181):
        result = subprocess.run([
            "docker", "compose", "exec", "-T", NEO4J_SERVICE,
            "cypher-shell", "-a", "bolt://127.0.0.1:7687", "-u", NEO4J_USER, "-p", NEO4J_PASS, "RETURN 1;"
        ], cwd=GRAPHDB_DIR, capture_output=True, text=True)
        if result.returncode == 0:
            print("[+] Neo4j ready.")
            break
        if i == 180:
            raise RuntimeError("Neo4j not ready in time.")
        time.sleep(1)

def main(repo_path: str | None = None):
    """Build graph from ``repo_path`` (normalized absolute path). Default: BugSlayer root."""
    scan_root = os.path.abspath(repo_path) if repo_path else BUGSLAYER_ROOT
    repo_name = os.path.basename(scan_root.rstrip(os.sep)) or "myrepo"
    funcs_jsonl, calls_jsonl = _scan_jsonl_paths(scan_root)

    print(f"[*] Repo root (scan): {scan_root}")
    print(f"[*] GraphDB dir: {GRAPHDB_DIR}")

    # 0) Wipe and start Neo4j
    wipe_and_start_neo4j()

    # 1) Regenerate JSONL
    print("[*] Removing old JSONL outputs...")
    for f in (funcs_jsonl, calls_jsonl):
        if os.path.exists(f):
            os.remove(f)

    print("[*] Extracting functions...")
    run_extract_funcs(scan_root, funcs_jsonl)

    print("[*] Extracting calls...")
    run_extract_calls(scan_root, calls_jsonl)

    # 2) Ingest into Neo4j
    print("[*] Ingesting functions into Neo4j...")
    run_ingest_funcs(funcs_jsonl, repo_root=scan_root, repo_name=repo_name)

    print("[*] Ingesting calls into Neo4j...")
    run_ingest_calls(calls_jsonl)

    # 3) Resolve calls
    print("[*] Resolving calls with LLM...")
    subprocess.run([sys.executable, "resolve_calls_llm.py"], cwd=os.path.dirname(__file__), check=True)

    print("[+] Done.")
    print("Neo4j Browser: http://localhost:7474 (user: neo4j pass: password)")

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Extract call graph and load Neo4j")
    ap.add_argument(
        "--repo",
        default=None,
        help="Repository root to scan (default: BugSlayer install directory)",
    )
    ns = ap.parse_args()
    main(repo_path=ns.repo)