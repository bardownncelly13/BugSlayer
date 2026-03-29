#!/usr/bin/env bash
set -euo pipefail

# --------- paths ----------
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
GRAPHDB_DIR="${REPO_ROOT}/codetracing/graphdb"

FUNCS_JSONL="${REPO_ROOT}/funcs.jsonl"
CALLS_JSONL="${REPO_ROOT}/calls.jsonl"

# --------- neo4j creds/uri (must match docker-compose.yml) ----------
NEO4J_SERVICE="${NEO4J_SERVICE:-neo4j}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASS="${NEO4J_PASS:-password}"

# For Python driver
export NEO4J_URI="${NEO4J_URI:-bolt://127.0.0.1:7687}"
export NEO4J_USER
export NEO4J_PASS

echo "[*] Repo root:    $REPO_ROOT"
echo "[*] GraphDB dir:  $GRAPHDB_DIR"
echo "[*] Neo4j URI:    $NEO4J_URI"

cd "$GRAPHDB_DIR"

# --------- 0) wipe + start neo4j via compose ----------
echo "[*] Wiping Neo4j (docker compose down -v)..."
docker compose down -v --remove-orphans || true

echo "[*] Starting Neo4j (docker compose up -d)..."
docker compose up -d

# --------- 1) wait until cypher-shell works ----------
echo "[*] Waiting for Neo4j to accept cypher-shell..."
for i in {1..180}; do
  if docker compose exec -T "$NEO4J_SERVICE" \
      cypher-shell -a bolt://127.0.0.1:7687 -u "$NEO4J_USER" -p "$NEO4J_PASS" "RETURN 1;" \
      >/dev/null 2>&1; then
    echo "[+] Neo4j ready."
    break
  fi

  if [[ "$i" -eq 180 ]]; then
    echo "[!] Neo4j not ready in time. Recent logs:"
    docker compose logs --tail=200 "$NEO4J_SERVICE"
    exit 1
  fi
  sleep 1
done

# --------- 2) regenerate jsonl from repo root ----------
cd "$REPO_ROOT"

echo "[*] Removing old JSONL outputs..."
rm -f "$FUNCS_JSONL" "$CALLS_JSONL"

echo "[*] Extracting functions -> $FUNCS_JSONL"
python3 codetracing/extract_funcs.py --repo "$REPO_ROOT" --out "$FUNCS_JSONL"

echo "[*] Extracting calls -> $CALLS_JSONL"
python3 codetracing/extract_calls.py --repo "$REPO_ROOT" --out "$CALLS_JSONL"

# --------- 4) ingest into neo4j ----------
echo "[*] Ingesting functions into Neo4j..."
python3 codetracing/ingest_neo4j.py "$FUNCS_JSONL"

echo "[*] Ingesting calls into Neo4j..."
python3 codetracing/ingest_calls_neo4j.py "$CALLS_JSONL"

echo "[+] Done."
echo "Neo4j Browser: http://localhost:7474  (user: $NEO4J_USER pass: $NEO4J_PASS)"
echo "Outputs:"
echo "  $FUNCS_JSONL"
echo "  $CALLS_JSONL"