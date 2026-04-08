import os
import sys
import json
import time
from typing import List, Dict

from neo4j import GraphDatabase
from dotenv import load_dotenv

# --------------------------
# Always-on logging
# --------------------------
def log(msg: str):
    print(msg, file=sys.stderr, flush=True)

# --------------------------
# Helpers
# --------------------------
def extract_json_object(text: str) -> str:
    t = (text or "").strip()

    # Remove ```json ... ``` fences if present
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 3:
            t = parts[1].strip()
        else:
            t = t.strip("`").strip()
        if t.startswith("json"):
            t = t[4:].strip()

    # Best-effort: take substring from first { to last }
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j != -1 and j > i:
        return t[i : j + 1]
    return t

def head_snippet(body: str, max_lines: int = 25, max_chars: int = 1200) -> str:
    if not body:
        return ""
    lines = body.splitlines()[:max_lines]
    s = "\n".join(lines)
    return s[:max_chars]

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

# --------------------------
# Repo root import + dotenv
# --------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(REPO_ROOT, ".env"))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from llm.gemini_client import gemini_text  # noqa: E402

# --------------------------
# Config
# --------------------------
NEO4J_URI  = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

FETCH_LIMIT = int(os.environ.get("LLM_MATCH_FETCH", "5000"))
BATCH_SIZE = int(os.environ.get("LLM_MATCH_BATCHSIZE", "20"))
MAX_CANDIDATES = int(os.environ.get("LLM_MATCH_MAX_CANDIDATES", "20"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
SLEEP_BETWEEN = float(os.environ.get("GEMINI_SLEEP_BETWEEN", "0"))

BUILTINS = {
    "print","len","range","tuple","list","dict","set","str","int","float","bool",
    "Exception","ValueError","TypeError","RuntimeError","KeyError","IndexError","AttributeError",
}

SYSTEM = """Return ONLY a JSON object. No markdown. No backticks. No prose.
Keys must be callsite_id strings. Values must be either:
- an exact candidate key provided for that callsite, or
- "UNRESOLVED"
Do not include any other keys besides the provided callsite_ids.
If the call appears to be a builtin/stdlib/external library call, output "UNRESOLVED".
"""

# --------------------------
# Neo4j queries
# --------------------------
def fetch_unresolved_callsites(tx, limit: int) -> List[Dict]:
    res = tx.run(
        """
        MATCH (cs:CallSite {resolved:false})
        RETURN cs.id AS id,
               cs.caller_key AS caller_key,
               cs.file AS file,
               cs.line AS line,
               cs.callee_text AS callee_text,
               cs.callee_name AS callee_name,
               cs.snippet AS snippet,
               cs.language AS language
        ORDER BY cs.file, cs.line
        LIMIT $limit
        """,
        limit=limit,
    )
    return [r.data() for r in res]

def fetch_caller_fn(tx, caller_key: str):
    rec = tx.run(
        """
        MATCH (fn:Function {key:$key})
        RETURN fn.key AS key, fn.name AS name, fn.path AS path, fn.start_line AS start_line
        """,
        key=caller_key,
    ).single()
    return rec.data() if rec else None

def fetch_candidates_by_name(tx, callee_name: str) -> List[Dict]:
    return tx.run(
        """
        MATCH (fn:Function {name:$name})
        RETURN fn.key AS key, fn.name AS name, fn.path AS path, fn.container AS container,
               fn.start_line AS start_line, fn.body AS body
        ORDER BY fn.path, fn.start_line
        LIMIT $limit
        """,
        name=callee_name,
        limit=MAX_CANDIDATES,
    ).data()

def mark_unresolved(tx, callsite_id: str, reason: str):
    tx.run(
        """
        MATCH (cs:CallSite {id:$id})
        SET cs.last_attempt = timestamp(),
            cs.last_result = "UNRESOLVED",
            cs.reason = $reason
        """,
        id=callsite_id,
        reason=reason,
    )

def apply_resolution(tx, callsite_id: str, callee_key: str, confidence: float, source: str):
    tx.run(
        """
        MATCH (cs:CallSite {id:$id})
        MATCH (caller:Function {key: cs.caller_key})
        MATCH (callee:Function {key:$callee_key})
        SET cs.resolved = true,
            cs.resolved_by = $source,
            cs.confidence = $confidence,
            cs.last_attempt = timestamp(),
            cs.last_result = "RESOLVED"
        MERGE (cs)-[:RESOLVES_TO]->(callee)
        MERGE (caller)-[r:CALLS]->(callee)
        ON CREATE SET r.count = 1, r.source = $source
        ON MATCH  SET r.count = coalesce(r.count,0) + 1
        """,
        id=callsite_id,
        callee_key=callee_key,
        confidence=confidence,
        source=source,
    )

# --------------------------
# Prompt
# --------------------------
def build_batched_prompt(items: List[Dict]) -> str:
    blocks = []
    for it in items:
        cs = it["cs"]

        cand_blocks = []
        for c in it["candidates"]:
            excerpt = head_snippet(c.get("body", ""))
            cand_blocks.append(
                f"""- key: {c['key']}
  name: {c['name']}
  path: {c['path']}
  container: {c.get('container')}
  start_line: {c.get('start_line')}
  snippet:
    {excerpt}
    """
                )

            snippet = (cs.get("snippet") or "")[:1800]
            blocks.append(
                f"""callsite_id: {cs['id']}
    file: {cs['file']}
    line: {cs['line']}
    caller_key: {cs['caller_key']}
    callee_text: {cs['callee_text']}
    callee_name: {cs.get('callee_name')}
    language: {cs['language']}
    callsite_snippet:
    {snippet}

    candidates:
    {chr(10).join(cand_blocks)}
    """
            )

        ids = [it["cs"]["id"] for it in items]
        joined = "\n---\n".join(blocks)

        return f"""Resolve these callsites. Output JSON mapping callsite_id -> chosen_key_or_UNRESOLVED.

    callsite_ids: {ids}

    {joined}
    """

# --------------------------
# Main
# --------------------------
def main():
    log(f"NEO4J_URI={NEO4J_URI}")
    log(f"FETCH_LIMIT={FETCH_LIMIT} BATCH_SIZE={BATCH_SIZE} MAX_CANDIDATES={MAX_CANDIDATES}")
    log(f"GEMINI_MODEL={GEMINI_MODEL} SLEEP_BETWEEN={SLEEP_BETWEEN}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    resolved = 0
    unresolved = 0
    invalid = 0
    no_candidates = 0
    skipped = 0
    missing_caller = 0
    batches = 0

    with driver.session() as session:
        callsites = session.execute_read(fetch_unresolved_callsites, FETCH_LIMIT)
        log(f"Fetched unresolved callsites: {len(callsites)}")

        work = []
        for cs in callsites:
            callee_text = (cs.get("callee_text") or "").strip()
            callee_name = (cs.get("callee_name") or "").strip()
            caller_key = cs["caller_key"]

            caller = session.execute_read(fetch_caller_fn, caller_key)
            if not caller:
                session.execute_write(mark_unresolved, cs["id"], "missing_caller_node")
                missing_caller += 1
                continue

            if not callee_name or not callee_name.isidentifier():
                session.execute_write(mark_unresolved, cs["id"], "callee_not_identifier")
                skipped += 1
                continue

            if callee_name in BUILTINS:
                session.execute_write(mark_unresolved, cs["id"], "builtin_or_external")
                skipped += 1
                continue

            # Candidates are always real nodes from the graph
            candidates = session.execute_read(fetch_candidates_by_name, callee_name)

            if not candidates:
                session.execute_write(mark_unresolved, cs["id"], "no_repo_symbol_named_callee")
                no_candidates += 1
                continue

            # Deterministic: unique match by name => resolve immediately
            if len(candidates) == 1:
                only_key = candidates[0]["key"]
                session.execute_write(apply_resolution, cs["id"], only_key, 0.9, "unique_name")
                resolved += 1
                continue

            # Otherwise defer to LLM
            work.append({"cs": cs, "candidates": candidates})

        log(f"Work items for LLM: {len(work)} | resolved_now={resolved} | skipped={skipped} | no_repo_symbol={no_candidates} | missing_caller={missing_caller}")

        for batch in chunk(work, BATCH_SIZE):
            batches += 1
            ids = [it["cs"]["id"] for it in batch]
            log(f"\n[Batch {batches}] size={len(batch)} first_id={ids[0]}")

            prompt = build_batched_prompt(batch)

            raw = gemini_text(SYSTEM, prompt, model=GEMINI_MODEL).strip()
            log("[LLM raw output first 800 chars]\n" + raw[:800])
            time.sleep(SLEEP_BETWEEN)

            cleaned = extract_json_object(raw)
            log("[LLM cleaned json first 800 chars]\n" + cleaned[:800])

            try:
                mapping = json.loads(cleaned)
                if not isinstance(mapping, dict):
                    raise ValueError("parsed JSON is not an object/dict")
            except Exception as e:
                log(f"[Batch {batches}] JSON parse FAILED: {e}")
                for it in batch:
                    session.execute_write(mark_unresolved, it["cs"]["id"], "llm_bad_json")
                    invalid += 1
                continue

            for it in batch:
                cs = it["cs"]
                cid = cs["id"]
                choice = mapping.get(cid, "UNRESOLVED")

                cand_keys = {c["key"] for c in it["candidates"]}

                if choice == "UNRESOLVED":
                    session.execute_write(mark_unresolved, cid, "llm_unresolved")
                    unresolved += 1
                    continue

                if choice not in cand_keys:
                    session.execute_write(mark_unresolved, cid, "llm_invalid_key")
                    invalid += 1
                    continue

                # Block bogus self-loop unless exact recursion (caller_name == callee_name)
                caller_key = cs["caller_key"]
                caller_name = caller_key.split("::")[1] if "::" in caller_key else ""
                callee_name = (cs.get("callee_name") or "").strip()
                if choice == caller_key and caller_name and callee_name and caller_name != callee_name:
                    session.execute_write(mark_unresolved, cid, "blocked_self_loop")
                    invalid += 1
                    continue

                # confidence heuristic
                callee_name = (cs.get("callee_name") or "").strip()
                name_matches = sum(1 for c in it["candidates"] if c["name"] == callee_name) if callee_name else 0
                confidence = 0.75 if name_matches == 1 else 0.55

                session.execute_write(apply_resolution, cid, choice, confidence, "llm(gemini_batch)")
                resolved += 1

    driver.close()

    out = {
        "resolved": resolved,
        "unresolved": unresolved,
        "invalid": invalid,
        "no_repo_symbol": no_candidates,
        "skipped": skipped,
        "missing_caller": missing_caller,
        "batches": batches,
    }
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()